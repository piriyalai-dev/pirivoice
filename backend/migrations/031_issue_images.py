"""031 — รูปภาพของเรื่อง (issue_images) + ประวัติการเปิดดู (issue_image_views)

**ทำไมต้องมีตาราง ไม่ใช้ `issues.image_url` เดิม:**
  - `image_url` เก็บได้ URL เดียว ⇒ ใส่ได้ 3 รูปตามที่ล็อกไว้ไม่ได้
  - ไม่มีที่เก็บ sha256/ขนาด/ชนิด (report/progress) ที่ต้องใช้ตรวจไฟล์และแสดง read receipt
  - รูปต้องผูก "ใครอัป" เพื่อให้ rate limit และปุ่มลบทำงานได้

**`issues.image_url` ไม่ถูกลบ** — คงไว้เป็น legacy fallback ของรูปเก่า (ถ้ามีในอนาคต)

**`issue_image_views` = 1 แถวต่อ (image_id, user_id)** ไม่ใช่ log ต่อการเปิด
  - `first_viewed_at` / `last_viewed_at` / `view_count` ให้ทั้ง "ใครเปิดเมื่อไร" และ "บ่อยแค่ไหน"
  - dedupe 10 นาทีทำที่ service (ไม่ใช่ที่ DB) เพราะเป็นนโยบายธุรกิจ ไม่ใช่ constraint
  - ⚠️ **ไม่เก็บ flag "ผู้รับผิดชอบเปิดแล้ว"** — คำนวณจาก `issues.current_assignee_id` ตอนอ่าน
    ⇒ ถ้าเปลี่ยนผู้รับ สถานะสะท้อนคนใหม่ทันที (flag ที่แช่ไว้จะโกหก)

**index:** mirror ไว้ใน `core/init_db.py` (บล็อก index ท้ายไฟล์) — ห้ามแก้ที่เดียว
  - `issue_images(issue_id, created_at) WHERE deleted_at IS NULL` — หน้ารายละเอียดเรื่อง
  - `issue_images(uploaded_by, created_at DESC)` — นับ rate limit รายชั่วโมง
  - `storage_path` UNIQUE — กันแถวชี้ไฟล์เดียวกันซ้ำ (และเป็นกุญแจของ purge)
  - views: ตาม image (แสดง receipt) และตาม user
"""
VERSION = "031_issue_images"
DESCRIPTION = "issue_images + issue_image_views สำหรับแนบรูปและ read receipt"

import asyncpg


async def upgrade(conn: asyncpg.Connection) -> None:
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS issue_images (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            issue_id INTEGER NOT NULL REFERENCES issues(id) ON DELETE CASCADE,
            uploaded_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
            -- บทบาท ณ ตอนอัป (snapshot) — ผู้ใช้ย้ายห้อง/จบปีแล้วยังรู้ว่าเคยเป็นใคร
            uploader_role TEXT,
            -- 'report' = ผู้แจ้งแนบตอนแจ้ง · 'progress' = ผู้รับงานแนบตอนอัปเดต
            kind VARCHAR(10) NOT NULL,
            storage_path TEXT NOT NULL,
            thumb_path TEXT,
            -- sha256 ของไฟล์ที่ **หลังประมวลผลแล้ว** (WebP) — ใช้ตรวจความถูกต้องตอน restore
            sha256 VARCHAR(64) NOT NULL,
            thumb_sha256 VARCHAR(64),
            mime VARCHAR(40) NOT NULL DEFAULT 'image/webp',
            bytes BIGINT NOT NULL,
            width INTEGER NOT NULL,
            height INTEGER NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            deleted_at TIMESTAMPTZ,
            CONSTRAINT chk_issue_images_kind CHECK (kind IN ('report', 'progress')),
            CONSTRAINT chk_issue_images_bytes CHECK (bytes > 0),
            CONSTRAINT chk_issue_images_dims CHECK (width > 0 AND height > 0)
        )
    """)
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS issue_image_views (
            image_id UUID NOT NULL REFERENCES issue_images(id) ON DELETE CASCADE,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            -- บทบาท ณ ตอนเปิดดู — ใช้แยก "ผู้รับผิดชอบ" ออกจาก "เพื่อนร่วมห้อง" ในรายงาน
            viewer_role TEXT,
            first_viewed_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            last_viewed_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            view_count INTEGER NOT NULL DEFAULT 1,
            PRIMARY KEY (image_id, user_id),
            CONSTRAINT chk_issue_image_views_count CHECK (view_count > 0)
        )
    """)
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_issue_images_issue "
        "ON issue_images(issue_id, created_at) WHERE deleted_at IS NULL"
    )
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_issue_images_uploader "
        "ON issue_images(uploaded_by, created_at DESC) WHERE deleted_at IS NULL"
    )
    await conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_issue_images_storage_path "
        "ON issue_images(storage_path)"
    )
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_issue_image_views_image "
        "ON issue_image_views(image_id, last_viewed_at DESC)"
    )
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_issue_image_views_user "
        "ON issue_image_views(user_id, last_viewed_at DESC)"
    )
