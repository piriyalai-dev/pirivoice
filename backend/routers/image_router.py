"""🖼️ เสิร์ฟไฟล์รูปด้วย signed URL — **ไม่มี Bearer token โดยเจตนา**

`<img src>` ของเบราว์เซอร์ส่ง Authorization header ไม่ได้ ⇒ endpoint นี้ยืนยันตัวตนด้วย
ลายเซ็นใน URL แทน (แล้วตรวจสิทธิ์ซ้ำใน service) — ดู `core/media_signing.py`

⚠️ **ห้ามใส่ endpoint นี้หลัง `get_current_user`** — ถ้าใส่ `<img>` จะโหลดไม่ขึ้นเลย
   และอย่าเพิ่มการอ่าน user จาก cookie/session แทนลายเซ็น เพราะจะทำให้ URL ที่แชร์
   ต่อกันใช้ได้ในนามของคนที่ถือ cookie
"""
from typing import Optional

import asyncpg
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from core.dependencies import get_db_pool
from core.exceptions import ForbiddenError, NotFoundError
from core.media import MediaStorageError
from services import image_service

router = APIRouter(tags=["Issue Images"])

# 🔒 header ชุดนี้ต้องมากับทุก response ของรูป
#   - private: ห้าม Cloudflare/CDN แคช (รูปส่วนตัว — cache กลาง = รูปหลุด)
#   - no-transform: ห้าม proxy บีบอัด/แปลงรูปซ้ำ
#   - no-referrer: URL ที่มีลายเซ็นต้องไม่หลุดไปใน Referer ของหน้าเว็บอื่น
#   - nosniff: เบราว์เซอร์ห้ามเดา content-type เอง
#   - noindex: ห้าม search engine เก็บรูป
_IMAGE_HEADERS = {
    "Cache-Control": "private, max-age=60, no-transform",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "X-Robots-Tag": "noindex",
    "Content-Disposition": "inline",
}


@router.get("/images/{image_id}")
async def serve_image(
    image_id: str,
    variant: Optional[str] = None,
    viewer: Optional[str] = None,
    exp: Optional[str] = None,
    sig: Optional[str] = None,
    pool: asyncpg.Pool = Depends(get_db_pool),
):
    """stream ไฟล์รูป (full/thumb) — ต้องมี signed URL ที่ยังไม่หมดอายุและผู้ถือต้องเห็นเรื่องได้

    ⚠️ query params เป็น `str` ไม่ใช่ `int` โดยเจตนา — ค่าที่ผิดรูปแบบต้องตอบ **403**
       (เหมือนลายเซ็นผิด) ไม่ใช่ 422 ที่บอกใบ้ว่าฟิลด์ไหนผิด
    """
    try:
        row, path = await image_service.resolve_image_for_serving(
            pool, image_id, variant, viewer, exp, sig
        )
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except MediaStorageError:
        raise HTTPException(status_code=500, detail="ระบบจัดเก็บรูปขัดข้อง")

    return FileResponse(
        path,
        media_type=row["mime"] or "image/webp",
        headers=_IMAGE_HEADERS,
    )
