"""🖼️ รูปภาพกลาง (media_images) — อัป/ดู/ลบ (Bearer) + เสิร์ฟไฟล์ (signed URL)

⚠️ **ลำดับการลงทะเบียน route สำคัญ** — `/media/file/{image_id}` มีรูปร่าง path
   เดียวกับ `/media/{owner_type}/{owner_id}` ทุกประการ (2 segment) ⇒ ต้องประกาศ
   route เสิร์ฟไฟล์ **ก่อน** ไม่งั้น Starlette จะ match เป็น owner_type="file"
   แล้วพังที่การแปลง owner_id เป็น int

⚠️ endpoint เสิร์ฟไฟล์ **ห้ามอยู่หลัง `get_current_user`** — `<img src>` ส่ง header ไม่ได้
   (เหมือน `image_router` ของเรื่อง) การยืนยันตัวตน = ลายเซ็น + การตรวจสิทธิ์ซ้ำใน service
"""
from typing import Optional

import asyncpg
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from core.dependencies import get_current_user, get_db_pool
from core.exceptions import ForbiddenError, NotFoundError
from core.media import MediaStorageError
from models.media_schemas import MediaImageListOut
from routers._media_http import ensure_user, err, read_upload_capped
from routers.image_router import _IMAGE_HEADERS
from services import media_service

router = APIRouter(prefix="/media", tags=["Media"])


# ------------------------------------------------------------
# 👁️ เสิร์ฟไฟล์ — ไม่มี Bearer (ต้องประกาศก่อน route ที่มี 2 segment)
# ------------------------------------------------------------
@router.get("/file/{image_id}")
async def serve_media(
    image_id: str,
    variant: Optional[str] = None,
    viewer: Optional[str] = None,
    exp: Optional[str] = None,
    sig: Optional[str] = None,
    pool: asyncpg.Pool = Depends(get_db_pool),
):
    """stream ไฟล์รูป (full/thumb) — signed URL + ผู้ถือต้องยังเห็นเนื้อหาเจ้าของได้

    query params เป็น `str` โดยเจตนา — ค่าผิดรูปแบบต้องตอบ 403 (เหมือนลายเซ็นผิด)
    ไม่ใช่ 422 ที่บอกใบ้ว่าฟิลด์ไหนผิด
    """
    try:
        row, path = await media_service.resolve_media_for_serving(
            pool, image_id, variant, viewer, exp, sig
        )
    except ForbiddenError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except MediaStorageError as e:
        raise HTTPException(status_code=500, detail="ระบบจัดเก็บรูปขัดข้อง") from e

    return FileResponse(
        path,
        media_type=row["mime"] or "image/webp",
        headers=_IMAGE_HEADERS,
    )


# ------------------------------------------------------------
# 📤 อัปโหลด
# ------------------------------------------------------------
@router.post("/{owner_type}/{owner_id}", response_model=MediaImageListOut)
async def upload_media(
    owner_type: str,
    owner_id: int,
    files: list[UploadFile] = File(...),
    kind: Optional[str] = Form(None),
    user_ctx: dict = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(get_db_pool),
):
    uid = ensure_user(user_ctx)
    try:
        payload = [(f.filename or "image", await read_upload_capped(f)) for f in files]
        return await media_service.upload_media(
            pool, uid, owner_type, owner_id, payload, requested_kind=kind
        )
    except Exception as e:  # noqa: BLE001 — แปลงเป็น HTTP ที่จุดเดียว
        raise err(e) from e


# ------------------------------------------------------------
# 📋 รายการรูปของเจ้าของ
# ------------------------------------------------------------
@router.get("/{owner_type}/{owner_id}", response_model=MediaImageListOut)
async def list_media(
    owner_type: str,
    owner_id: int,
    user_ctx: dict = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(get_db_pool),
):
    uid = ensure_user(user_ctx)
    try:
        return await media_service.list_media(pool, uid, owner_type, owner_id)
    except Exception as e:  # noqa: BLE001
        raise err(e) from e


# ------------------------------------------------------------
# 🗑️ ลบ (soft delete)
# ------------------------------------------------------------
@router.delete("/{owner_type}/{owner_id}/{image_id}")
async def delete_media(
    owner_type: str,
    owner_id: int,
    image_id: str,
    user_ctx: dict = Depends(get_current_user),
    pool: asyncpg.Pool = Depends(get_db_pool),
):
    uid = ensure_user(user_ctx)
    try:
        return await media_service.delete_media(pool, uid, owner_type, owner_id, image_id)
    except Exception as e:  # noqa: BLE001
        raise err(e) from e
