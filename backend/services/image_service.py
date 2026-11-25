"""🖼️ รูปภาพของเรื่อง — ประมวลผล, อัปโหลด, แสดง, ลบ และ read receipt

**เส้นทางข้อมูล**
    frontend อัปรูป → process (Pillow, threadpool) → storage.write (volume)
                  → INSERT issue_images + audit (transaction เดียว)
    frontend <img src=signed-url> → GET /api/images/{id} → verify sig → assert_can_view
                  → FileResponse + upsert issue_image_views (best-effort)

**สิ่งที่ service นี้ไม่ทำ (โดยเจตนา)**
  - ไม่ลบไฟล์จริงเมื่อ soft-delete — purge script ทำ (เฟส 8) เพราะการลบไฟล์ทันที
    ทำให้กู้คืนไม่ได้เมื่อผู้ใช้กดผิด และ backup ยังควรเห็นไฟล์ในรอบถัดไป
  - ไม่ตัดสินใจว่าใครควรเห็นเรื่อง — เรียก `issue_service.assert_can_view` ตัวเดียวกับ
    หน้าเรื่อง/คอมเมนต์ (แหล่งความจริงเดียว)
"""
import hashlib
import io
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Sequence, Tuple

import asyncpg
from PIL import Image, ImageOps, UnidentifiedImageError
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

logger = logging.getLogger("API_MEDIA")

# 📱 HEIC/HEIF จาก iPhone — ลงทะเบียน opener ครั้งเดียวตอน import
#    ⚠️ ถ้าไลบรารีหายไป (build ผิด) ระบบยังทำงานได้กับ JPEG/PNG/WebP และจะตอบ 400
#       "ไม่รองรับไฟล์ชนิดนี้" แทนการ crash ทั้งโปรเซส
try:
    from pillow_heif import register_heif_opener

    register_heif_opener()
    _HEIF_OK = True
except Exception:  # pragma: no cover — ขึ้นกับ build image
    _HEIF_OK = False
    logger.warning("pillow-heif ใช้ไม่ได้ — จะไม่รองรับไฟล์ HEIC")

# Pillow รายงาน MPO สำหรับ JPEG หลายภาพจากกล้องมือถือ — ยังเป็น JPEG ที่อ่านได้
ALLOWED_FORMATS = {"JPEG", "MPO", "PNG", "WEBP"}
if _HEIF_OK:
    ALLOWED_FORMATS.add("HEIF")

# เพดานพิกเซลก่อนโหลด (กัน decompression bomb) — 50MP เกินกล้องมือถือทั่วไปแล้ว
MAX_PIXELS = 50_000_000
Image.MAX_IMAGE_PIXELS = MAX_PIXELS

# สถานะที่ถือว่า "เรื่องปิดแล้ว" — ผู้อัปโหลดลบรูปเองไม่ได้ (แอดมินยังลบได้)
CLOSED_STATUSES = ("resolved", "cancelled", "rejected")

_ISSUE_COLS = """
    id, room_id, reporter_id, reporter_room_id, current_level,
    current_assignee_id, is_anonymous, status
"""


# ============================================================
# 🧪 ประมวลผลรูป (sync — รันใน threadpool)
# ============================================================
def _to_rgb(im: Image.Image) -> Image.Image:
    """แปลงเป็น RGB โดยวางพื้นหลังสีขาวถ้ามีความโปร่งใส (WebP ไม่มี alpha ในผลลัพธ์)"""
    if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
        rgba = im.convert("RGBA")
        bg = Image.new("RGB", rgba.size, (255, 255, 255))
        bg.paste(rgba, mask=rgba.split()[-1])
        return bg
    return im.convert("RGB")


def _resize_longest(im: Image.Image, max_dim: int) -> Image.Image:
    """ย่อด้านยาวสุดให้ไม่เกิน max_dim — **ไม่ขยาย** รูปเล็ก"""
    longest = max(im.size)
    if longest <= max_dim:
        return im
    scale = max_dim / longest
    size = (max(1, round(im.width * scale)), max(1, round(im.height * scale)))
    return im.resize(size, Image.LANCZOS)


def _encode_webp(im: Image.Image) -> bytes:
    """บันทึกเป็น WebP โดย **ไม่ส่ง exif/icc** ⇒ metadata (รวม GPS) ถูกตัดทิ้ง"""
    buf = io.BytesIO()
    im.save(buf, format="WEBP", quality=int(settings.MEDIA_WEBP_QUALITY), method=4)
    return buf.getvalue()


def _process_image_sync(raw: bytes) -> dict:
    """ตรวจ + ย่อ + แปลง WebP + ทำ thumbnail — คืน bytes และ metadata

    ⚠️ **ฟังก์ชันนี้ blocking** (CPU + diskless) ⇒ ผู้เรียกต้องผ่าน `run_in_threadpool`
       ไม่งั้น event loop ของ FastAPI จะค้างทั้ง replica ระหว่างรอ Pillow
    """
    if not raw:
        raise ValidationError("ไฟล์รูปว่าง")
    try:
        with Image.open(io.BytesIO(raw)) as im:
            fmt = (im.format or "").upper()
            if fmt not in ALLOWED_FORMATS:
                raise ValidationError("รับเฉพาะไฟล์ JPEG, PNG, WebP หรือ HEIC")
            width, height = im.size
            if width * height > MAX_PIXELS:
                raise ValidationError("รูปมีขนาดพิกเซลใหญ่เกินไป")
            if min(width, height) < int(settings.MEDIA_MIN_DIMENSION):
                raise ValidationError(
                    f"รูปเล็กเกินไป — ต้องมีด้านสั้นอย่างน้อย {settings.MEDIA_MIN_DIMENSION}px"
                )
            im.load()
            im = ImageOps.exif_transpose(im)  # หมุนตาม EXIF แล้ว **ทิ้ง** tag ไปพร้อมกัน
            im = _to_rgb(im)

            full = _resize_longest(im, int(settings.MEDIA_MAX_DIMENSION))
            thumb = full.copy()
            thumb.thumbnail(
                (int(settings.MEDIA_THUMB_DIMENSION), int(settings.MEDIA_THUMB_DIMENSION)),
                Image.LANCZOS,
            )
            full_bytes = _encode_webp(full)
            thumb_bytes = _encode_webp(thumb)
            out_w, out_h = full.size
    except ValidationError:
        raise
    except Image.DecompressionBombError:
        raise ValidationError("รูปมีขนาดพิกเซลใหญ่เกินไป")
    except (UnidentifiedImageError, OSError, ValueError) as e:
        raise ValidationError("ไฟล์รูปเสียหรือไม่ใช่รูปภาพที่รองรับ") from e

    return {
        "data": full_bytes,
        "thumb_data": thumb_bytes,
        "sha256": hashlib.sha256(full_bytes).hexdigest(),
        "thumb_sha256": hashlib.sha256(thumb_bytes).hexdigest(),
        "bytes": len(full_bytes),
        "width": out_w,
        "height": out_h,
    }


# ============================================================
# 🔧 helper
# ============================================================
def _limits() -> dict:
    return {
        "max_report": int(settings.MEDIA_MAX_REPORT_IMAGES),
        "max_progress": int(settings.MEDIA_MAX_PROGRESS_IMAGES),
        "max_per_request": int(settings.MEDIA_MAX_UPLOAD_PER_REQUEST),
        "size_limit_mb": int(settings.MEDIA_IMAGE_SIZE_LIMIT_MB),
    }


def _max_images_for(kind: str) -> int:
    return int(
        settings.MEDIA_MAX_REPORT_IMAGES if kind == "report" else settings.MEDIA_MAX_PROGRESS_IMAGES
    )


async def _fetch_issue(conn, issue_id: int, *, for_update: bool = False):
    query = f"SELECT {_ISSUE_COLS} FROM issues WHERE id = $1 AND deleted_at IS NULL"
    if for_update:
        query += " FOR UPDATE"
    row = await conn.fetchrow(query, issue_id)
    if not row:
        raise NotFoundError("ไม่พบเรื่องนี้")
    return row


def _image_to_dict(row, viewer_id: int, receipt: Optional[dict] = None) -> dict:
    image_id = str(row["id"])
    return {
        "id": image_id,
        "issue_id": row["issue_id"],
        "kind": row["kind"],
        "url": sign_url(image_id, "full", viewer_id),
        "thumb_url": sign_url(image_id, "thumb", viewer_id),
        "width": row["width"],
        "height": row["height"],
        "bytes": row["bytes"],
        "uploaded_by": row["uploaded_by"],
        "created_at": row["created_at"],
        "receipt": receipt,
    }


# ============================================================
# 📤 อัปโหลด
# ============================================================
async def upload_images(
    pool: asyncpg.Pool,
    user_id: int,
    issue_id: int,
    files: Sequence[Tuple[str, bytes]],
    requested_kind: Optional[str] = None,
) -> dict:
    """อัปโหลด 1–3 รูปเข้าธรรมชาติของเรื่อง — ผู้แจ้ง (report) หรือผู้รับปัจจุบัน (progress)

    ⚠️ **ประมวลผลรูปก่อนเปิด transaction** — Pillow ใช้ CPU หลายร้อย ms ต่อรูป
       ถ้าถือ `FOR UPDATE` บนแถวเรื่องระหว่างนั้น ผู้ใช้อื่นที่เปิดเรื่องเดียวกัน
       (เช่นผู้รับ กดรับเรื่อง) จะรอค้างโดยไม่มีเหตุผล
    """
    if not files:
        raise ValidationError("ไม่มีไฟล์ที่จะอัปโหลด")
    per_request = int(settings.MEDIA_MAX_UPLOAD_PER_REQUEST)
    if len(files) > per_request:
        raise ValidationError(f"อัปโหลดได้ครั้งละไม่เกิน {per_request} รูป")

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

    async with pool.acquire() as conn:
        async with conn.transaction():
            issue = await _fetch_issue(conn, issue_id, for_update=True)
            is_reporter = issue["reporter_id"] == user_id
            is_assignee = issue["current_assignee_id"] == user_id

            if is_reporter and is_assignee:
                # ผู้แจ้งที่กดรับเรื่องเอง (เป็นไปได้ในห้องเล็ก) — ให้ form field ตัดสิน
                kind = (requested_kind or "report").strip().lower()
                if kind not in ("report", "progress"):
                    raise ValidationError("kind ต้องเป็น report หรือ progress")
            elif is_reporter:
                kind = "report"
            elif is_assignee:
                kind = "progress"
            else:
                raise ForbiddenError("เฉพาะผู้แจ้งหรือผู้รับผิดชอบปัจจุบันเท่านั้นที่แนบรูปได้")

            # จำนวนต่อชนิด (นับเฉพาะที่ยังไม่ถูกลบ)
            existing = await conn.fetchval(
                """
                SELECT COUNT(*) FROM issue_images
                WHERE issue_id = $1 AND kind = $2 AND deleted_at IS NULL
                """,
                issue_id, kind,
            )
            max_images = _max_images_for(kind)
            if existing + len(processed) > max_images:
                raise ValidationError(f"แนบรูปประเภทนี้ได้สูงสุด {max_images} รูป")

            # Rate limit รายชั่วโมง — นับข้ามเรื่อง (กันคนเดียวสแปมหลายเรื่อง)
            used_last_hour = await conn.fetchval(
                """
                SELECT COUNT(*) FROM issue_images
                WHERE uploaded_by = $1
                  AND created_at > NOW() - INTERVAL '1 hour'
                  AND deleted_at IS NULL
                """,
                user_id,
            )
            hourly = int(settings.MEDIA_MAX_UPLOAD_PER_HOUR)
            if used_last_hour + len(processed) > hourly:
                raise RateLimitError(f"อัปโหลดรูปได้ไม่เกิน {hourly} รูปต่อชั่วโมง")

            inserted = []
            for item in processed:
                image_id = uuid.uuid4()
                storage_path = f"issues/{issue_id}/{image_id}.webp"
                thumb_path = f"issues/{issue_id}/{image_id}_thumb.webp"

                # ⚠️ เขียนไฟล์ก่อน INSERT — ถ้าตายระหว่างสองขั้นจะเหลือ "ไฟล์กำพร้า"
                #    (ไม่มีแถวชี้) ซึ่ง purge script เก็บกวาดได้
                #    ตรงกันข้าม (INSERT ก่อน) = แถวชี้ไฟล์ที่ไม่มี → GET 404 ตลอดกาล
                await storage.write(storage_path, item["data"])
                await storage.write(thumb_path, item["thumb_data"])

                row = await conn.fetchrow(
                    """
                    INSERT INTO issue_images (
                        id, issue_id, uploaded_by, uploader_role, kind,
                        storage_path, thumb_path, sha256, thumb_sha256,
                        mime, bytes, width, height
                    ) VALUES (
                        $1, $2, $3, $4, $5,
                        $6, $7, $8, $9,
                        'image/webp', $10, $11, $12
                    )
                    RETURNING *
                    """,
                    image_id, issue_id, user_id, role, kind,
                    storage_path, thumb_path, item["sha256"], item["thumb_sha256"],
                    item["bytes"], item["width"], item["height"],
                )
                await AuditLogger("image_service").log(
                    conn=conn,
                    action="CREATE_ISSUE_IMAGE",
                    actor_identifier=str(user_id),
                    client_source="web",
                    room_id=issue["room_id"],
                    user_id=user_id,
                    entity_type="issue_image",
                    entity_id=str(image_id),
                    new_values={
                        "issue_id": issue_id,
                        "kind": kind,
                        "bytes": item["bytes"],
                        "width": item["width"],
                        "height": item["height"],
                        "sha256": item["sha256"],
                        "storage_path": storage_path,
                    },
                )
                inserted.append(row)

    return {
        "items": [_image_to_dict(r, user_id) for r in inserted],
        "limits": _limits(),
    }


# ============================================================
# 📋 ดูรายการ + receipt
# ============================================================
def _build_receipts(issue_row, images, views) -> dict:
    """คำนวณ receipt ต่อ image — `views` = แถวทั้งหมดของ image ชุดนี้"""
    assignee_id = issue_row["current_assignee_id"]
    reporter_id = issue_row["reporter_id"]
    by_image: dict = {}
    for v in views:
        by_image.setdefault(v["image_id"], []).append(v)

    receipts = {}
    for img in images:
        rows = by_image.get(img["id"], [])
        assignee_view = next(
            (v for v in rows if assignee_id is not None and v["user_id"] == assignee_id), None
        )
        other_viewers = {
            v["user_id"] for v in rows if v["user_id"] not in (reporter_id, assignee_id)
        }
        receipts[img["id"]] = {
            "current_assignee_viewed": assignee_view is not None,
            "current_assignee_viewed_at": assignee_view["first_viewed_at"] if assignee_view else None,
            "other_viewer_count": len(other_viewers),
            "last_viewed_at": max((v["last_viewed_at"] for v in rows), default=None),
        }
    return receipts


async def list_images(pool: asyncpg.Pool, user_id: int, issue_id: int) -> dict:
    """รายการรูปของเรื่อง + signed URL + receipt (receipt เฉพาะผู้แจ้ง/แอดมิน)"""
    async with pool.acquire() as conn:
        issue = await _fetch_issue(conn, issue_id)
        await issue_service.assert_can_view(conn, pool, user_id, issue)

        images = await conn.fetch(
            """
            SELECT * FROM issue_images
            WHERE issue_id = $1 AND deleted_at IS NULL
            ORDER BY created_at, id
            """,
            issue_id,
        )

        receipts = {}
        show_receipt = user_id == issue["reporter_id"] or await issue_service.is_admin(conn, user_id)
        if show_receipt and images:
            views = await conn.fetch(
                """
                SELECT image_id, user_id, first_viewed_at, last_viewed_at, view_count
                FROM issue_image_views
                WHERE image_id = ANY($1::uuid[])
                """,
                [img["id"] for img in images],
            )
            receipts = _build_receipts(issue, images, views)

    return {
        "items": [_image_to_dict(img, user_id, receipts.get(img["id"])) for img in images],
        "limits": _limits(),
    }


# ============================================================
# 👁️ เสิร์ฟไฟล์ + บันทึกการเปิดดู
# ============================================================
async def _record_view(pool: asyncpg.Pool, image, issue, viewer_id: int) -> None:
    """upsert view แบบ dedupe 10 นาที — **ไม่บันทึก** ของผู้แจ้ง/ผู้อัปโหลดเอง

    ⚠️ "ของผู้แจ้ง" ในที่นี้คือผู้แจ้ง **เรื่อง** — ผู้แจ้งเปิดดูหลักฐานของตัวเอง
       ไม่ควรนับเป็นการอ่านของผู้รับ (ไม่งั้น badge "ผู้รับผิดชอบเปิดดูแล้ว"
       จะขึ้นทันทีที่ผู้แจ้งเปิดหน้าตัวเอง)
    """
    if viewer_id in (issue["reporter_id"], image["uploaded_by"]):
        return
    role = await issue_service.user_level(pool, viewer_id)
    cutoff = datetime.now(timezone.utc) - timedelta(
        minutes=max(0, int(settings.MEDIA_VIEW_DEDUPE_MINUTES))
    )
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO issue_image_views (
                image_id, user_id, viewer_role, first_viewed_at, last_viewed_at, view_count
            ) VALUES ($1, $2, $3, NOW(), NOW(), 1)
            ON CONFLICT (image_id, user_id) DO UPDATE SET
                last_viewed_at = NOW(),
                -- ค่าใน SET ถูกประเมินจากแถว "ก่อน" UPDATE ⇒ last_viewed_at ทางขวาคือค่าเก่า
                view_count = issue_image_views.view_count
                    + CASE WHEN issue_image_views.last_viewed_at < $4 THEN 1 ELSE 0 END,
                viewer_role = COALESCE(issue_image_views.viewer_role, EXCLUDED.viewer_role)
            """,
            image["id"], viewer_id, role, cutoff,
        )


async def resolve_image_for_serving(
    pool: asyncpg.Pool,
    image_id: str,
    variant: Optional[str],
    viewer: Optional[str],
    exp: Optional[str],
    sig: Optional[str],
):
    """ตรวจ signed URL + สิทธิ์ แล้วคืน `(image_row, path)` — ยังไม่ส่งไฟล์

    ลำดับสำคัญ:
      1) ตรวจลายเซ็น (ราคาถูก ไม่แตะ DB)
      2) โหลดแถวรูป + เรื่อง (404 ถ้าไม่มี/ถูกลบ)
      3) **ตรวจสิทธิ์ซ้ำ** ด้วย `assert_can_view` — ไม่เชื่อว่ามี URL แล้วจะเข้าได้
         (URL อาจถูกแชร์ต่อ หรือผู้ใช้ถูกย้ายห้อง/หมดวาระหลังสร้าง URL)
      4) ตรวจไฟล์มีจริง → 404 + log (ไม่ 500)
    """
    verified = verify_signature(str(image_id), variant, viewer, exp, sig)
    if not verified:
        raise ForbiddenError("ลิงก์รูปไม่ถูกต้องหรือหมดอายุ")
    viewer_id, variant = verified

    try:
        image_uuid = uuid.UUID(str(image_id))
    except (ValueError, AttributeError, TypeError):
        raise NotFoundError("ไม่พบรูปนี้")

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT
                im.*,
                i.id AS issue_row_id,
                i.room_id AS issue_room_id,
                i.reporter_id AS issue_reporter_id,
                i.reporter_room_id AS issue_reporter_room_id,
                i.current_level AS issue_current_level,
                i.current_assignee_id AS issue_assignee_id,
                i.is_anonymous AS issue_is_anonymous
            FROM issue_images im
            JOIN issues i ON i.id = im.issue_id AND i.deleted_at IS NULL
            WHERE im.id = $1 AND im.deleted_at IS NULL
            """,
            image_uuid,
        )
        if not row:
            raise NotFoundError("ไม่พบรูปนี้")

        issue_row = {
            "id": row["issue_row_id"],
            "room_id": row["issue_room_id"],
            "reporter_id": row["issue_reporter_id"],
            "reporter_room_id": row["issue_reporter_room_id"],
            "current_level": row["issue_current_level"],
            "current_assignee_id": row["issue_assignee_id"],
            "is_anonymous": row["issue_is_anonymous"],
        }
        await issue_service.assert_can_view(conn, pool, viewer_id, issue_row)

    key = row["thumb_path"] if variant == "thumb" and row["thumb_path"] else row["storage_path"]
    storage = get_media_storage()
    try:
        local_path = storage.local_path(key)
        exists = local_path is not None and await storage.exists(key)
    except MediaStorageError:
        # storage_path ใน DB ผิดรูปแบบ/หลุดนอก root — ปฏิบัติเหมือน "ไฟล์หาย"
        # (404 + log) ไม่ใช่ 500 และ **ห้ามพยายามเปิด path นั้น**
        local_path, exists = None, False
    if local_path is None or not exists:
        # ⚠️ ไฟล์หาย ≠ ระบบพัง — ตอบ 404 และ log ไว้ให้ verify_media.py (เฟส 8) ตามเจอ
        logger.warning(
            "media file missing: image_id=%s key=%s", row["id"], key
        )
        raise NotFoundError("ไม่พบไฟล์รูปในที่จัดเก็บ")

    try:
        await _record_view(pool, row, issue_row, viewer_id)
    except Exception:  # best-effort — การบันทึก receipt ต้องไม่ทำให้ดูรูปไม่ได้
        logger.exception("record view failed: image_id=%s viewer=%s", row["id"], viewer_id)

    return row, local_path


# ============================================================
# 🗑️ ลบ (soft delete)
# ============================================================
async def delete_image(
    pool: asyncpg.Pool, user_id: int, issue_id: int, image_id: str
) -> dict:
    """soft delete — ผู้อัปโหลดเอง (เรื่องยังไม่ปิด) หรือแอดมิน"""
    try:
        image_uuid = uuid.UUID(str(image_id))
    except (ValueError, AttributeError, TypeError):
        raise NotFoundError("ไม่พบรูปนี้")

    async with pool.acquire() as conn:
        async with conn.transaction():
            issue = await _fetch_issue(conn, issue_id, for_update=True)
            row = await conn.fetchrow(
                """
                SELECT * FROM issue_images
                WHERE id = $1 AND issue_id = $2 AND deleted_at IS NULL
                FOR UPDATE
                """,
                image_uuid, issue_id,
            )
            if not row:
                raise NotFoundError("ไม่พบรูปนี้")

            admin = await issue_service.is_admin(conn, user_id)
            if not admin:
                if row["uploaded_by"] != user_id:
                    raise ForbiddenError("ลบได้เฉพาะรูปที่คุณอัปโหลดเอง")
                if issue["status"] in CLOSED_STATUSES:
                    raise ForbiddenError("เรื่องปิดแล้ว — ลบรูปไม่ได้")

            await conn.execute(
                "UPDATE issue_images SET deleted_at = NOW() WHERE id = $1", image_uuid
            )
            await AuditLogger("image_service").log(
                conn=conn,
                action="DELETE_ISSUE_IMAGE",
                actor_identifier=str(user_id),
                client_source="web",
                room_id=issue["room_id"],
                user_id=user_id,
                entity_type="issue_image",
                entity_id=str(image_uuid),
                old_values={
                    "issue_id": issue_id,
                    "kind": row["kind"],
                    "uploaded_by": row["uploaded_by"],
                    "storage_path": row["storage_path"],
                },
            )

    # ไฟล์ยังอยู่บนดิสก์จนกว่า purge (MEDIA_PURGE_AFTER_DAYS) — กันกดลบผิดแล้วกู้ไม่ได้
    return {"status": "deleted", "id": str(image_uuid)}
