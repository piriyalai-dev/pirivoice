"""🖼️ รูปภาพของเรื่อง — อัปโหลด, สิทธิ์, ขีดจำกัด, receipt, ลบ, audit

⚠️ กฎจาก docs/rules/testing.md: ตรวจ DB ตรงหลังยืนยัน HTTP status เสมอ
   (ไม่เชื่อ response body อย่างเดียว) และห้าม hardcode id
"""
import io
import random

import pytest
import pytest_asyncio
from PIL import Image

from core.config import settings
from services import auth_service


# ===================== helpers =====================
def make_image(width=800, height=600, fmt="JPEG", color=(200, 60, 60), exif=None) -> bytes:
    im = Image.new("RGB", (width, height), color)
    buf = io.BytesIO()
    kwargs = {"format": fmt}
    if exif is not None:
        kwargs["exif"] = exif
    im.save(buf, **kwargs)
    return buf.getvalue()


def auth(user):
    return {"Authorization": f"Bearer {user['token']}"}


def upload(client, user, issue_id, blobs, kind=None):
    files = [
        ("files", (f"img{i}.jpg", data, "application/octet-stream"))
        for i, data in enumerate(blobs)
    ]
    data = {"kind": kind} if kind else {}
    return client.post(
        f"/api/issues/{issue_id}/images", files=files, data=data, headers=auth(user)
    )


def list_images(client, user, issue_id):
    return client.get(f"/api/issues/{issue_id}/images", headers=auth(user))


@pytest_asyncio.fixture
async def image_world(db_pool, client):
    """ห้องเดียว: reporter + roommate + head (รับเรื่อง) · ห้องอื่น: outsider · council admin"""
    code = f"ม.4/{random.randint(100, 999)}"
    other_code = f"ม.5/{random.randint(100, 999)}"
    async with db_pool.acquire() as conn:
        room_id = await conn.fetchval(
            "INSERT INTO rooms (room_code, room_name, level) VALUES ($1,$2,'ม.4') RETURNING id",
            code, code,
        )
        await conn.fetchval(
            "INSERT INTO rooms (room_code, room_name, level) VALUES ($1,$2,'ม.5') RETURNING id",
            other_code, other_code,
        )

    async def reg(label, role, room_code):
        sid = f"T{random.randint(100000, 999999)}"
        uid = await auth_service.register_user(
            db_pool, sid, "1234", f"{label} ทดสอบ", sid, room_code, 1, role
        )
        return {"user_id": uid, "token": auth_service.create_access_token(uid)}

    users = {
        "reporter": await reg("reporter", "student", code),
        "roommate": await reg("roommate", "student", code),
        "head": await reg("head", "class_president", code),
        "outsider": await reg("outsider", "student", other_code),
        "admin": await reg("admin", "council_president", other_code),
    }

    res = client.post(
        "/api/issues",
        json={
            "main_category": "report",
            "category": "complaint",
            "title": "เรื่องทดสอบรูป",
            "description": "รายละเอียด",
            "room_id": room_id,
        },
        headers=auth(users["reporter"]),
    )
    assert res.status_code == 200, res.text
    issue_id = res.json()["id"]

    # หัวหน้าห้องรับเรื่อง → current_assignee_id = head
    res = client.post(
        f"/api/issues/{issue_id}/accept",
        json={"estimated_days": 3},
        headers=auth(users["head"]),
    )
    assert res.status_code == 200, res.text

    return {"users": users, "issue_id": issue_id, "room_id": room_id}


# ===================== upload: permission matrix =====================
@pytest.mark.asyncio
async def test_reporter_uploads_report_image(client, db_pool, image_world):
    w = image_world
    res = upload(client, w["users"]["reporter"], w["issue_id"], [make_image()])
    assert res.status_code == 200, res.text
    item = res.json()["items"][0]
    assert item["kind"] == "report"

    rows = await db_pool.fetch(
        "SELECT * FROM issue_images WHERE issue_id = $1 AND deleted_at IS NULL",
        w["issue_id"],
    )
    assert len(rows) == 1
    assert rows[0]["kind"] == "report"
    assert rows[0]["uploaded_by"] == w["users"]["reporter"]["user_id"]
    assert len(rows[0]["sha256"]) == 64


@pytest.mark.asyncio
async def test_assignee_uploads_progress_image(client, db_pool, image_world):
    w = image_world
    res = upload(client, w["users"]["head"], w["issue_id"], [make_image()])
    assert res.status_code == 200, res.text
    assert res.json()["items"][0]["kind"] == "progress"


@pytest.mark.asyncio
async def test_upload_forbidden_for_roommate_outsider_admin(client, image_world):
    w = image_world
    for who in ("roommate", "outsider", "admin"):
        res = upload(client, w["users"][who], w["issue_id"], [make_image()])
        assert res.status_code == 403, f"{who}: {res.text}"


@pytest.mark.asyncio
async def test_reporter_cannot_upload_progress_kind(client, image_world):
    """ผู้แจ้งไม่ใช่ผู้รับ → server ตัดสิน kind=report เสมอ ไม่สนใจ form field"""
    w = image_world
    res = upload(client, w["users"]["reporter"], w["issue_id"], [make_image()], kind="progress")
    assert res.status_code == 200, res.text
    assert res.json()["items"][0]["kind"] == "report"


# ===================== processing =====================
@pytest.mark.asyncio
async def test_image_is_resized_webp_and_exif_stripped(client, db_pool, image_world):
    w = image_world
    exif = Image.Exif()
    exif[0x0112] = 6  # orientation — ต้องถูกใช้แล้วทิ้ง
    exif[0x010F] = "TestPhone"
    raw = make_image(width=3200, height=2400, exif=exif.tobytes())

    res = upload(client, w["users"]["reporter"], w["issue_id"], [raw])
    assert res.status_code == 200, res.text
    item = res.json()["items"][0]
    assert max(item["width"], item["height"]) <= settings.MEDIA_MAX_DIMENSION

    row = await db_pool.fetchrow(
        "SELECT * FROM issue_images WHERE id = $1", item["id"]
    )
    full = Image.open(f"{settings.MEDIA_STORAGE_DIR}/{row['storage_path']}")
    thumb = Image.open(f"{settings.MEDIA_STORAGE_DIR}/{row['thumb_path']}")
    assert full.format == "WEBP"
    assert max(full.size) <= settings.MEDIA_MAX_DIMENSION
    assert max(thumb.size) <= settings.MEDIA_THUMB_DIMENSION
    # ล้าง EXIF: ไม่มีทั้ง orientation และ maker tag
    assert len(full.getexif()) == 0

    # sha256 ต้องตรงกับไฟล์จริงบนดิสก์
    import hashlib

    disk = open(f"{settings.MEDIA_STORAGE_DIR}/{row['storage_path']}", "rb").read()
    assert hashlib.sha256(disk).hexdigest() == row["sha256"]


@pytest.mark.parametrize(
    "raw",
    [
        b"not an image at all",
        make_image(fmt="GIF"),
        make_image(width=32, height=32),
    ],
    ids=["fake-bytes", "gif", "too-small"],
)
@pytest.mark.asyncio
async def test_invalid_images_rejected(client, image_world, raw):
    w = image_world
    res = upload(client, w["users"]["reporter"], w["issue_id"], [raw])
    assert res.status_code == 400, res.text


@pytest.mark.asyncio
async def test_oversized_file_rejected(client, image_world):
    w = image_world
    huge = b"\x00" * (settings.MEDIA_IMAGE_SIZE_LIMIT_MB * 1024 * 1024 + 1)
    res = upload(client, w["users"]["reporter"], w["issue_id"], [huge])
    assert res.status_code == 413, res.text


@pytest.mark.asyncio
async def test_max_images_per_kind(client, image_world):
    w = image_world
    res = upload(client, w["users"]["reporter"], w["issue_id"], [make_image()] * 3)
    assert res.status_code == 200, res.text
    res = upload(client, w["users"]["reporter"], w["issue_id"], [make_image()])
    assert res.status_code == 400, res.text


@pytest.mark.asyncio
async def test_max_files_per_request(client, image_world):
    w = image_world
    res = upload(client, w["users"]["reporter"], w["issue_id"], [make_image()] * 4)
    assert res.status_code == 400, res.text


@pytest.mark.asyncio
async def test_hourly_rate_limit(client, image_world, monkeypatch):
    w = image_world
    monkeypatch.setattr(settings, "MEDIA_MAX_UPLOAD_PER_HOUR", 2)
    assert upload(client, w["users"]["reporter"], w["issue_id"], [make_image()]).status_code == 200
    assert upload(client, w["users"]["reporter"], w["issue_id"], [make_image()]).status_code == 200
    res = upload(client, w["users"]["reporter"], w["issue_id"], [make_image()])
    assert res.status_code == 429, res.text


# ===================== list / visibility =====================
@pytest.mark.asyncio
async def test_visibility_of_image_list(client, image_world):
    w = image_world
    assert upload(client, w["users"]["reporter"], w["issue_id"], [make_image()]).status_code == 200

    for who in ("reporter", "roommate", "head", "admin"):
        res = list_images(client, w["users"][who], w["issue_id"])
        assert res.status_code == 200, f"{who}: {res.text}"
        assert len(res.json()["items"]) == 1

    res = list_images(client, w["users"]["outsider"], w["issue_id"])
    assert res.status_code == 403, res.text


# ===================== receipts =====================
@pytest.mark.asyncio
async def test_receipt_tracks_current_assignee_and_roommates(client, db_pool, image_world):
    w = image_world
    up = upload(client, w["users"]["reporter"], w["issue_id"], [make_image()])
    assert up.status_code == 200
    url = up.json()["items"][0]["url"]
    image_id = up.json()["items"][0]["id"]

    # ยังไม่มีใครเปิด
    res = list_images(client, w["users"]["reporter"], w["issue_id"])
    receipt = res.json()["items"][0]["receipt"]
    assert receipt is not None
    assert receipt["current_assignee_viewed"] is False
    assert receipt["other_viewer_count"] == 0

    # ผู้รับปัจจุบันเปิดรูป — URL ต้องเป็นลายเซ็นของ "ผู้ดู" ⇒ ดึงจาก list ของเขาเอง
    # (ไม่มี Authorization — signed URL)
    head_url = list_images(client, w["users"]["head"], w["issue_id"]).json()["items"][0]["url"]
    assert client.get(head_url).status_code == 200

    res = list_images(client, w["users"]["reporter"], w["issue_id"])
    receipt = res.json()["items"][0]["receipt"]
    assert receipt["current_assignee_viewed"] is True
    assert receipt["current_assignee_viewed_at"] is not None

    views = await db_pool.fetch(
        "SELECT * FROM issue_image_views WHERE image_id = $1", image_id
    )
    assert len(views) == 1
    assert views[0]["user_id"] == w["users"]["head"]["user_id"]
    assert views[0]["view_count"] == 1

    # เพื่อนร่วมห้องเปิด → other_viewer_count = 1 (ไม่ปนกับผู้รับผิดชอบ)
    url_roommate = list_images(client, w["users"]["roommate"], w["issue_id"]).json()["items"][0]["url"]
    assert client.get(url_roommate).status_code == 200
    receipt = list_images(client, w["users"]["reporter"], w["issue_id"]).json()["items"][0]["receipt"]
    assert receipt["current_assignee_viewed"] is True
    assert receipt["other_viewer_count"] == 1


@pytest.mark.asyncio
async def test_receipt_hidden_from_assignee(client, image_world):
    w = image_world
    upload(client, w["users"]["reporter"], w["issue_id"], [make_image()])
    res = list_images(client, w["users"]["head"], w["issue_id"])
    assert res.status_code == 200
    assert res.json()["items"][0]["receipt"] is None


@pytest.mark.asyncio
async def test_view_dedupe_window(client, db_pool, image_world):
    w = image_world
    up = upload(client, w["users"]["reporter"], w["issue_id"], [make_image()])
    url = up.json()["items"][0]["url"]
    image_id = up.json()["items"][0]["id"]

    head_url = list_images(client, w["users"]["head"], w["issue_id"]).json()["items"][0]["url"]
    assert client.get(head_url).status_code == 200
    assert client.get(head_url).status_code == 200
    row = await db_pool.fetchrow(
        "SELECT view_count FROM issue_image_views WHERE image_id = $1 AND user_id = $2",
        image_id, w["users"]["head"]["user_id"],
    )
    assert row["view_count"] == 1  # เปิดซ้ำใน 10 นาที ไม่นับเพิ่ม

    # ดัน last_viewed_at ย้อนหลังเกิน dedupe → เปิดอีกครั้งนับเพิ่ม
    await db_pool.execute(
        "UPDATE issue_image_views SET last_viewed_at = NOW() - INTERVAL '30 minutes' "
        "WHERE image_id = $1 AND user_id = $2",
        image_id, w["users"]["head"]["user_id"],
    )
    assert client.get(head_url).status_code == 200
    row = await db_pool.fetchrow(
        "SELECT view_count FROM issue_image_views WHERE image_id = $1 AND user_id = $2",
        image_id, w["users"]["head"]["user_id"],
    )
    assert row["view_count"] == 2


@pytest.mark.asyncio
async def test_reporter_and_uploader_views_not_recorded(client, db_pool, image_world):
    w = image_world
    # ผู้รับอัปรูป progress ของตัวเอง
    up = upload(client, w["users"]["head"], w["issue_id"], [make_image()])
    url = up.json()["items"][0]["url"]
    image_id = up.json()["items"][0]["id"]

    assert client.get(url).status_code == 200  # ผู้รับเปิดรูปที่ตัวเองอัป
    res = list_images(client, w["users"]["reporter"], w["issue_id"])
    reporter_url = res.json()["items"][0]["url"]
    assert client.get(reporter_url).status_code == 200  # ผู้แจ้งเปิดรูปของเรื่องตัวเอง

    count = await db_pool.fetchval(
        "SELECT COUNT(*) FROM issue_image_views WHERE image_id = $1", image_id
    )
    assert count == 0


# ===================== delete =====================
@pytest.mark.asyncio
async def test_uploader_can_soft_delete(client, db_pool, image_world):
    w = image_world
    up = upload(client, w["users"]["reporter"], w["issue_id"], [make_image()])
    item = up.json()["items"][0]
    url = item["url"]

    res = client.delete(
        f"/api/issues/{w['issue_id']}/images/{item['id']}", headers=auth(w["users"]["reporter"])
    )
    assert res.status_code == 200, res.text

    row = await db_pool.fetchrow(
        "SELECT deleted_at, storage_path FROM issue_images WHERE id = $1", item["id"]
    )
    assert row["deleted_at"] is not None
    # ไฟล์ยังอยู่บนดิสก์ (purge เป็นเฟสแยก)
    from pathlib import Path

    assert (Path(settings.MEDIA_STORAGE_DIR) / row["storage_path"]).is_file()
    assert client.get(url).status_code == 404
    assert list_images(client, w["users"]["reporter"], w["issue_id"]).json()["items"] == []


@pytest.mark.asyncio
async def test_other_people_cannot_delete(client, image_world):
    w = image_world
    up = upload(client, w["users"]["reporter"], w["issue_id"], [make_image()])
    image_id = up.json()["items"][0]["id"]
    for who in ("head", "roommate", "outsider"):
        res = client.delete(
            f"/api/issues/{w['issue_id']}/images/{image_id}", headers=auth(w["users"][who])
        )
        assert res.status_code == 403, f"{who}: {res.text}"


@pytest.mark.asyncio
async def test_admin_can_delete_any_image(client, db_pool, image_world):
    w = image_world
    up = upload(client, w["users"]["reporter"], w["issue_id"], [make_image()])
    image_id = up.json()["items"][0]["id"]
    res = client.delete(
        f"/api/issues/{w['issue_id']}/images/{image_id}", headers=auth(w["users"]["admin"])
    )
    assert res.status_code == 200, res.text
    row = await db_pool.fetchrow("SELECT deleted_at FROM issue_images WHERE id = $1", image_id)
    assert row["deleted_at"] is not None


@pytest.mark.asyncio
async def test_reporter_cannot_delete_after_issue_closed(client, image_world):
    w = image_world
    up = upload(client, w["users"]["reporter"], w["issue_id"], [make_image()])
    image_id = up.json()["items"][0]["id"]
    res = client.post(
        f"/api/issues/{w['issue_id']}/resolve", json={"reason": "เสร็จ"}, headers=auth(w["users"]["head"])
    )
    assert res.status_code == 200, res.text
    res = client.delete(
        f"/api/issues/{w['issue_id']}/images/{image_id}", headers=auth(w["users"]["reporter"])
    )
    assert res.status_code == 403, res.text


# ===================== audit =====================
@pytest.mark.asyncio
async def test_upload_and_delete_are_audited(client, db_pool, image_world):
    w = image_world
    up = upload(client, w["users"]["reporter"], w["issue_id"], [make_image()])
    item = up.json()["items"][0]

    row = await db_pool.fetchrow(
        "SELECT * FROM audit_logs WHERE action = 'CREATE_ISSUE_IMAGE' AND entity_id = $1",
        item["id"],
    )
    assert row is not None
    import json

    new_values = json.loads(row["new_values"]) if isinstance(row["new_values"], str) else row["new_values"]
    assert new_values["issue_id"] == w["issue_id"]
    assert new_values["kind"] == "report"
    assert len(new_values["sha256"]) == 64

    client.delete(
        f"/api/issues/{w['issue_id']}/images/{item['id']}", headers=auth(w["users"]["reporter"])
    )
    row = await db_pool.fetchrow(
        "SELECT * FROM audit_logs WHERE action = 'DELETE_ISSUE_IMAGE' AND entity_id = $1",
        item["id"],
    )
    assert row is not None
