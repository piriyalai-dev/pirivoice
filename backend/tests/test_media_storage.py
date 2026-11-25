"""🗄️ LocalMediaStorage — write/read/delete, atomicity, key containment"""
import hashlib
import os
import uuid
from pathlib import Path

import pytest

from core.media import LocalMediaStorage, MediaStorageError


@pytest.fixture
def storage(tmp_path):
    return LocalMediaStorage(str(tmp_path / "media"))


def _key(issue_id=7):
    return f"issues/{issue_id}/{uuid.uuid4()}.webp"


@pytest.mark.asyncio
async def test_write_read_roundtrip(storage):
    key = _key()
    data = b"RIFF-webp-payload" + os.urandom(4096)
    await storage.write(key, data)
    assert await storage.exists(key)

    chunks = []
    async for c in storage.read_stream(key):
        chunks.append(c)
    got = b"".join(chunks)
    assert got == data
    assert hashlib.sha256(got).digest() == hashlib.sha256(data).digest()

    path = storage.local_path(key)
    assert path is not None and path.is_file()


@pytest.mark.asyncio
async def test_delete_is_idempotent(storage):
    key = _key()
    await storage.write(key, b"x")
    await storage.delete(key)
    await storage.delete(key)  # ไม่มีไฟล์แล้วต้องไม่ error
    assert not await storage.exists(key)


@pytest.mark.asyncio
async def test_atomic_write_leaves_no_partial_file(storage, monkeypatch):
    """ถ้า os.replace ล้ม ต้องไม่เหลือไฟล์ที่ final path และไม่เหลือ .part"""
    key = _key()

    def boom(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr("core.media.local.os.replace", boom)
    with pytest.raises(MediaStorageError):
        await storage.write(key, b"data")

    assert not await storage.exists(key)
    parts = list(storage.tmp_dir.glob("*.part"))
    assert parts == []


@pytest.mark.asyncio
async def test_overwrite_is_atomic_replace(storage):
    key = _key()
    await storage.write(key, b"first")
    await storage.write(key, b"second")
    chunks = []
    async for c in storage.read_stream(key):
        chunks.append(c)
    assert b"".join(chunks) == b"second"


@pytest.mark.parametrize(
    "key",
    [
        "../../etc/passwd",
        "/etc/passwd",
        "issues/7/not-a-uuid.webp",
        "issues/7/..%2f..%2fetc.webp",
        "issues/x/" + "a" * 36 + ".webp",
        "issues/7/" + "a" * 36 + ".jpg",
        "tmp/evil.webp",
        "",
    ],
)
@pytest.mark.asyncio
async def test_invalid_keys_rejected(storage, key):
    with pytest.raises(MediaStorageError):
        await storage.write(key, b"x")
    with pytest.raises(MediaStorageError):
        storage.local_path(key)


@pytest.mark.asyncio
async def test_symlink_escape_rejected(tmp_path):
    """`issues/` ที่เป็น symlink ออกนอก root ต้องถูกปฏิเสธ (containment หลัง resolve)"""
    root = tmp_path / "media"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (root / "issues").symlink_to(outside, target_is_directory=True)

    s = LocalMediaStorage(str(root))
    key = _key()
    with pytest.raises(MediaStorageError):
        await s.write(key, b"x")
    assert list(outside.rglob("*.webp")) == []


@pytest.mark.asyncio
async def test_missing_file_read_raises(storage):
    with pytest.raises(MediaStorageError):
        async for _ in storage.read_stream(_key()):
            pass
