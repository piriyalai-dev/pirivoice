"""🖼️ รูปภาพกลางของส่วนอื่น (บอร์ด · ประกาศ · กิจกรรม · โปรไฟล์)

**เส้นทางข้อมูล** (ลำดับเดียวกับ `image_service` ของเรื่อง — จงใจให้เหมือนกัน)
    frontend อัปรูป → process (Pillow, threadpool) → storage.write (volume)
                  → INSERT media_images + audit (transaction เดียว)
    frontend <img src=signed-url> → GET /api/media/file/{id} → verify sig (scope=media)
                  → policy.assert_can_view **สด ๆ** → FileResponse

**ต่างจาก `issue_images` อย่างไร**
  - 1 ตาราง polymorphic `media_images(owner_type, owner_id)` แทน FK ไปยังตารางเจ้าของ
    (เจ้าของ 5 ตารางใช้ FK ร่วมไม่ได้) ⇒ ความปลอดภัยตอนเจ้าของถูกลบ/ซ่อนมาจาก policy
    ที่ตรวจ **ทุกครั้งที่เสิร์ฟ** ไม่ใช่จาก FK
  - ไม่มี read receipt (receipt เป็นความหมายเฉพาะของเรื่อง)
  - การ "เปลี่ยนปก" = soft-delete แถวเดิม + INSERT ใหม่ ใน transaction เดียว
    (partial unique index `uq_media_single_cover` จึงไม่เคยเห็นสองแถวที่ยังไม่ถูกลบ)

⚠️ **ไม่แตะ `issue_images` / `/api/images` เดิมเลย** — ฟีเจอร์ที่ใช้อยู่ต้องไม่เสี่ยง
"""
import logging
import uuid
from typing import Optional, Sequence, Tuple

import asyncpg
from starlette.concurrency import run_in_threadpool

from core.config import settings
from core.exceptions import (
    ForbiddenError,
    NotFoundError,
    PayloadTooLargeError,
    RateLimitError,
    ValidationError,
)
from core.logger import AuditLogger
from core.media import MediaStorageError, get_media_storage
from core.media_signing import sign_url, verify_signature
from services import issue_service
from services.media_policies import MediaPolicy, get_policy

logger = logging.getLogger("API_MEDIA")

# ⚠️ ยืมตัวประมวลผลรูปของ issue **โดย import** ไม่ copy — พฤติกรรม EXIF/resize/HEIC/
#    decompression-bomb ต้องมีชุดเดียว (ถ้ามีวันที่ย้ายไป `core/media/processing.py`
#    ให้แก้ import ที่นี่จุดเดียว)
from services.image_service import _process_image_sync

# 👍 scope ลายเซ็นของรูปกลาง — ต้องตรงกับ `core/media_signing._SCOPE_CONFIG`
_SIGN_SCOPE = "media"


# ============================================================
# 🔧 helper
# ============================================================
def _limits(policy: MediaPolicy) -> dict:
    return {
        "max_per_owner": policy.max_per_owner,
        "max_per_request": int(settings.MEDIA_MAX_UPLOAD_PER_REQUEST),
        "size_limit_mb": int(settings.MEDIA_IMAGE_SIZE_LIMIT_MB),
    }


def _image_to_dict(row, viewer_id: int) -> dict:
    """แถว media_images → payload (signed URL relative path)

    ⚠️ **ไม่ส่ง `uploaded_by`** — เนื้อหาบางชนิด (บอร์ด/คอมเมนต์) เป็น anonymous
       และรูปเป็นของเจ้าของเนื้อหา ⇒ เปิดเผยผู้อัป = เปิดเผยผู้เขียน
    """
    image_id = str(row["id"])
    return {
        "id": image_id,
        "owner_type": row["owner_type"],
        "owner_id": row["owner_id"],
        "kind": row["kind"],
        "url": sign_url(image_id, "full", viewer_id, scope=_SIGN_SCOPE),
        "thumb_url": sign_url(image_id, "thumb", viewer_id, scope=_SIGN_SCOPE),
        "width": row["width"],
        "height": row["height"],
        "bytes": row["bytes"],
        "created_at": row["created_at"],
    }


# ============================================================
# 📤 อัปโหลด
# ============================================================
async def upload_media(
    pool: asyncpg.Pool,
    user_id: int,
    owner_type: str,
    owner_id: int,
    files: Sequence[Tuple[str, bytes]],
    requested_kind: Optional[str] = None,
) -> dict:
    """อัปโหลดรูปให้เจ้าของหนึ่งราย (1 ชนิดต่อ owner_type, 1 รูปต่อเจ้าของ)

    ⚠️ ประมวลผลรูป **ก่อน** เปิด transaction — Pillow ใช้ CPU หลายร้อย ms ต่อรูป
       ถ้าถือ `FOR UPDATE` บนแถวเจ้าของระหว่างนั้น ผู้ใช้อื่นที่แตะเนื้อหาเดียวกันจะรอฟรี
    """
    if not files:
        raise ValidationError("ไม่มีไฟล์ที่จะอัปโหลด")
    policy = get_policy(owner_type)

    kind = (requested_kind or policy.kind).strip().lower()
    if kind != policy.kind:
        raise ValidationError(f"แนบรูปชนิด '{kind}' กับเนื้อหาชนิดนี้ไม่ได้")

    per_request = int(settings.MEDIA_MAX_UPLOAD_PER_REQUEST)
    if len(files) > per_request:
        raise ValidationError(f"อัปโหลดได้ครั้งละไม่เกิน {per_request} รูป")
    if len(files) > policy.max_per_owner:
        raise ValidationError(f"แนบรูปได้สูงสุด {policy.max_per_owner} รูป")

    limit_bytes = int(settings.MEDIA_IMAGE_SIZE_LIMIT_MB) * 1024 * 1024
    processed = []
    for _filename, raw in files:
        if len(raw) > limit_bytes:
            raise PayloadTooLargeError(
                f"รูปใหญ่เกิน {settings.MEDIA_IMAGE_SIZE_LIMIT_MB} MB"
            )
        processed.append(await run_in_threadpool(_process_image_sync, raw))

    storage = get_media_storage()
    role = await issue_service.user_level(pool, user_id)
    # ⚠️ ไฟล์ที่เขียนแล้วภายในคำขอนี้ — ใช้ลบทิ้งถ้า transaction ล้ม (ไฟล์กำพร้า
    #    ที่ purge เก็บกวาดได้อยู่แล้ว แต่ลบทันทีประหยัดดิสก์และทำให้ verify สะอาด)
    written: list[str] = []
    inserted: list = []

    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                owner_row = await policy.lock_owner(conn, owner_id)
                await policy.assert_can_upload(conn, user_id, owner_id, owner_row)

                existing = await conn.fetchval(
                    """
                    SELECT COUNT(*) FROM media_images
                    WHERE owner_type = $1 AND owner_id = $2 AND kind = $3
                      AND deleted_at IS NULL
                    """,
                    owner_type, owner_id, kind,
                )
                # เพดานเดียวต่อเจ้าของ = "แทนที่ของเดิม" ไม่ใช่ "เพิ่มอีกรูป"
                if policy.max_per_owner == 1:
                    await conn.execute(
                        """
                        UPDATE media_images SET deleted_at = NOW()
                        WHERE owner_type = $1 AND owner_id = $2 AND kind = $3
                          AND deleted_at IS NULL
                        """,
                        owner_type, owner_id, kind,
                    )
                elif existing + len(processed) > policy.max_per_owner:
                    raise ValidationError(
                        f"แนบรูปได้สูงสุด {policy.max_per_owner} รูป"
                    )

                # Rate limit รายชั่วโมง — นับข้ามเจ้าของ/ส่วน (กันคนเดียวสแปมทุกหน้า)
                # ⚠️ **ไม่กรอง deleted_at** — "การเปลี่ยนปก" soft-delete แถวเดิมทิ้งก่อนเสมอ
                #    ถ้ากรองด้วย จะสลับปกได้ไม่จำกัดครั้งแม้เพดานเหลือ 0
                #    (นับ "งานที่ทำ" ไม่ใช่ "รูปที่ยังอยู่" — purge เก็บแถวเก่าให้เองใน 30 วัน)
                used_last_hour = await conn.fetchval(
                    """
                    SELECT COUNT(*) FROM media_images
                    WHERE uploaded_by = $1
                      AND created_at > NOW() - INTERVAL '1 hour'
                    """,
                    user_id,
                )
                hourly = int(settings.MEDIA_MAX_UPLOAD_PER_HOUR)
                if used_last_hour + len(processed) > hourly:
                    raise RateLimitError(f"อัปโหลดรูปได้ไม่เกิน {hourly} รูปต่อชั่วโมง")

                for item in processed:
                    image_id = uuid.uuid4()
                    storage_path = f"media/{owner_type}/{owner_id}/{image_id}.webp"
                    thumb_path = f"media/{owner_type}/{owner_id}/{image_id}_thumb.webp"

                    # ⚠️ เขียนไฟล์ก่อน INSERT — ถ้าตายกลางทางจะเหลือไฟล์กำพร้า (collect ได้)
                    #    กลับกัน (INSERT ก่อน) = แถวชี้ไฟล์ที่ไม่มี → GET 404 ตลอดกาล
                    await storage.write(storage_path, item["data"])
                    await storage.write(thumb_path, item["thumb_data"])
                    written.extend((storage_path, thumb_path))

                    row = await conn.fetchrow(
                        """
                        INSERT INTO media_images (
                            id, owner_type, owner_id, kind, uploaded_by, uploader_role,
                            storage_path, thumb_path, sha256, thumb_sha256,
                            mime, bytes, width, height
                        ) VALUES (
                            $1, $2, $3, $4, $5, $6,
                            $7, $8, $9, $10,
                            'image/webp', $11, $12, $13
                        )
                        RETURNING *
                        """,
                        image_id, owner_type, owner_id, kind, user_id, role,
                        storage_path, thumb_path, item["sha256"], item["thumb_sha256"],
                        item["bytes"], item["width"], item["height"],
                    )
                    await AuditLogger("media_service").log(
                        conn=conn,
                        action="CREATE_MEDIA_IMAGE",
                        actor_identifier=str(user_id),
                        client_source="web",
                        user_id=user_id,
                        entity_type="media_image",
                        entity_id=str(image_id),
                        new_values={
                            "owner_type": owner_type,
                            "owner_id": owner_id,
                            "kind": kind,
                            "bytes": item["bytes"],
                            "width": item["width"],
                            "height": item["height"],
                            "sha256": item["sha256"],
                            "storage_path": storage_path,
                        },
                    )
                    inserted.append(row)
    except BaseException:
        for key in written:
            try:
                await storage.delete(key)
            except Exception:  # best-effort — อย่ากลบ exception ต้นเหตุ
                logger.warning("ลบไฟล์ที่เขียนไว้ไม่สำเร็จ: %s", key)
        raise

    return {
        "items": [_image_to_dict(r, user_id) for r in inserted],
        "limits": _limits(policy),
    }


# ============================================================
# 📋 ดูรายการ
# ============================================================
async def list_media(
    pool: asyncpg.Pool, user_id: int, owner_type: str, owner_id: int
) -> dict:
    policy = get_policy(owner_type)
    async with pool.acquire() as conn:
        await policy.assert_can_view(conn, user_id, owner_id)
        rows = await conn.fetch(
            """
            SELECT * FROM media_images
            WHERE owner_type = $1 AND owner_id = $2 AND deleted_at IS NULL
            ORDER BY created_at, id
            """,
            owner_type, owner_id,
        )
    return {
        "items": [_image_to_dict(r, user_id) for r in rows],
        "limits": _limits(policy),
    }


async def signed_media_map(
    conn: asyncpg.Connection,
    owner_type: str,
    owner_ids: Sequence[int],
    viewer_id: int,
    *,
    kind: Optional[str] = None,
) -> dict[int, list[dict]]:
    """แนบรูปให้หลายเจ้าของในคิวรีเดียว — ใช้ใน list endpoints (กัน N+1)

    ⚠️ `owner_id` เป็น INTEGER ⇒ `int[]` (ไม่ใช่ `uuid[]` — มีแต่ `media_images.id` ที่เป็น uuid)
    """
    ids = [int(x) for x in owner_ids]
    if not ids:
        return {}
    rows = await conn.fetch(
        """
        SELECT * FROM media_images
        WHERE owner_type = $1 AND owner_id = ANY($2::int[]) AND deleted_at IS NULL
          AND ($3::text IS NULL OR kind = $3)
        ORDER BY created_at ASC, id ASC
        """,
        owner_type, ids, kind,
    )
    out: dict[int, list[dict]] = {}
    for r in rows:
        out.setdefault(r["owner_id"], []).append(_image_to_dict(r, viewer_id))
    return out


async def get_avatar(
    conn: asyncpg.Connection, owner_id: int, viewer_id: int
) -> Optional[dict]:
    """รูปโปรไฟล์ของ user (หรือ None) — ผู้ดูมักเป็นเจ้าของเอง ⇒ ไม่ต้อง batch"""
    row = await conn.fetchrow(
        """
        SELECT * FROM media_images
        WHERE owner_type = 'user' AND owner_id = $1 AND kind = 'avatar'
          AND deleted_at IS NULL
        ORDER BY created_at DESC
        LIMIT 1
        """,
        owner_id,
    )
    return _image_to_dict(row, viewer_id) if row else None


async def avatars_map(
    conn: asyncpg.Connection, user_ids: Sequence[int], viewer_id: int
) -> dict[int, dict]:
    """avatar ของหลายผู้ใช้ (คิวรีเดียว) — สำหรับ payload ที่แสดงผู้เขียน/ผู้คอมเมนต์"""
    m = await signed_media_map(conn, "user", user_ids, viewer_id, kind="avatar")
    return {uid: imgs[0] for uid, imgs in m.items() if imgs}


# ============================================================
# 👁️ เสิร์ฟไฟล์
# ============================================================
async def resolve_media_for_serving(
    pool: asyncpg.Pool,
    image_id: str,
    variant: Optional[str],
    viewer: Optional[str],
    exp: Optional[str],
    sig: Optional[str],
):
    """ตรวจ signed URL (scope=media) + สิทธิ์ **สด ๆ** แล้วคืน `(row, path)`

    ลำดับ: ลายเซ็น (ไม่แตะ DB) → แถวรูป → policy.assert_can_view → ไฟล์มีจริง
    """
    verified = verify_signature(
        str(image_id), variant, viewer, exp, sig, scope=_SIGN_SCOPE
    )
    if not verified:
        raise ForbiddenError("ลิงก์รูปไม่ถูกต้องหรือหมดอายุ")
    viewer_id, variant = verified

    try:
        image_uuid = uuid.UUID(str(image_id))
    except (ValueError, AttributeError, TypeError):
        raise NotFoundError("ไม่พบรูปนี้") from None

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM media_images WHERE id = $1 AND deleted_at IS NULL",
            image_uuid,
        )
        if not row:
            raise NotFoundError("ไม่พบรูปนี้")
        policy = get_policy(row["owner_type"])
        await policy.assert_can_view(conn, viewer_id, row["owner_id"])

    key = row["thumb_path"] if variant == "thumb" and row["thumb_path"] else row["storage_path"]
    storage = get_media_storage()
    try:
        local_path = storage.local_path(key)
        exists = local_path is not None and await storage.exists(key)
    except MediaStorageError:
        # key ใน DB ผิดรูปแบบ/หลุดนอก root ⇒ ปฏิบัติเหมือนไฟล์หาย (ห้ามพยายามเปิด path นั้น)
        local_path, exists = None, False
    if local_path is None or not exists:
        logger.warning("media file missing: image_id=%s key=%s", row["id"], key)
        raise NotFoundError("ไม่พบไฟล์รูปในที่จัดเก็บ")

    return row, local_path


# ============================================================
# 🗑️ ลบ (soft delete)
# ============================================================
async def delete_media(
    pool: asyncpg.Pool, user_id: int, owner_type: str, owner_id: int, image_id: str
) -> dict:
    try:
        image_uuid = uuid.UUID(str(image_id))
    except (ValueError, AttributeError, TypeError):
        raise NotFoundError("ไม่พบรูปนี้") from None

    policy = get_policy(owner_type)
    async with pool.acquire() as conn:
        async with conn.transaction():
            # เจ้าของหาย/ถูกซ่อน ⇒ 404 (เหมือน list)
            await policy.assert_can_view(conn, user_id, owner_id)
            row = await conn.fetchrow(
                """
                SELECT * FROM media_images
                WHERE id = $1 AND owner_type = $2 AND owner_id = $3
                  AND deleted_at IS NULL
                FOR UPDATE
                """,
                image_uuid, owner_type, owner_id,
            )
            if not row:
                raise NotFoundError("ไม่พบรูปนี้")
            await policy.assert_can_delete(conn, user_id, owner_id, row)

            await conn.execute(
                "UPDATE media_images SET deleted_at = NOW() WHERE id = $1", image_uuid
            )
            await AuditLogger("media_service").log(
                conn=conn,
                action="DELETE_MEDIA_IMAGE",
                actor_identifier=str(user_id),
                client_source="web",
                user_id=user_id,
                entity_type="media_image",
                entity_id=str(image_uuid),
                old_values={
                    "owner_type": owner_type,
                    "owner_id": owner_id,
                    "kind": row["kind"],
                    "storage_path": row["storage_path"],
                },
            )

    # ไฟล์ยังอยู่บนดิสก์จนกว่า purge (MEDIA_PURGE_AFTER_DAYS)
    return {"status": "deleted", "id": str(image_uuid)}
