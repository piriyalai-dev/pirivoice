"""✍️ Signed URL ของรูปภาพเรื่อง — HMAC-SHA256 บน `SECRET_KEY`

⭐ **ทำไมต้อง signed URL ไม่ใช่ Authorization header**

   `<img src="...">` ของเบราว์เซอร์ **ส่ง header ไม่ได้** (ไม่ใช่ fetch/XHR) ⇒ ถ้า endpoint
   รูปต้องใช้ Bearer token ภาพจะโหลดไม่ขึ้นเลยไม่ว่าจะทำ frontend อย่างไร
   ทางเลือกมีแค่ (ก) ให้ frontend โหลดเป็น blob แล้ว `URL.createObjectURL` — เปลืองหน่วยความจำ
   และทำให้เบราว์เซอร์ cache ไม่ได้ หรือ (ข) ฝังลายเซ็นใน URL — เลือก (ข)

🔒 **ลายเซ็นผูกกับ viewer** — ไม่ใช่แค่ image_id ⇒ URL ที่หลุดไปให้คนอื่นใช้แทนไม่ได้
   (คนอื่นเปิด URL นั้นจะได้ viewer_id ของเจ้าของ URL ซึ่ง **ผ่านการตรวจสิทธิ์ซ้ำตอน GET**
   อยู่ดี ⇒ ถ้าเขาไม่มีสิทธิ์เห็นเรื่องก็ยัง 403)

⏱️ **อายุ 15 นาที + ปัด exp เป็นรอบ 5 นาที**
   - URL เดิมที่สร้างในรอบเดียวกันได้ exp เท่ากัน ⇒ React re-render / cache ของเบราว์เซอร์
     ใช้ URL ซ้ำได้ ไม่ทำให้ภาพกระพริบเปลี่ยน URL ทุกครั้ง
   - อายุจริงจึงอยู่ที่ **10–15 นาที** (ไม่สั้นกว่านั้น) — ผู้ใช้เปิดหน้าเดิมค้างไว้นาน
     จะเห็นภาพหายเมื่อหมดอายุ ซึ่ง frontend แก้ด้วยการ refetch list ตอน `onerror`

⚠️ ลายเซ็นใช้ `SECRET_KEY` ร่วมกับบัตรเช็คอิน (ดู `core/check_in_token.py`) แต่ **แยกโดเมน**
   ด้วย prefix `issue-image:v1:` — ลายเซ็นของโดเมนหนึ่งใช้ข้ามอีกโดเมนไม่ได้
   (และถ้าจะหมุน `SECRET_KEY` ต้องรู้ว่า **URL รูปที่แชร์อยู่ทั้งหมดจะหมดอายุทันที** —
   ไม่เสียหาย เพราะ URL อายุสั้นและ frontend สร้างใหม่ได้เอง)
"""
import base64
import hashlib
import hmac
import time
from typing import Optional, Tuple

from core.config import settings

# โดเมนลายเซ็น — ขึ้นต้นด้วยค่านี้ทุกครั้ง (กันใช้ลายเซ็นข้ามบริบท)
#
# ⭐ **scope** แยกโดเมน: `issue-image` = รูปของเรื่อง (path/โดเมนเดิม ห้ามเปลี่ยน)
#    `media` = รูปของส่วนอื่น (บอร์ด/ประกาศ/กิจกรรม/โปรไฟล์) ⇒ ลายเซ็นของโดเมนหนึ่ง
#    ใช้ข้ามอีกโดเมนไม่ได้ แม้ id จะบังเอิญตรงกัน
_SCOPE_CONFIG = {
    "issue-image": ("issue-image:v1", "/api/images"),
    "media": ("media:v1", "/api/media/file"),
}
DEFAULT_SCOPE = "issue-image"
_SIGNING_CONTEXT = _SCOPE_CONFIG[DEFAULT_SCOPE][0]


def _scope_config(scope: str) -> tuple[str, str]:
    try:
        return _SCOPE_CONFIG[scope]
    except KeyError:
        raise ValueError(f"signing scope ไม่ถูกต้อง: {scope}") from None

VALID_VARIANTS = ("full", "thumb")

# ตัด 16 ไบต์ (2^128) — พอสำหรับ URL อายุ 15 นาที และทำให้ query string สั้น
_SIG_BYTES = 16


def _sign(
    image_id: str, variant: str, viewer_id: int, exp: int, context: str = _SIGNING_CONTEXT
) -> str:
    message = f"{context}:{image_id}:{variant}:{viewer_id}:{exp}".encode()
    digest = hmac.new(settings.SECRET_KEY.encode(), message, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest[:_SIG_BYTES]).decode().rstrip("=")


def _round_exp(now: int) -> int:
    ttl = max(1, int(settings.MEDIA_URL_SIGNING_TTL_SECONDS))
    step = max(1, int(settings.MEDIA_URL_EXP_ROUND_SECONDS))
    return ((now + ttl) // step) * step


def make_signature(
    image_id: str,
    variant: str,
    viewer_id: int,
    now: Optional[int] = None,
    *,
    scope: str = DEFAULT_SCOPE,
) -> Tuple[int, str]:
    """คืน `(exp, sig)` — ใช้ `sign_url()` ในเส้นทางปกติ

    ⚠️ `variant` ต้องอยู่ใน `VALID_VARIANTS` — ถ้าเรียกด้วยค่าอื่นให้ raise ตั้งแต่ต้น
       (ไม่ปล่อยให้สร้าง URL ที่ verify ไม่ผ่านแล้วไปงงที่ปลายทาง)
    """
    if variant not in VALID_VARIANTS:
        raise ValueError(f"variant ไม่ถูกต้อง: {variant}")
    context, _path = _scope_config(scope)
    current = int(now if now is not None else time.time())
    exp = _round_exp(current)
    return exp, _sign(str(image_id), variant, int(viewer_id), exp, context)


def sign_url(
    image_id: str,
    variant: str,
    viewer_id: int,
    now: Optional[int] = None,
    *,
    scope: str = DEFAULT_SCOPE,
) -> str:
    """path แบบ relative (`/api/images/...` · scope `media` → `/api/media/file/...`)

    frontend เติม `VITE_API_BASE_URL` เอง

    ⚠️ **ไม่ประกอบ absolute URL ที่นี่** — backend ไม่รู้ว่าเบราว์เซอร์เข้าผ่านโดเมนไหน
       (Cloudflare/staging/localhost) และ `request.base_url` ที่ผิดจะทำให้ `<img>`
       ชี้ไปโดเมนที่ไม่มีอยู่ ⇒ ปล่อยให้ frontend ซึ่งรู้ base ของตัวเองเป็นคนเติม
    """
    _context, base_path = _scope_config(scope)
    exp, sig = make_signature(str(image_id), variant, viewer_id, now=now, scope=scope)
    return (
        f"{base_path}/{image_id}?variant={variant}"
        f"&viewer={int(viewer_id)}&exp={exp}&sig={sig}"
    )


def verify_signature(
    image_id: str,
    variant: Optional[str],
    viewer: Optional[str],
    exp: Optional[str],
    sig: Optional[str],
    now: Optional[int] = None,
    *,
    scope: str = DEFAULT_SCOPE,
) -> Optional[Tuple[int, str]]:
    """ตรวจลายเซ็น + เวลา — คืน `(viewer_id, variant)` หรือ `None` ถ้าไม่ผ่าน

    ⚠️ **คืน `None` รวมทุกกรณี** (พารามิเตอร์หาย · ตัวเลขผิด · ลายเซ็นผิด · หมดอายุ)
       ⇒ router ตอบ 403 ข้อความเดียว ไม่เป็น oracle บอกว่า "ผิดเพราะอะไร"
    ⚠️ เทียบด้วย `hmac.compare_digest` เท่านั้น (กัน timing attack)
    """
    if not isinstance(variant, str) or variant not in VALID_VARIANTS:
        return None
    if not isinstance(viewer, str) or not isinstance(exp, str) or not isinstance(sig, str):
        return None
    try:
        context, _path = _scope_config(scope)
    except ValueError:
        return None
    try:
        # int() เข้ม: "12x" / "" / "1.0" / " 1" (ไม่ strip) ไม่ผ่านทั้งหมด
        viewer_id = int(viewer)
        exp_ts = int(exp)
    except (TypeError, ValueError):
        return None
    if viewer_id < 1:
        return None
    current = int(now if now is not None else time.time())
    ttl = max(1, int(settings.MEDIA_URL_SIGNING_TTL_SECONDS))
    step = max(1, int(settings.MEDIA_URL_EXP_ROUND_SECONDS))
    # หมดอายุแล้ว หรือ exp ไกลเกินกว่าที่ระบบจะออกให้ได้ ⇒ ปฏิเสธ
    # (กรณีหลังไม่ใช่ช่องโหว่ — ลายเซ็นปลอมไม่ได้ — แต่กันความผิดพลาดของการคำนวณฝั่งออก URL)
    if exp_ts < current or exp_ts > current + ttl + step:
        return None
    expected = _sign(str(image_id), variant, viewer_id, exp_ts, context)
    if not hmac.compare_digest(sig, expected):
        return None
    return viewer_id, variant
