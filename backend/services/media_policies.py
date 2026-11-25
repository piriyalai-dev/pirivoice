"""🔐 นโยบายของรูปกลาง `media_images` — registry แบบ **fail-closed**

⭐ **ทำไมต้องเป็น registry ไม่ใช่ if/elif ใน service**

   รูปผูกกับ "เจ้าของ" 5 ชนิดที่ไม่มี FK ร่วมกัน (board · board_comment · announcement ·
   event · user) ⇒ ถ้า service ต้องรู้ว่าแต่ละชนิดตรวจสิทธิ์อย่างไร โค้ดจะบวมและมีจุด
   "ลืมตรวจ" ได้ง่าย · registry ทำให้: (ก) `owner_type` ที่ไม่รู้จัก **raise ทันที**
   (ไม่มี `.get()` default — ชนิดใหม่ที่ลืมลงทะเบียนจะแนบรูปไม่ได้ ไม่ใช่แนบได้โดยไม่มีใครตรวจ)
   (ข) การเพิ่มส่วนใหม่ในอนาคต = เพิ่มคลาสเดียว ไม่แตะ service/router

⚠️ **ทุก policy เรียกตรรกะของโดเมนนั้นซ้ำ** (`_has_council_authority`,
   `require_permission_anywhere`) — ห้ามประดิษฐ์กติกาการมองเห็นชุดที่สอง
   ไม่งั้นรูปจะโผล่/ซ่อนไม่ตรงกับตัวเนื้อหาเอง

⚠️ `assert_can_view` ถูกเรียก **ทุกครั้งที่เสิร์ฟไฟล์** (ไม่ใช่แค่ตอนออก URL)
   ⇒ บอร์ดที่ถูกซ่อน/คอมเมนต์ที่ถูก hide จะหยุดเสิร์ฟทันที แม้ URL ยังไม่หมดอายุ

📌 ไม่อยู่ใน `core/` โดยเจตนา — policy ต้อง import จาก `services/` (issue_service) ซึ่ง
   core ต้องไม่พึ่ง ⇒ วางใน services เพื่อไม่ให้ dependency ทิศทางย้อน
"""
from dataclasses import dataclass

import asyncpg

from core.config import settings
from core.exceptions import ForbiddenError, NotFoundError, ValidationError
from core.rbac import require_permission_anywhere
from services import issue_service


@dataclass(frozen=True)
class MediaPolicy:
    """สัญญาของเจ้าของรูปหนึ่งชนิด — ค่าคงที่ + การตรวจสิทธิ์ 3 ทาง"""

    owner_type: str
    kind: str            # ชนิดรูปเดียวที่อนุญาต (cover / attachment / avatar)
    max_per_owner: int

    async def lock_owner(self, conn: asyncpg.Connection, owner_id: int):
        """ล็อกแถวเจ้าของ (`FOR UPDATE`) — raise NotFoundError ถ้าเจ้าของหาย/ถูกซ่อน

        ⚠️ เรียก "ก่อน" ตรวจเพดานจำนวน เพื่อให้การอัปพร้อมกันสองคำขอไม่ผ่านทั้งคู่
        """
        raise NotImplementedError

    async def assert_can_upload(
        self, conn: asyncpg.Connection, user_id: int, owner_id: int, owner_row
    ) -> None:
        raise NotImplementedError

    async def assert_can_view(
        self, conn: asyncpg.Connection, user_id: int, owner_id: int
    ) -> None:
        raise NotImplementedError

    async def assert_can_delete(
        self, conn: asyncpg.Connection, user_id: int, owner_id: int, image_row
    ) -> None:
        raise NotImplementedError


# ============================================================
# PIRI Board — ปกโพสต์
# ============================================================
class BoardPolicy(MediaPolicy):
    async def lock_owner(self, conn, owner_id):
        row = await conn.fetchrow(
            """
            SELECT id, author_id, status
            FROM piri_boards
            WHERE id = $1 AND deleted_at IS NULL
            FOR UPDATE
            """,
            owner_id,
        )
        # board ที่ถูกซ่อน = 404 เหมือน get_board_detail (ไม่เปิดเผยว่ามีอยู่)
        if not row or row["status"] == "hidden":
            raise NotFoundError("ไม่พบโพสต์นี้")
        return row

    async def assert_can_upload(self, conn, user_id, owner_id, owner_row):
        if owner_row["author_id"] == user_id:
            return
        if await issue_service._has_council_authority(conn, user_id):
            return
        raise ForbiddenError("แนบรูปได้เฉพาะเจ้าของโพสต์หรือสภานักเรียน")

    async def assert_can_view(self, conn, user_id, owner_id):
        row = await conn.fetchrow(
            "SELECT status FROM piri_boards WHERE id = $1 AND deleted_at IS NULL",
            owner_id,
        )
        if not row or row["status"] == "hidden":
            raise NotFoundError("ไม่พบโพสต์นี้")

    async def assert_can_delete(self, conn, user_id, owner_id, image_row):
        if image_row["uploaded_by"] == user_id:
            return
        if await issue_service._has_council_authority(conn, user_id):
            return
        raise ForbiddenError("ลบได้เฉพาะรูปที่คุณอัปโหลดเองหรือสภานักเรียน")


# ============================================================
# PIRI Board comment — รูปในคอมเมนต์
# ============================================================
_COMMENT_LIVE_SQL = """
    SELECT c.id, c.user_id, c.board_id, c.is_hidden_by_admin,
           b.status AS board_status
    FROM piri_board_comments c
    JOIN piri_boards b ON b.id = c.board_id AND b.deleted_at IS NULL
    WHERE c.id = $1 AND c.deleted_at IS NULL
"""


class BoardCommentPolicy(MediaPolicy):
    async def lock_owner(self, conn, owner_id):
        row = await conn.fetchrow(_COMMENT_LIVE_SQL + " FOR UPDATE OF c", owner_id)
        if not row or row["is_hidden_by_admin"] or row["board_status"] == "hidden":
            raise NotFoundError("ไม่พบคอมเมนต์นี้")
        return row

    async def assert_can_upload(self, conn, user_id, owner_id, owner_row):
        if owner_row["user_id"] == user_id:
            return
        if await issue_service._has_council_authority(conn, user_id):
            return
        raise ForbiddenError("แนบรูปได้เฉพาะเจ้าของคอมเมนต์หรือสภานักเรียน")

    async def assert_can_view(self, conn, user_id, owner_id):
        row = await conn.fetchrow(_COMMENT_LIVE_SQL, owner_id)
        if not row or row["is_hidden_by_admin"] or row["board_status"] == "hidden":
            raise NotFoundError("ไม่พบคอมเมนต์นี้")

    async def assert_can_delete(self, conn, user_id, owner_id, image_row):
        if image_row["uploaded_by"] == user_id:
            return
        row = await conn.fetchrow(_COMMENT_LIVE_SQL, owner_id)
        if row and row["user_id"] == user_id:
            return
        if await issue_service._has_council_authority(conn, user_id):
            return
        raise ForbiddenError("ลบได้เฉพาะรูปที่คุณอัปโหลดเองหรือสภานักเรียน")


# ============================================================
# ประกาศ
# ============================================================
class AnnouncementPolicy(MediaPolicy):
    async def lock_owner(self, conn, owner_id):
        row = await conn.fetchrow(
            "SELECT id FROM announcements WHERE id = $1 AND deleted_at IS NULL FOR UPDATE",
            owner_id,
        )
        if not row:
            raise NotFoundError("ไม่พบประกาศนี้")
        return row

    async def assert_can_upload(self, conn, user_id, owner_id, owner_row):
        await require_permission_anywhere(conn, user_id, "MANAGE_ANNOUNCEMENTS")

    async def assert_can_view(self, conn, user_id, owner_id):
        # ประกาศที่ "ปลดระวาง" ยังดูรูปได้จน URL หมดอายุ (ไฟล์ยังเป็นของประกาศที่ยังไม่ถูกลบ)
        exists = await conn.fetchval(
            "SELECT 1 FROM announcements WHERE id = $1 AND deleted_at IS NULL",
            owner_id,
        )
        if not exists:
            raise NotFoundError("ไม่พบประกาศนี้")

    async def assert_can_delete(self, conn, user_id, owner_id, image_row):
        await require_permission_anywhere(conn, user_id, "MANAGE_ANNOUNCEMENTS")


# ============================================================
# กิจกรรม
# ============================================================
class EventPolicy(MediaPolicy):
    async def lock_owner(self, conn, owner_id):
        row = await conn.fetchrow(
            "SELECT id, status FROM events WHERE id = $1 AND deleted_at IS NULL FOR UPDATE",
            owner_id,
        )
        if not row:
            raise NotFoundError("ไม่พบกิจกรรมนี้")
        return row

    async def assert_can_upload(self, conn, user_id, owner_id, owner_row):
        await require_permission_anywhere(conn, user_id, "MANAGE_EVENTS")

    async def assert_can_view(self, conn, user_id, owner_id):
        row = await conn.fetchrow(
            "SELECT status FROM events WHERE id = $1 AND deleted_at IS NULL", owner_id
        )
        if not row:
            raise NotFoundError("ไม่พบกิจกรรมนี้")
        if row["status"] != "published":
            # ยังไม่เผยแพร่ ⇒ เห็นได้เฉพาะผู้จัดการกิจกรรม (คนอื่น 404 — ไม่เปิดเผยว่ามีอยู่)
            try:
                await require_permission_anywhere(conn, user_id, "MANAGE_EVENTS")
            except ForbiddenError:
                raise NotFoundError("ไม่พบกิจกรรมนี้") from None

    async def assert_can_delete(self, conn, user_id, owner_id, image_row):
        await require_permission_anywhere(conn, user_id, "MANAGE_EVENTS")


# ============================================================
# โปรไฟล์ (avatar)
# ============================================================
class UserAvatarPolicy(MediaPolicy):
    async def lock_owner(self, conn, owner_id):
        row = await conn.fetchrow(
            "SELECT id FROM users WHERE id = $1 AND deleted_at IS NULL FOR UPDATE", owner_id
        )
        if not row:
            raise NotFoundError("ไม่พบผู้ใช้นี้")
        return row

    async def assert_can_upload(self, conn, user_id, owner_id, owner_row):
        if owner_id == user_id:
            return
        if settings.SUPER_ADMIN_ID and int(user_id) == int(settings.SUPER_ADMIN_ID):
            return
        raise ForbiddenError("อัปรูปโปรไฟล์ได้เฉพาะของตัวเอง")

    async def assert_can_view(self, conn, user_id, owner_id):
        exists = await conn.fetchval(
            "SELECT 1 FROM users WHERE id = $1 AND deleted_at IS NULL", owner_id
        )
        if not exists:
            raise NotFoundError("ไม่พบผู้ใช้นี้")

    async def assert_can_delete(self, conn, user_id, owner_id, image_row):
        if owner_id == user_id:
            return
        if await issue_service.is_admin(conn, user_id):
            return
        raise ForbiddenError("ลบรูปโปรไฟล์ได้เฉพาะเจ้าของหรือแอดมิน")


# ============================================================
# Registry
# ============================================================
# ⚠️ สร้างตอน import จาก settings — ถ้าวันหน้าต้องเปิดให้หลายรูปต่อเจ้าของ
#    (เช่น album) แก้ MEDIA_MAX_* แล้วรีสตาร์ท; เทสต์ที่ต้องการค่าเฉพาะให้ patch ตัว registry
_POLICIES: dict[str, MediaPolicy] = {
    p.owner_type: p
    for p in (
        BoardPolicy(
            owner_type="board", kind="cover",
            max_per_owner=int(settings.MEDIA_MAX_COVER_IMAGES),
        ),
        BoardCommentPolicy(
            owner_type="board_comment", kind="attachment",
            max_per_owner=int(settings.MEDIA_MAX_ATTACHMENT_IMAGES),
        ),
        AnnouncementPolicy(
            owner_type="announcement", kind="attachment",
            max_per_owner=int(settings.MEDIA_MAX_ATTACHMENT_IMAGES),
        ),
        EventPolicy(
            owner_type="event", kind="cover",
            max_per_owner=int(settings.MEDIA_MAX_COVER_IMAGES),
        ),
        UserAvatarPolicy(
            owner_type="user", kind="avatar",
            max_per_owner=int(settings.MEDIA_MAX_AVATAR_IMAGES),
        ),
    )
}


def get_policy(owner_type: str) -> MediaPolicy:
    """คืน policy ของเจ้าของชนิดนี้ — **raise ValidationError ถ้าไม่รู้จัก**

    ⚠️ ห้ามเปลี่ยนเป็น `_POLICIES.get(...)` คืน default — นั่นคือการเปิดช่องให้
       owner_type ใหม่ (ที่ยังไม่มีใครกำหนดสิทธิ์) แนบรูปได้โดยไม่มีด่าน
    """
    try:
        return _POLICIES[owner_type]
    except KeyError:
        raise ValidationError(f"ไม่รู้จักชนิดเจ้าของรูป: {owner_type}") from None
