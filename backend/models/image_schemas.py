"""Response schemas ของรูปภาพเรื่อง (issue images)

⚠️ `url` / `thumb_url` เป็น **path แบบ relative** (`/api/images/...`) ไม่ใช่ absolute
   — backend ไม่รู้ว่าเบราว์เซอร์เข้าผ่านโดเมนไหน (Cloudflare/staging/localhost)
   ⇒ frontend เติม `VITE_API_BASE_URL` เอง (ดู `frontend/src/services/api.ts`)
"""
from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel


class IssueImageReceiptOut(BaseModel):
    """หลักฐานการเปิดดู — คืนเฉพาะผู้แจ้ง/แอดมิน"""

    # ⚠️ คำนวณจาก `issues.current_assignee_id` ตอนอ่าน **ไม่ใช่ flag ที่แช่ไว้**
    #    ⇒ เปลี่ยนผู้รับแล้วสถานะสะท้อนคนใหม่ทันที
    current_assignee_viewed: bool = False
    current_assignee_viewed_at: Optional[datetime] = None
    # จำนวนผู้เปิดดูที่นับเป็น "คนอื่น" (ไม่ใช่ผู้แจ้ง/ผู้รับปัจจุบัน) — เช่นเพื่อนร่วมห้อง
    other_viewer_count: int = 0
    last_viewed_at: Optional[datetime] = None


class IssueImageOut(BaseModel):
    id: UUID
    issue_id: int
    kind: str  # report / progress
    url: str
    thumb_url: str
    width: int
    height: int
    bytes: int
    uploaded_by: Optional[int] = None
    created_at: datetime
    receipt: Optional[IssueImageReceiptOut] = None


class IssueImageLimitsOut(BaseModel):
    """เพดานที่ frontend ใช้แสดง "แนบได้อีกกี่รูป" — ค่ามาจาก server ไม่ hardcode ฝั่ง UI"""

    max_report: int
    max_progress: int
    max_per_request: int
    size_limit_mb: int


class IssueImageListOut(BaseModel):
    items: List[IssueImageOut]
    limits: IssueImageLimitsOut
