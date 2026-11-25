"""
E2E Seed — สร้าง users/rooms ที่ deterministic สำหรับ Playwright flow
=====================================================================
- ต้องรันหลังจาก backend เริ่ม (init_db สร้าง schema + migrations เรียบร้อย)
- ใช้ JWT_SECRET/env เดียวกับ backend ที่รันอยู่ (token ใช้ login ผ่าน UI ได้)
- เขียน credentials + tokens → /tmp/e2e_credentials.json (Playwright spec อ่าน)
- รันซ้ำได้ (register_user idempotent — หา user เดิมเจอ)
"""
import asyncio
import json
import os
import sys

import asyncpg

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from services import auth_service  # noqa: E402

DB_URL = os.environ.get("E2E_DATABASE_URL", "postgresql://test_admin:test_password@localhost:5435/e2e_piri_db")
OUT = os.environ.get("E2E_CREDS_OUT", "/tmp/e2e_credentials.json")
PASSWORD = "E2Epass123!"
ROOM_CODE = "ม.5/1"
OUTSIDER_ROOM = "ม.5/2"

# username ต้องสั้น ≤10 ตัว (student_id VARCHAR(10))
# (room, seat, role, is_admin)
USERS = [
    ("e2estu", ROOM_CODE, 1, "student", False),            # ผู้แจ้ง
    ("e2ehead", ROOM_CODE, 2, "class_president", False),   # ผู้รับ (หัวหน้าห้อง)
    ("e2ecou", ROOM_CODE, 3, "council_member", False),     # สมาชิกสภา — ผู้เปิดดูอีกคน
    ("e2eadm", ROOM_CODE, 4, "council_president", True),   # ประธานสภา (admin)
    ("e2eout", OUTSIDER_ROOM, 1, "student", False),        # นักเรียนห้องอื่น — ต้องมองไม่เห็น
]


async def _ensure_room(pool, room_code: str) -> int:
    async with pool.acquire() as conn:
        room_id = await conn.fetchval(
            "SELECT id FROM rooms WHERE room_code = $1 AND deleted_at IS NULL", room_code
        )
        if not room_id:
            room_id = await conn.fetchval(
                "INSERT INTO rooms (room_code, room_name, level) VALUES ($1, $2, 'ม.5') RETURNING id",
                room_code, room_code
            )
        print(f"✅ room_id={room_id} ({room_code})")
        return room_id


async def main() -> None:
    pool = await asyncpg.create_pool(DB_URL)
    try:
        # 1) rooms (ถ้ายังไม่มี)
        await _ensure_room(pool, ROOM_CODE)
        await _ensure_room(pool, OUTSIDER_ROOM)

        # 2) users
        creds = {}
        for username, room_code, seat, role, is_admin in USERS:
            uid = await auth_service.register_user(
                pool, username, PASSWORD, f"E2E {username}", username, room_code, seat, role
            )
            async with pool.acquire() as conn:
                if is_admin:
                    await conn.execute("UPDATE students SET is_admin = TRUE WHERE user_id = $1", uid)
                # กัน router guard บังคับเปลี่ยนรหัส (seed users ต้อง login ผ่านได้ทันที)
                await conn.execute("UPDATE users SET must_change_password = FALSE WHERE id = $1", uid)
            creds[username] = {
                "username": username,
                "password": PASSWORD,
                "user_id": uid,
                "token": auth_service.create_access_token(uid),
            }
            print(f"✅ {username} → user_id={uid} role={role} is_admin={is_admin}")

        with open(OUT, "w", encoding="utf-8") as f:
            json.dump(creds, f, ensure_ascii=False, indent=2)
        print(f"✅ credentials saved → {OUT}")
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
