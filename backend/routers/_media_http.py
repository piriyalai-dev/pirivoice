"""ตัวช่วย HTTP ที่ router รูปภาพใช้ร่วมกัน

⚠️ ยัง **ไม่ย้าย** `issue_router` มาใช้ไฟล์นี้โดยเจตนา — ฟีเจอร์รูปของเรื่องกำลังใช้งาน
   อยู่ การแก้ไฟล์นั้นเพื่อ DRY ไม่คุ้มความเสี่ยง ⇒ media_router ใช้ของใหม่นี้
   ของเดิมใน issue_router ยังทำงานเหมือนเดิม (พฤติกรรม 413/401/400 ต้องตรงกัน —
   ถ้ามีวันที่แก้ ให้แก้ทั้งสองที่พร้อมกัน หรือย้ายมาใช้ตัวนี้ทั้งคู่พร้อมเทสต์)
"""
from fastapi import HTTPException, UploadFile

from core.config import settings
from core.exceptions import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    PayloadTooLargeError,
    RateLimitError,
    ValidationError,
)


def ensure_user(user_ctx: dict) -> int:
    uid = user_ctx.get("user_id")
    if not uid:
        raise HTTPException(status_code=401, detail="ต้องเข้าสู่ระบบ")
    return int(uid)


def err(e: Exception) -> HTTPException:
    """แปลง domain exception → HTTPException (ชุดเดียวกับ issue_router._err)"""
    if isinstance(e, NotFoundError):
        return HTTPException(status_code=404, detail=str(e))
    if isinstance(e, ForbiddenError):
        return HTTPException(status_code=403, detail=str(e))
    if isinstance(e, ValidationError):
        return HTTPException(status_code=400, detail=str(e))
    if isinstance(e, ConflictError):
        return HTTPException(status_code=409, detail=str(e))
    if isinstance(e, PayloadTooLargeError):
        return HTTPException(status_code=413, detail=str(e))
    if isinstance(e, RateLimitError):
        return HTTPException(status_code=429, detail=str(e))
    return HTTPException(status_code=500, detail=f"เกิดข้อผิดพลาด: {e}")


async def read_upload_capped(upload: UploadFile) -> bytes:
    """อ่านไฟล์อัปโหลดแบบมีเพดาน — อ่านทีละ 1MB และตัดที่เพดาน (ไม่ buffer ทั้งไฟล์)"""
    limit = int(settings.MEDIA_IMAGE_SIZE_LIMIT_MB) * 1024 * 1024
    buf = bytearray()
    while True:
        chunk = await upload.read(1024 * 1024)
        if not chunk:
            break
        if len(buf) + len(chunk) > limit:
            raise PayloadTooLargeError(
                f"รูปใหญ่เกิน {settings.MEDIA_IMAGE_SIZE_LIMIT_MB} MB"
            )
        buf.extend(chunk)
    return bytes(buf)
