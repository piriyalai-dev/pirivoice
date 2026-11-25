"""
verify_media — ตรวจว่ารูปบนดิสก์ตรงกับแถวใน `issue_images`
============================================================
ใช้ตอน restore drill และใช้ตรวจสุขภาพประจำ (อ่านอย่างเดียว ไม่แก้ข้อมูล)

ตรวจอะไร:
- แถวที่ `storage_path` / `thumb_path` ไม่ผ่าน pattern (ถูกแก้มือ / path traversal)
- ไฟล์เต็ม/thumbnail ที่ **หายไปจากดิสก์** แต่ DB ยังอ้างอยู่
- sha256 ของไฟล์ **ไม่ตรง** กับที่บันทึกไว้ (ไฟล์เสีย/ถูกเขียนทับ)
- ไฟล์ในโฟลเดอร์ `issues/` ที่ **ไม่มีแถวใดอ้างถึง** (orphan — crash ระหว่าง upload)

⚠️ นับแถวที่ soft-delete ด้วย เพราะไฟล์ยังถูกเก็บไว้จนกว่า `purge_media.py` จะลบ
   (ถ้าไม่นับ ไฟล์ของแถวที่ลบจะกลายเป็น orphan หลอก)

รัน:
    DATABASE_URL=... MEDIA_STORAGE_DIR=... python scripts/verify_media.py
    ... python scripts/verify_media.py --root /tmp/restore --skip-hash --json

exit: 0 = ตรงกันทั้งหมด · 1 = พบ drift · 2 = ใช้ผิด/เชื่อมต่อไม่ได้
"""
import argparse
import asyncio
import hashlib
import json
import os
import sys
from collections import Counter

import asyncpg

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from core.media.base import MediaStorageError  # noqa: E402
from core.media.local import LocalMediaStorage  # noqa: E402

READ_CHUNK = 1024 * 1024


def _hash_sync(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(READ_CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


async def _hash_file(path) -> str:
    return await asyncio.to_thread(_hash_sync, path)


async def _check_row(row, storage: LocalMediaStorage, skip_hash: bool, sem: asyncio.Semaphore) -> dict:
    """ตรวจแถวเดียว → dict ของปัญหา (คีย์ว่าง = ผ่าน)"""
    problems: dict[str, str] = {}
    keys = {"full": row["storage_path"], "thumb": row["thumb_path"]}
    expected = {"full": row["sha256"], "thumb": row["thumb_sha256"]}

    for variant, key in keys.items():
        if not key:
            if variant == "full":
                problems["invalid_full"] = "storage_path ว่าง"
            continue
        try:
            path = storage.local_path(key)
        except MediaStorageError as e:
            problems[f"invalid_{variant}"] = f"{key} — {e}"
            continue
        assert path is not None  # local backend เท่านั้น
        if not await asyncio.to_thread(path.is_file):
            problems[f"missing_{variant}"] = key
            continue
        if skip_hash or not expected[variant]:
            continue
        async with sem:
            actual = await _hash_file(path)
        if actual != expected[variant]:
            problems[f"mismatch_{variant}"] = f"{key} (DB {expected[variant][:12]}… ≠ disk {actual[:12]}…)"

    if problems:
        problems["_id"] = str(row["id"])
        problems["_issue_id"] = str(row["issue_id"])
        problems["_deleted"] = "yes" if row["deleted_at"] else "no"
    return problems


def _scan_disk(storage: LocalMediaStorage) -> set[str]:
    """relative path ของทุกไฟล์ใต้ issues/ (posix)"""
    issues_dir = storage.root / "issues"
    found: set[str] = set()
    if not issues_dir.is_dir():
        return found
    for dirpath, _dirnames, filenames in os.walk(issues_dir):
        for name in filenames:
            full = os.path.join(dirpath, name)
            found.add(os.path.relpath(full, storage.root).replace(os.sep, "/"))
    return found


async def main() -> int:
    ap = argparse.ArgumentParser(description="ตรวจความสอดคล้องของรูป issue_images กับดิสก์")
    ap.add_argument("--database-url", default=os.environ.get("DATABASE_URL"))
    ap.add_argument("--root", default=os.environ.get("MEDIA_STORAGE_DIR"))
    ap.add_argument("--skip-hash", action="store_true", help="ไม่คำนวณ sha256 (เร็ว — ตรวจแค่ว่าไฟล์มีอยู่)")
    ap.add_argument("--concurrency", type=int, default=8)
    ap.add_argument("--max-report", type=int, default=50, help="แสดงปัญหาได้กี่บรรทัดต่อหมวด (0 = ทั้งหมด)")
    ap.add_argument("--json", action="store_true", help="คืนผลเป็น JSON")
    args = ap.parse_args()

    if not args.database_url:
        print("❌ ต้องระบุ --database-url หรือตั้ง DATABASE_URL", file=sys.stderr)
        return 2
    if not args.root:
        print("❌ ต้องระบุ --root หรือตั้ง MEDIA_STORAGE_DIR", file=sys.stderr)
        return 2
    if not os.path.isdir(args.root):
        print(f"❌ ไม่พบโฟลเดอร์ media: {args.root}", file=sys.stderr)
        return 2

    storage = LocalMediaStorage(args.root)
    sem = asyncio.Semaphore(max(1, args.concurrency))

    try:
        pool = await asyncpg.create_pool(args.database_url, min_size=1, max_size=4)
    except Exception as e:  # noqa: BLE001 — แสดงสาเหตุจริงให้คนซ้อม restore เห็น
        print(f"❌ เชื่อมต่อ DB ไม่ได้: {e}", file=sys.stderr)
        return 2

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, issue_id, storage_path, thumb_path, sha256, thumb_sha256, deleted_at
            FROM issue_images
            ORDER BY created_at
            """
        )

    results = await asyncio.gather(*(_check_row(r, storage, args.skip_hash, sem) for r in rows))
    problems = [p for p in results if p]

    referenced: set[str] = set()
    for r in rows:
        if r["storage_path"]:
            referenced.add(r["storage_path"])
        if r["thumb_path"]:
            referenced.add(r["thumb_path"])
    on_disk = await asyncio.to_thread(_scan_disk, storage)
    orphans = sorted(on_disk - referenced)

    counts = Counter()
    for p in problems:
        for key in p:
            if not key.startswith("_"):
                counts[key] += 1

    soft_deleted = sum(1 for r in rows if r["deleted_at"])
    drift = bool(problems or orphans)

    if args.json:
        print(json.dumps({
            "root": args.root,
            "rows": len(rows),
            "soft_deleted_rows": soft_deleted,
            "problems": problems,
            "counts": dict(counts),
            "orphan_count": len(orphans),
            "orphans": orphans,
            "ok": not drift,
        }, ensure_ascii=False, indent=2))
    else:
        print(f"🖼️ ตรวจ media root: {args.root}")
        print(f"   แถวทั้งหมด {len(rows)} (soft-deleted {soft_deleted}) · ไฟล์บนดิสก์ {len(on_disk)}")
        if not drift:
            print("🟢 ตรงกันทั้งหมด — ไม่มีไฟล์ขาด/เสีย/orphan")
        else:
            def show(title: str, items: list[str]) -> None:
                if not items:
                    return
                print(f"\n❌ {title}: {len(items)}")
                limit = len(items) if args.max_report == 0 else min(len(items), args.max_report)
                for line in items[:limit]:
                    print(f"   - {line}")
                if limit < len(items):
                    print(f"   … อีก {len(items) - limit} รายการ (ใช้ --max-report 0 เพื่อดูทั้งหมด)")

            def lines_for(kind: str) -> list[str]:
                return [
                    f"image {p['_id']} (issue {p['_issue_id']}, deleted={p['_deleted']}): {p[kind]}"
                    for p in problems
                    if kind in p
                ]

            show("key ไม่ถูกต้อง (full)", lines_for("invalid_full"))
            show("key ไม่ถูกต้อง (thumb)", lines_for("invalid_thumb"))
            show("ไฟล์เต็มหายจากดิสก์", lines_for("missing_full"))
            show("thumbnail หายจากดิสก์", lines_for("missing_thumb"))
            show("sha256 ไม่ตรง (full)", lines_for("mismatch_full"))
            show("sha256 ไม่ตรง (thumb)", lines_for("mismatch_thumb"))
            show("ไฟล์ orphan (ไม่มีแถวอ้างถึง)", orphans)
            print("\n🔴 พบ drift — อย่าลบแถว DB อัตโนมัติ; ตรวจว่ากู้ dump/media ครบชุดหรือไม่")

        if args.skip_hash:
            print("ℹ️ --skip-hash: ไม่ได้ตรวจ sha256 ของไฟล์ (ตรวจแค่ว่ามีอยู่)")

    await pool.close()
    return 1 if drift else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
