"""032 — รูปภาพกลาง (`media_images`) สำหรับบอร์ด/ประกาศ/กิจกรรม/โปรไฟล์

**ทำไมตารางใหม่ ไม่ขยาย `issue_images`:**
  - `issue_images.issue_id` เป็น FK ไป `issues` (ON DELETE CASCADE) — รูปของบอร์ด/ประกาศ
    ไม่มี `issues` รองรับ และไม่ควรผูกกับตารางนั้น
  - `issue_images` กำลังใช้งานจริง — แก้ไขเพื่อรับเจ้าของ 5 ชนิด = เสี่ยงฟีเจอร์ที่ใช้อยู่

**ทำไม polymorphic `(owner_type, owner_id)` ไม่ใช่ FK 5 คอลัมน์:**
  - เจ้าของ 5 ตาราง (`piri_boards`, `piri_board_comments`, `announcements`, `events`, `users`)
    เป็น INTEGER ทั้งหมด ⇒ คอลัมน์เดียวรับได้
  - FK ไปเจ้าของทำไม่ได้ (polymorphic) ⇒ **ความปลอดภัยตอนเจ้าของถูกลบ/ซ่อนมาจาก policy
    ที่ตรวจทุกครั้งที่เสิร์ฟ** (`services/media_policies.py`) ไม่ใช่ FK
  - `owner_type` ถูกบังคับด้วย CHECK ให้ตรงกับ registry ใน Python (fail-closed)

**partial unique index `uq_media_single_cover`:**
  ปก/avatar (= `cover`/`avatar`) มีได้ **ชิ้นเดียวที่ยังไม่ถูกลบ** ต่อเจ้าของ —
  การ "เปลี่ยนปก" ทำ soft-delete แถวเดิมก่อน INSERT ใหม่ใน transaction เดียว
  ⇒ index ไม่เคยเห็นสองแถวที่ยังไม่ถูกลบ (attachment คุมเพดานด้วย service)

**index:** mirror ไว้ใน `core/init_db.py` (บล็อก index ท้ายไฟล์) — ห้ามแก้ที่เดียว

**rollback (operator):** `DROP TABLE IF EXISTS media_images;` ปลอดภัย (ไม่มีตารางใดอ้างถึง)
  แต่ไฟล์ใต้ `media/` ยังอยู่ — รัน `scripts/purge_media.py --apply` หลัง drop
  หรือปล่อยให้ `verify_media.py` รายงานเป็น orphan
"""
VERSION = "032_media_images"
DESCRIPTION = "media_images — รูปภาพกลางของบอร์ด/ประกาศ/กิจกรรม/โปรไฟล์"

import asyncpg


async def upgrade(conn: asyncpg.Connection) -> None:
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS media_images (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            -- เจ้าของแบบ polymorphic — ชนิดที่รู้จักอยู่ใน CHECK (ตรงกับ media_policies)
            owner_type VARCHAR(24) NOT NULL,
            owner_id INTEGER NOT NULL,
            -- 'cover' (บอร์ด/กิจกรรม) · 'attachment' (คอมเมนต์/ประกาศ) · 'avatar' (โปรไฟล์)
            kind VARCHAR(16) NOT NULL,
            uploaded_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
            -- บทบาท ณ ตอนอัป (snapshot) — ผู้ใช้ย้ายห้อง/จบปีแล้วยังรู้ว่าเคยเป็นใคร
            uploader_role TEXT,
            storage_path TEXT NOT NULL,
            thumb_path TEXT,
            -- sha256 ของไฟล์ **หลังประมวลผลแล้ว** (WebP) — ใช้ตรวจความถูกต้องตอน restore
            sha256 VARCHAR(64) NOT NULL,
            thumb_sha256 VARCHAR(64),
            mime VARCHAR(40) NOT NULL DEFAULT 'image/webp',
            bytes BIGINT NOT NULL,
            width INTEGER NOT NULL,
            height INTEGER NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            deleted_at TIMESTAMPTZ,
            CONSTRAINT chk_media_owner_type CHECK (
                owner_type IN ('board','board_comment','announcement','event','user')
            ),
            CONSTRAINT chk_media_kind CHECK (kind IN ('cover','attachment','avatar')),
            CONSTRAINT chk_media_bytes CHECK (bytes > 0),
            CONSTRAINT chk_media_dims CHECK (width > 0 AND height > 0)
        )
    """)
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_media_owner "
        "ON media_images(owner_type, owner_id, created_at) WHERE deleted_at IS NULL"
    )
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_media_uploader "
        "ON media_images(uploaded_by, created_at DESC) WHERE deleted_at IS NULL"
    )
    await conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_media_storage_path "
        "ON media_images(storage_path)"
    )
    await conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_media_single_cover "
        "ON media_images(owner_type, owner_id) "
        "WHERE deleted_at IS NULL AND kind IN ('cover','avatar')"
    )
