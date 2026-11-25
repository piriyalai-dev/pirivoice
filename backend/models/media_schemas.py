"""Response schemas ของรูปภาพกลาง (`media_images` — บอร์ด/ประกาศ/กิจกรรม/โปรไฟล์)

⚠️ `url` / `thumb_url` เป็น **path แบบ relative** (`/api/media/file/...`) ไม่ใช่ absolute
   — backend ไม่รู้ว่าเบราว์เซอร์เข้าผ่านโดเมนไหน ⇒ frontend เติม base เอง
⚠️ **ไม่มี `uploaded_by` โดยเจตนา** — เนื้อหาบอร์ด/คอมเมนต์เป็น anonymous ได้
   การเปิดเผยผู้อัป = การเปิดเผยผู้เขียน
"""
from datetime import datetime
from typing import List

from pydantic import BaseModel


class MediaImageOut(BaseModel):
    id: str
    owner_type: str
    owner_id: int
    kind: str  # cover / attachment / avatar
    url: str
    thumb_url: str
    width: int
    height: int
    bytes: int
    created_at: datetime


class MediaLimitsOut(BaseModel):
    """เพดานที่ frontend ใช้ตัดสินใจก่อนอัป — ค่ามาจาก server ไม่ hardcode ฝั่ง UI"""

    max_per_owner: int
    max_per_request: int
    size_limit_mb: int


class MediaImageListOut(BaseModel):
    items: List[MediaImageOut]
    limits: MediaLimitsOut
