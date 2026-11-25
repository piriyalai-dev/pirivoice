"""🚪 GET /api/images/{id} — signed URL, สิทธิ์ซ้ำ, ไฟล์หาย, path traversal"""
import io
import random
import time
import uuid
from pathlib import Path

import pytest
import pytest_asyncio
from PIL import Image

from core.config import settings
from core.media_signing import make_signature, sign_url
from services import auth_service


def make_jpeg(width=800, height=600) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (width, height), (30, 120, 200)).save(buf, format="JPEG")
    return buf.getvalue()


def auth(user):
    return {"Authorization": f"Bearer {user['token']}"}


@pytest_asyncio.fixture
async def serving_world(db_pool, client):
    code = f"ม.4/{random.randint(100, 999)}"
    other = f"ม.6/{random.randint(100, 999)}"
    async with db_pool.acquire() as conn:
        room_id = await conn.fetchval(
            "INSERT INTO rooms (room_code, room_name, level) VALUES ($1,$2,'ม.4') RETURNING id", code, code
        )
        await conn.fetchval(
            "INSERT INTO rooms (room_code, room_name, level) VALUES ($1,$2,'ม.6') RETURNING id", other, other
        )

    async def reg(label, role, room_code):
        sid = f"T{random.randint(100000, 999999)}"
        uid = await auth_service.register_user(
            db_pool, sid, "1234", label, sid, room_code, 1, role
        )
        return {"user_id": uid, "token": auth_service.create_access_token(uid)}

    users = {
        "reporter": await reg("reporter", "student", code),
        "head": await reg("head", "class_president", code),
        "outsider": await reg("outsider", "student", other),
    }
    res = client.post(
        "/api/issues",
        json={
            "main_category": "report",
            "category": "complaint",
            "title": "เรื่องรูปสำหรับเสิร์ฟ",
            "description": "รายละเอียด",
            "room_id": room_id,
        },
        headers=auth(users["reporter"]),
    )
    issue_id = res.json()["id"]
    client.post(
        f"/api/issues/{issue_id}/accept", json={"estimated_days": 1}, headers=auth(users["head"])
    )

    up = client.post(
        f"/api/issues/{issue_id}/images",
        files=[("files", ("a.jpg", make_jpeg(), "image/jpeg"))],
        headers=auth(users["reporter"]),
    )
    assert up.status_code == 200, up.text
    item = up.json()["items"][0]
    row = await db_pool.fetchrow("SELECT * FROM issue_images WHERE id = $1", item["id"])
    return {
        "users": users,
        "issue_id": issue_id,
        "item": item,
        "row": row,
        "db_pool": db_pool,
    }


@pytest.mark.asyncio
async def test_full_and_thumb_served(client, serving_world):
    w = serving_world
    full = client.get(w["item"]["url"])
    assert full.status_code == 200, full.text
    assert full.headers["content-type"] == "image/webp"
    assert full.headers["cache-control"] == "private, max-age=60, no-transform"
    assert full.headers["referrer-policy"] == "no-referrer"
    assert full.headers["x-content-type-options"] == "nosniff"
    assert full.headers["x-robots-tag"] == "noindex"
    assert Image.open(io.BytesIO(full.content)).format == "WEBP"

    thumb = client.get(w["item"]["thumb_url"])
    assert thumb.status_code == 200
    timg = Image.open(io.BytesIO(thumb.content))
    assert max(timg.size) <= settings.MEDIA_THUMB_DIMENSION


def _url(image_id, variant, viewer, exp, sig):
    return f"/api/images/{image_id}?variant={variant}&viewer={viewer}&exp={exp}&sig={sig}"


@pytest.mark.asyncio
async def test_missing_or_bad_params_403(client, serving_world):
    image_id = serving_world["item"]["id"]
    assert client.get(f"/api/images/{image_id}").status_code == 403
    assert client.get(_url(image_id, "full", "", "", "")).status_code == 403
    assert client.get(_url(image_id, "huge", "1", "99", "x")).status_code == 403


@pytest.mark.asyncio
async def test_tampered_viewer_403(client, serving_world):
    w = serving_world
    image_id = w["item"]["id"]
    viewer = w["users"]["head"]["user_id"]
    exp, sig = make_signature(image_id, "full", viewer)
    assert client.get(_url(image_id, "full", viewer + 1, exp, sig)).status_code == 403


@pytest.mark.asyncio
async def test_tampered_sig_403(client, serving_world):
    w = serving_world
    image_id = w["item"]["id"]
    viewer = w["users"]["head"]["user_id"]
    exp, sig = make_signature(image_id, "full", viewer)
    bad = ("A" if sig[0] != "A" else "B") + sig[1:]
    assert client.get(_url(image_id, "full", viewer, exp, bad)).status_code == 403


@pytest.mark.asyncio
async def test_expired_url_403(client, serving_world):
    w = serving_world
    image_id = w["item"]["id"]
    viewer = w["users"]["head"]["user_id"]
    exp, sig = make_signature(image_id, "full", viewer, now=int(time.time()) - 3600)
    assert client.get(_url(image_id, "full", viewer, exp, sig)).status_code == 403


@pytest.mark.asyncio
async def test_valid_signature_without_permission_403(client, serving_world):
    """ลายเซ็นถูกต้องทุกไบต์ แต่ผู้ถือไม่มีสิทธิ์เห็นเรื่อง → 403 (ตรวจสิทธิ์ซ้ำตอน GET)"""
    w = serving_world
    outsider = w["users"]["outsider"]["user_id"]
    url = sign_url(w["item"]["id"], "full", outsider)
    assert client.get(url).status_code == 403


@pytest.mark.asyncio
async def test_deleted_image_404(client, serving_world):
    w = serving_world
    res = client.delete(
        f"/api/issues/{w['issue_id']}/images/{w['item']['id']}",
        headers=auth(w["users"]["reporter"]),
    )
    assert res.status_code == 200
    assert client.get(w["item"]["url"]).status_code == 404


@pytest.mark.asyncio
async def test_missing_file_404_not_500(client, serving_world):
    w = serving_world
    path = Path(settings.MEDIA_STORAGE_DIR) / w["row"]["storage_path"]
    assert path.is_file()
    path.unlink()
    assert client.get(w["item"]["url"]).status_code == 404


@pytest.mark.asyncio
async def test_traversal_storage_path_404(client, serving_world):
    w = serving_world
    await w["db_pool"].execute(
        "UPDATE issue_images SET storage_path = '../../etc/passwd', thumb_path = NULL WHERE id = $1",
        w["item"]["id"],
    )
    assert client.get(w["item"]["url"]).status_code == 404
    assert client.get(w["item"]["thumb_url"]).status_code == 404


@pytest.mark.asyncio
async def test_valid_signature_for_non_uuid_404(client, serving_world):
    """image_id ที่ไม่ใช่ uuid — ลายเซ็นผ่านได้แต่แถวไม่มี ⇒ 404 ไม่ใช่ 500"""
    w = serving_world
    viewer = w["users"]["head"]["user_id"]
    url = sign_url("not-a-uuid", "full", viewer)
    assert client.get(url).status_code == 404


@pytest.mark.asyncio
async def test_view_requires_existing_image_row(client, serving_world):
    """ลบแถวตรง ๆ (hard delete) → URL เดิมเปิดไม่ได้"""
    w = serving_world
    victim = str(uuid.uuid4())
    assert client.get(sign_url(victim, "full", w["users"]["head"]["user_id"])).status_code == 404
