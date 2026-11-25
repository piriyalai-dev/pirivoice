"""🖼️ รูปภาพกลาง (media_images) — policy registry, อัป/ลบ, เพดาน, signed URL, audit

PR1 = core เท่านั้น ⇒ เทสต์ใช้เจ้าของ 2 ชนิดที่ตั้งง่ายโดยไม่ต้องมีเนื้อหาอื่น:
  - `user` (avatar) — ทุกคนมีแถวของตัวเองอยู่แล้ว
  - `announcement` — insert แถวตรงได้ (การแนบรูปใน payload ของบอร์ด/ประกาศ มาพร้อม PR ถัดไป)

⚠️ กฎ testing.md: ตรวจ DB ตรงหลังยืนยัน HTTP status, id สุ่ม, ไม่ hardcode
"""
import io
import random
from datetime import datetime, timedelta, timezone

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


# ============================================================
# 🗂️ board / board_comment — แนบรูปใน payload ของบอร์ด (PR2)
# ============================================================
def _make_suggestion(client, user, title=None) -> int:
    """สร้างข้อเสนอแนะผ่าน API จริง — บอร์ดชนิดเดียวที่ผู้ใช้ทั่วไปสร้างได้"""
    res = client.post(
        "/api/boards/suggestions",
        json={
            "title": title or f"ข้อเสนอทดสอบ {random.randint(1, 10**6)}",
            "description": "รายละเอียดสำหรับทดสอบรูปปก",
            "is_anonymous": False,
        },
        headers=auth(user),
    )
    assert res.status_code == 201, res.text
    return res.json()["id"]


@pytest.mark.asyncio
async def test_board_cover_in_feed_and_detail(client, media_world):
    """ปกบอร์ดถูกแนบมาใน feed + detail · คนอื่นอัปให้บอร์ดของเราไม่ได้"""
    author = media_world["student"]
    board_id = _make_suggestion(client, author)

    # policy: เจ้าของโพสต์หรือสภาเท่านั้น
    assert upload(client, media_world["student2"], "board", board_id, [make_image()]).status_code == 403
    item = upload(client, author, "board", board_id, [make_image()]).json()["items"][0]

    feed = client.get("/api/boards", headers=auth(media_world["student2"]))
    assert feed.status_code == 200, feed.text
    row = next((b for b in feed.json()["items"] if b["id"] == board_id), None)
    assert row is not None, "บอร์ดใหม่ต้องอยู่ในหน้าแรกของ feed"
    assert row["cover_image"]["id"] == item["id"]
    # ลายเซ็นผูกกับผู้ดู ⇒ URL ที่ได้จาก feed ของ student2 ต้องเปิดได้
    assert client.get(row["cover_image"]["url"]).status_code == 200

    detail = client.get(f"/api/boards/{board_id}", headers=auth(media_world["student2"]))
    assert detail.status_code == 200, detail.text
    assert detail.json()["cover_image"]["id"] == item["id"]


@pytest.mark.asyncio
async def test_board_cover_replacement_keeps_single_live_row(client, db_pool, media_world):
    """เปลี่ยนปก = soft-delete ของเดิม + แถวใหม่ ใน transaction เดียว (unique index ไม่เคยเห็น 2 แถว)"""
    author = media_world["student"]
    board_id = _make_suggestion(client, author)
    old = upload(client, author, "board", board_id, [make_image()]).json()["items"][0]
    new = upload(client, author, "board", board_id, [make_image(color=(200, 20, 20))]).json()["items"][0]

    async with db_pool.acquire() as conn:
        live = await conn.fetch(
            """SELECT id, deleted_at FROM media_images
               WHERE owner_type = 'board' AND owner_id = $1 AND kind = 'cover'""",
            board_id,
        )
    by_id = {str(r["id"]): r["deleted_at"] for r in live}
    assert len(by_id) == 2
    assert by_id[old["id"]] is not None
    assert by_id[new["id"]] is None

    # รูปที่ถูกแทนที่แล้วเสิร์ฟไม่ได้
    assert client.get(old["url"]).status_code == 404


@pytest.mark.asyncio
async def test_board_comment_image_in_detail(client, media_world):
    """รูปคอมเมนต์ถูกแนบมาที่ node ของคอมเมนต์ใน detail (ไม่รั่วข้ามคอมเมนต์)"""
    author = media_world["student"]
    board_id = _make_suggestion(client, author)

    c1 = client.post(
        f"/api/boards/{board_id}/comments", json={"body": "เห็นด้วย"}, headers=auth(author)
    )
    c2 = client.post(
        f"/api/boards/{board_id}/comments",
        json={"body": "ไม่แน่ใจ"},
        headers=auth(media_world["student2"]),
    )
    assert c1.status_code == 200 and c2.status_code == 200, (c1.text, c2.text)
    id1, id2 = c1.json()["id"], c2.json()["id"]

    item = upload(client, author, "board_comment", id1, [make_image()]).json()["items"][0]

    detail = client.get(f"/api/boards/{board_id}", headers=auth(media_world["student2"]))
    assert detail.status_code == 200, detail.text
    nodes = {n["id"]: n for n in detail.json()["comments"]}
    assert nodes[id1]["image"]["id"] == item["id"]
    assert nodes[id2]["image"] is None
    assert client.get(nodes[id1]["image"]["thumb_url"]).status_code == 200


@pytest.mark.asyncio
async def test_hidden_board_cover_is_not_served(client, media_world):
    """บอร์ดถูกซ่อน ⇒ รูปปกเสิร์ฟไม่ได้ทันที (policy ตรวจสดทุกครั้ง ไม่พึ่ง FK)"""
    author = media_world["student"]
    board_id = _make_suggestion(client, author)
    item = upload(client, author, "board", board_id, [make_image()]).json()["items"][0]
    assert client.get(item["url"]).status_code == 200

    hidden = client.post(
        f"/api/boards/{board_id}/hide",
        json={"reason": "ทดสอบซ่อน"},
        headers=auth(media_world["council"]),
    )
    assert hidden.status_code == 200, hidden.text

    assert client.get(item["url"]).status_code == 404
    assert client.get(f"/api/boards/{board_id}", headers=auth(author)).status_code == 404


@pytest.mark.asyncio
async def test_cover_editable_flag_follows_policy(client, media_world):
    """`cover_editable` = เจ้าของโพสต์หรือสภา · คนอื่น False

    ⚠️ บอร์ด anonymous: `author_id` ถูกส่งเป็น null ⇒ frontend เทียบเองไม่ได้
    ตัว flag นี้จึงต้องคำนวณจาก `author_id` ดิบฝั่ง server
    """
    author, other, council = (
        media_world["student"],
        media_world["student2"],
        media_world["council"],
    )
    board_id = _make_suggestion(client, author)

    assert client.get(f"/api/boards/{board_id}", headers=auth(author)).json()["cover_editable"] is True
    assert client.get(f"/api/boards/{board_id}", headers=auth(other)).json()["cover_editable"] is False
    assert client.get(f"/api/boards/{board_id}", headers=auth(council)).json()["cover_editable"] is True

    # anonymous board — เจ้าของยังจัดการปกได้ แม้ `author_id` จะเป็น null ใน payload
    anon = client.post(
        "/api/boards/suggestions",
        json={
            "title": f"ข้อเสนอไม่ระบุตัวตน {random.randint(1, 10**6)}",
            "description": "รายละเอียด",
            "is_anonymous": True,
        },
        headers=auth(author),
    )
    assert anon.status_code == 201, anon.text
    anon_id = anon.json()["id"]
    detail = client.get(f"/api/boards/{anon_id}", headers=auth(author)).json()
    assert detail["author_id"] is None
    assert detail["cover_editable"] is True


# ============================================================
# 📣 announcement — รูปใน list/admin + Home แต่ *ไม่* ทาง public
# ============================================================
@pytest.mark.asyncio
async def test_announcement_image_admin_list_home_and_public_gate(client, db_pool, media_world):
    admin = media_world["admin"]
    created = client.post(
        "/api/announcements",
        json={"message": f"ประกาศมีรูป {random.randint(1, 10**9)}", "priority": "normal"},
        headers=auth(admin),
    )
    assert created.status_code == 201, created.text
    ann_id = created.json()["id"]

    item = upload(client, admin, "announcement", ann_id, [make_image()]).json()["items"][0]

    # 1) หน้า admin เห็นรูปของแถวนั้น
    listing = client.get("/api/announcements", headers=auth(admin))
    assert listing.status_code == 200, listing.text
    row = next(i for i in listing.json()["items"] if i["id"] == ann_id)
    assert row["image"]["thumb_url"] == item["thumb_url"]

    # 2) ผู้ใช้ที่ล็อกอินเห็นรูปบน Home (/api/home/summary)
    home = client.get("/api/home/summary", headers=auth(media_world["student"]))
    assert home.status_code == 200, home.text
    hrow = next(a for a in home.json()["announcements"] if a["id"] == ann_id)
    assert hrow["image"]["url"], "Home ต้องแนบรูปให้ผู้ที่ล็อกอิน"

    # 3) endpoint public (ไม่ล็อกอิน) **ห้าม** มีรูป — Landing ยังเป็นข้อความล้วน
    pub = client.get("/api/v1/public/announcements")
    assert pub.status_code == 200, pub.text
    prow = next(a for a in pub.json() if a["id"] == ann_id)
    assert prow["image"] is None

    # 4) signed URL ยังเสิร์ฟได้จริง
    served = client.get(item["thumb_url"])
    assert served.status_code == 200
    assert served.headers["content-type"].startswith("image/")


@pytest.mark.asyncio
async def test_announcement_image_stops_serving_after_delete(client, db_pool, media_world):
    admin = media_world["admin"]
    ann_id = await _make_announcement(db_pool)
    item = upload(client, admin, "announcement", ann_id, [make_image()]).json()["items"][0]
    assert client.get(item["url"]).status_code == 200

    res = client.delete(f"/api/announcements/{ann_id}", headers=auth(admin))
    assert res.status_code == 200, res.text

    # policy ตรวจ "ประกาศยังอยู่ไหม" ทุกครั้งที่เสิร์ฟ ⇒ รูปต้องหยุดทันที
    assert client.get(item["url"]).status_code == 404


# ============================================================
# 📅 กิจกรรม — ปกที่อัปเข้าเซิร์ฟเวอร์ (PR4)
# ============================================================
def _make_event(client, admin) -> int:
    """สร้างกิจกรรมผ่าน API (admin = is_admin ⇒ ผ่าน MANAGE_EVENTS) — เกิดเป็น 'draft' เสมอ"""
    res = client.post(
        "/api/events",
        json={
            "title": f"กิจกรรมมีรูป {random.randint(1, 10**9)}",
            "event_date": (datetime.now(timezone.utc) + timedelta(days=7)).isoformat(),
        },
        headers=auth(admin),
    )
    assert res.status_code == 201, res.text
    return res.json()["id"]


@pytest.mark.asyncio
async def test_event_cover_manage_then_public_after_publish(client, db_pool, media_world):
    admin = media_world["admin"]
    student = media_world["student"]
    event_id = _make_event(client, admin)

    item = upload(client, admin, "event", event_id, [make_image()]).json()["items"][0]

    # 1) หน้าจัดการเห็นรูปทั้งในลิสต์และในหน้ารายละเอียด
    listing = client.get("/api/events", headers=auth(admin))
    assert listing.status_code == 200, listing.text
    row = next(e for e in listing.json()["items"] if e["id"] == event_id)
    assert row["cover_image"]["thumb_url"] == item["thumb_url"]
    assert row["cover_image_url"] is None, "ลิงก์ภายนอกแบบเดิมต้องไม่ถูกแต่งขึ้นมา"

    detail = client.get(f"/api/events/{event_id}", headers=auth(admin))
    assert detail.status_code == 200, detail.text
    assert detail.json()["cover_image"]["id"] == item["id"]

    # 2) ยังเป็นฉบับร่าง ⇒ นักเรียนไม่เห็นกิจกรรม (และไม่เห็นรูปในลิสต์สาธารณะ)
    assert client.get(f"/api/events/public/{event_id}", headers=auth(student)).status_code == 404
    pub = client.get("/api/events/public", headers=auth(student), params={"scope": "all"})
    assert pub.status_code == 200, pub.text
    assert all(e["id"] != event_id for e in pub.json()["items"])

    # 3) เผยแพร่แล้ว ⇒ นักเรียนรู้เห็นรูปพร้อม signed URL ที่เสิร์ฟได้จริง
    #    (เบี่ยงจากแผนเดิมที่คิดว่า /events/public เป็น anon — จริง ๆ ต้องล็อกอิน
    #     ⇒ มี viewer ให้ผูกลายเซ็นเสมอ · ความปลอดภัยของร่างยังอยู่ที่ EventPolicy)
    pub_res = client.post(f"/api/events/{event_id}/publish", headers=auth(admin))
    assert pub_res.status_code == 200, pub_res.text

    pub2 = client.get("/api/events/public", headers=auth(student), params={"scope": "all"})
    assert pub2.status_code == 200, pub2.text
    srow = next(e for e in pub2.json()["items"] if e["id"] == event_id)
    assert srow["cover_image"]["thumb_url"]
    served = client.get(srow["cover_image"]["thumb_url"])
    assert served.status_code == 200
    assert served.headers["content-type"].startswith("image/")

    sdetail = client.get(f"/api/events/public/{event_id}", headers=auth(student))
    assert sdetail.status_code == 200, sdetail.text
    assert sdetail.json()["cover_image"]["id"] == item["id"]


@pytest.mark.asyncio
async def test_event_cover_stops_serving_after_event_deleted(client, db_pool, media_world):
    admin = media_world["admin"]
    event_id = _make_event(client, admin)
    item = upload(client, admin, "event", event_id, [make_image()]).json()["items"][0]
    assert client.get(item["url"]).status_code == 200

    res = client.delete(f"/api/events/{event_id}", headers=auth(admin))
    assert res.status_code == 200, res.text

    # policy ถาม "กิจกรรมยังอยู่ไหม" ทุกครั้งที่เสิร์ฟ ⇒ ถูกลบ = รูปหยุดทันที (แถวรูปยังอยู่)
    assert client.get(item["url"]).status_code == 404
    async with db_pool.acquire() as conn:
        alive = await conn.fetchval(
            "SELECT COUNT(*) FROM media_images "
            "WHERE owner_type = 'event' AND owner_id = $1 AND deleted_at IS NULL",
            event_id,
        )
    assert alive == 1, "รูปต้องยังไม่ถูกลบ — ที่หยุดเพราะ policy ของกิจกรรม ไม่ใช่เพราะแถวหาย"
