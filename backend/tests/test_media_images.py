"""🖼️ รูปภาพกลาง (media_images) — policy registry, อัป/ลบ, เพดาน, signed URL, audit

PR1 = core เท่านั้น ⇒ เทสต์ใช้เจ้าของ 2 ชนิดที่ตั้งง่ายโดยไม่ต้องมีเนื้อหาอื่น:
  - `user` (avatar) — ทุกคนมีแถวของตัวเองอยู่แล้ว
  - `announcement` — insert แถวตรงได้ (การแนบรูปใน payload ของบอร์ด/ประกาศ มาพร้อม PR ถัดไป)

⚠️ กฎ testing.md: ตรวจ DB ตรงหลังยืนยัน HTTP status, id สุ่ม, ไม่ hardcode
"""
import io
import random

import pytest
import pytest_asyncio
from PIL import Image

from core.config import settings
from core.exceptions import ValidationError
from services import auth_service
from services.media_policies import get_policy


def make_image(width=640, height=480, fmt="JPEG", color=(30, 90, 160)) -> bytes:
    im = Image.new("RGB", (width, height), color)
    buf = io.BytesIO()
    im.save(buf, format=fmt)
    return buf.getvalue()


def auth(user):
    return {"Authorization": f"Bearer {user['token']}"}


def upload(client, user, owner_type, owner_id, blobs, kind=None):
    files = [
        ("files", (f"img{i}.jpg", data, "application/octet-stream"))
        for i, data in enumerate(blobs)
    ]
    data = {"kind": kind} if kind else {}
    return client.post(
        f"/api/media/{owner_type}/{owner_id}", files=files, data=data, headers=auth(user)
    )


@pytest_asyncio.fixture
async def media_world(db_pool, client):
    """ห้องเดียว: admin (is_admin) · council · student · student2"""
    room_code = f"ม.6/{random.randint(1, 90)}"
    async with db_pool.acquire() as conn:
        room_id = await conn.fetchval(
            "INSERT INTO rooms (room_code, room_name, level) VALUES ($1,$2,'ม.6') RETURNING id",
            room_code, room_code,
        )

    users = {}
    for label, role in [
        ("admin", "admin"),
        ("council", "council_member"),
        ("student", "student"),
        ("student2", "student"),
    ]:
        sid = f"MD{random.randint(100000, 999999)}"  # ≤ 10 ตัว
        uid = await auth_service.register_user(
            db_pool, sid, "1234", f"{label} ทดสอบ", sid, room_code, 1, role
        )
        users[label] = {"user_id": uid, "token": auth_service.create_access_token(uid)}
    users["room_id"] = room_id
    return users


async def _make_announcement(db_pool) -> int:
    async with db_pool.acquire() as conn:
        return await conn.fetchval(
            "INSERT INTO announcements (message, priority) VALUES ($1, 'normal') RETURNING id",
            f"ประกาศทดสอบ {random.randint(1, 10**9)}",
        )


# ============================================================
# 🧭 registry — fail-closed
# ============================================================
@pytest.mark.parametrize("owner_type", ["issue", "piri_board", "user_avatar", "", "BOARD"])
def test_unknown_owner_type_raises(owner_type):
    with pytest.raises(ValidationError):
        get_policy(owner_type)


def test_registry_kinds_are_single_per_owner():
    assert get_policy("board").kind == "cover"
    assert get_policy("board_comment").kind == "attachment"
    assert get_policy("announcement").kind == "attachment"
    assert get_policy("event").kind == "cover"
    assert get_policy("user").kind == "avatar"


# ============================================================
# 👤 avatar (owner_type=user)
# ============================================================
@pytest.mark.asyncio
async def test_avatar_upload_and_db_row(client, db_pool, media_world):
    me = media_world["student"]
    res = upload(client, me, "user", me["user_id"], [make_image(width=1600, height=1200)])
    assert res.status_code == 200, res.text
    body = res.json()
    item = body["items"][0]
    assert item["kind"] == "avatar"
    assert item["owner_type"] == "user"
    assert item["owner_id"] == me["user_id"]
    assert "/api/media/file/" in item["url"] and "variant=full" in item["url"]
    assert "variant=thumb" in item["thumb_url"]
    # ไม่ส่ง uploaded_by (anonymous guard)
    assert "uploaded_by" not in item
    assert body["limits"]["max_per_owner"] == settings.MEDIA_MAX_AVATAR_IMAGES

    row = await db_pool.fetchrow("SELECT * FROM media_images WHERE id = $1", item["id"])
    assert row is not None
    assert row["owner_type"] == "user" and row["owner_id"] == me["user_id"]
    assert row["uploaded_by"] == me["user_id"]
    assert row["storage_path"].startswith(f"media/user/{me['user_id']}/")
    assert row["storage_path"].endswith(".webp")
    assert row["thumb_path"].endswith("_thumb.webp")
    assert len(row["sha256"]) == 64
    assert row["width"] == 1600 and row["height"] == 1200
    assert row["mime"] == "image/webp"
    assert row["deleted_at"] is None

    # audit ใน transaction เดียวกัน
    audit = await db_pool.fetchrow(
        "SELECT * FROM audit_logs WHERE action = 'CREATE_MEDIA_IMAGE' AND entity_id = $1",
        item["id"],
    )
    assert audit is not None
    assert audit["entity_type"] == "media_image"


@pytest.mark.asyncio
async def test_avatar_for_other_user_forbidden(client, media_world):
    res = upload(
        client, media_world["student"], "user", media_world["student2"]["user_id"], [make_image()]
    )
    assert res.status_code == 403, res.text


@pytest.mark.asyncio
async def test_avatar_upload_to_missing_user_404(client, media_world):
    res = upload(client, media_world["student"], "user", 999_999_999, [make_image()])
    assert res.status_code == 404, res.text


@pytest.mark.asyncio
async def test_avatar_replace_keeps_single_live_row(client, db_pool, media_world):
    me = media_world["student"]
    first = upload(client, me, "user", me["user_id"], [make_image()])
    second = upload(client, me, "user", me["user_id"], [make_image(color=(9, 9, 9))])
    assert first.status_code == 200 and second.status_code == 200, second.text

    live = await db_pool.fetch(
        "SELECT id FROM media_images WHERE owner_type='user' AND owner_id=$1 AND deleted_at IS NULL",
        me["user_id"],
    )
    assert len(live) == 1
    assert str(live[0]["id"]) == second.json()["items"][0]["id"]

    old = await db_pool.fetchrow(
        "SELECT deleted_at FROM media_images WHERE id = $1", first.json()["items"][0]["id"]
    )
    assert old["deleted_at"] is not None


@pytest.mark.asyncio
async def test_wrong_kind_for_owner_rejected(client, media_world):
    me = media_world["student"]
    res = upload(client, me, "user", me["user_id"], [make_image()], kind="cover")
    assert res.status_code == 400, res.text


@pytest.mark.asyncio
async def test_unknown_owner_type_route_400(client, media_world):
    me = media_world["student"]
    res = upload(client, me, "issue", 1, [make_image()])
    assert res.status_code == 400, res.text


@pytest.mark.asyncio
async def test_too_many_files_rejected(client, media_world):
    me = media_world["student"]
    res = upload(client, me, "user", me["user_id"], [make_image(), make_image()])
    assert res.status_code == 400, res.text


@pytest.mark.asyncio
async def test_oversized_file_413(client, media_world):
    me = media_world["student"]
    huge = b"\x00" * (settings.MEDIA_IMAGE_SIZE_LIMIT_MB * 1024 * 1024 + 1)
    res = upload(client, me, "user", me["user_id"], [huge])
    assert res.status_code == 413, res.text


@pytest.mark.parametrize("raw", [b"not an image", make_image(fmt="GIF"), make_image(32, 32)])
@pytest.mark.asyncio
async def test_invalid_images_rejected(client, media_world, raw):
    me = media_world["student"]
    res = upload(client, me, "user", me["user_id"], [raw])
    assert res.status_code == 400, res.text


@pytest.mark.asyncio
async def test_hourly_rate_limit(client, db_pool, media_world, monkeypatch):
    monkeypatch.setattr(settings, "MEDIA_MAX_UPLOAD_PER_HOUR", 2)
    me = media_world["student"]
    assert upload(client, me, "user", me["user_id"], [make_image()]).status_code == 200
    # การ "เปลี่ยนปก" (แทนที่ของเดิม) ก็นับชั่วโมงละครั้ง — ไม่ใช่ทางลัดข้ามเพดาน
    assert upload(client, me, "user", me["user_id"], [make_image()]).status_code == 200
    res = upload(client, me, "user", me["user_id"], [make_image()])
    assert res.status_code == 429, res.text

    # เพดานเป็นรายคน — ผู้ใช้อื่นยังอัปได้
    ann = await _make_announcement(db_pool)
    ok = upload(client, media_world["admin"], "announcement", ann, [make_image()])
    assert ok.status_code == 200, ok.text


# ============================================================
# 📣 announcement (owner_type=announcement)
# ============================================================
@pytest.mark.asyncio
async def test_announcement_upload_permission_matrix(client, db_pool, media_world):
    ann = await _make_announcement(db_pool)
    assert upload(client, media_world["admin"], "announcement", ann, [make_image()]).status_code == 200
    # สภานักเรียนมี MANAGE_ANNOUNCEMENTS ตาม config/roles.json (แทนที่รูปเดิมได้)
    assert upload(client, media_world["council"], "announcement", ann, [make_image()]).status_code == 200

    res = upload(client, media_world["student"], "announcement", ann, [make_image()])
    assert res.status_code == 403, res.text


@pytest.mark.asyncio
async def test_announcement_missing_404(client, media_world):
    res = upload(client, media_world["admin"], "announcement", 999_999_999, [make_image()])
    assert res.status_code == 404, res.text


@pytest.mark.asyncio
async def test_announcement_delete_by_admin_soft_deletes(client, db_pool, media_world):
    ann = await _make_announcement(db_pool)
    item = upload(client, media_world["admin"], "announcement", ann, [make_image()]).json()["items"][0]

    res = client.delete(
        f"/api/media/announcement/{ann}/{item['id']}", headers=auth(media_world["admin"])
    )
    assert res.status_code == 200, res.text

    row = await db_pool.fetchrow("SELECT deleted_at FROM media_images WHERE id = $1", item["id"])
    assert row["deleted_at"] is not None
    audit = await db_pool.fetchrow(
        "SELECT 1 FROM audit_logs WHERE action = 'DELETE_MEDIA_IMAGE' AND entity_id = $1",
        item["id"],
    )
    assert audit is not None


@pytest.mark.asyncio
async def test_avatar_delete_by_other_forbidden(client, media_world):
    me = media_world["student"]
    item = upload(client, me, "user", me["user_id"], [make_image()]).json()["items"][0]
    res = client.delete(
        f"/api/media/user/{me['user_id']}/{item['id']}",
        headers=auth(media_world["student2"]),
    )
    assert res.status_code == 403, res.text


# ============================================================
# 👁️ signed URL + serving
# ============================================================
@pytest.mark.asyncio
async def test_serve_full_and_thumb(client, media_world):
    me = media_world["student"]
    item = upload(client, me, "user", me["user_id"], [make_image()]).json()["items"][0]

    full = client.get(item["url"])
    assert full.status_code == 200, full.text
    assert full.headers["content-type"].startswith("image/webp")
    assert full.headers["cache-control"].startswith("private")
    assert full.headers["x-content-type-options"] == "nosniff"

    thumb = client.get(item["thumb_url"])
    assert thumb.status_code == 200, thumb.text
    # thumbnail เล็กกว่าหรือเท่าของเต็ม
    assert len(thumb.content) <= len(full.content)


@pytest.mark.asyncio
async def test_serve_rejects_tampered_signature(client, media_world):
    me = media_world["student"]
    item = upload(client, me, "user", me["user_id"], [make_image()]).json()["items"][0]
    bad = item["url"][:-3] + "AAA"
    assert client.get(bad).status_code == 403


@pytest.mark.asyncio
async def test_serve_rejects_expired(client, media_world):
    from core.media_signing import sign_url

    me = media_world["student"]
    item = upload(client, me, "user", me["user_id"], [make_image()]).json()["items"][0]
    old_url = sign_url(item["id"], "full", me["user_id"], now=1000, scope="media")
    assert client.get(old_url).status_code == 403


@pytest.mark.asyncio
async def test_issue_scope_signature_cannot_open_media(client, media_world):
    """ลายเซ็นของเรื่องใช้กับรูปกลางไม่ได้ (scope แยกโดเมน)"""
    from core.media_signing import sign_url

    me = media_world["student"]
    item = upload(client, me, "user", me["user_id"], [make_image()]).json()["items"][0]
    wrong_scope = sign_url(item["id"], "full", me["user_id"])  # scope default = issue-image
    assert client.get(wrong_scope.replace("/api/images/", "/api/media/file/")).status_code == 403


@pytest.mark.asyncio
async def test_serve_after_announcement_deleted_404(client, db_pool, media_world):
    ann = await _make_announcement(db_pool)
    item = upload(client, media_world["admin"], "announcement", ann, [make_image()]).json()["items"][0]
    assert client.get(item["url"]).status_code == 200

    async with db_pool.acquire() as conn:
        await conn.execute("UPDATE announcements SET deleted_at = NOW() WHERE id = $1", ann)
    assert client.get(item["url"]).status_code == 404


@pytest.mark.asyncio
async def test_serve_after_image_soft_deleted_404(client, media_world):
    me = media_world["student"]
    res = upload(client, me, "user", me["user_id"], [make_image()]).json()
    item = res["items"][0]
    client.delete(f"/api/media/user/{me['user_id']}/{item['id']}", headers=auth(me))
    assert client.get(item["url"]).status_code == 404


# ============================================================
# 📋 list + batch map
# ============================================================
@pytest.mark.asyncio
async def test_list_returns_only_live_images(client, media_world):
    me = media_world["student"]
    old = upload(client, me, "user", me["user_id"], [make_image()]).json()["items"][0]
    new = upload(client, me, "user", me["user_id"], [make_image()]).json()["items"][0]

    res = client.get(f"/api/media/user/{me['user_id']}", headers=auth(media_world["student2"]))
    assert res.status_code == 200, res.text
    ids = [i["id"] for i in res.json()["items"]]
    assert ids == [new["id"]]
    assert old["id"] not in ids


@pytest.mark.asyncio
async def test_signed_media_map_batches(client, db_pool, media_world):
    from services import media_service

    a, b = media_world["student"], media_world["student2"]
    ia = upload(client, a, "user", a["user_id"], [make_image()]).json()["items"][0]
    ib = upload(client, b, "user", b["user_id"], [make_image()]).json()["items"][0]

    async with db_pool.acquire() as conn:
        m = await media_service.signed_media_map(
            conn, "user", [a["user_id"], b["user_id"], 999_999_999], a["user_id"], kind="avatar"
        )
    assert str(m[a["user_id"]][0]["id"]) == ia["id"]
    assert str(m[b["user_id"]][0]["id"]) == ib["id"]
    assert 999_999_999 not in m


@pytest.mark.asyncio
async def test_get_avatar_helper(client, db_pool, media_world):
    from services import media_service

    me = media_world["student"]
    assert await db_pool.fetchval("SELECT 1") is not None
    async with db_pool.acquire() as conn:
        assert await media_service.get_avatar(conn, me["user_id"], me["user_id"]) is None
    item = upload(client, me, "user", me["user_id"], [make_image()]).json()["items"][0]
    async with db_pool.acquire() as conn:
        got = await media_service.get_avatar(conn, me["user_id"], me["user_id"])
    assert got is not None and got["id"] == item["id"]


# ============================================================
# 🔐 proxy auth
# ============================================================
@pytest.mark.asyncio
async def test_upload_requires_auth(client, media_world):
    res = client.post(
        f"/api/media/user/{media_world['student']['user_id']}",
        files=[("files", ("i.jpg", make_image(), "application/octet-stream"))],
    )
    assert res.status_code in (401, 403)
