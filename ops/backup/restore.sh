#!/bin/bash
# =============================================================================
# restore.sh — ซ้อมกู้คืน (restore drill) บน scratch DB + scratch โฟลเดอร์
# =============================================================================
#
# ⚠️ **ไม่แตะ DB/volume จริง** — สร้าง DB ชั่วคราว `<db>_drill_<ts>` ใน Postgres
#    container เดียวกัน, แตก media ลง /tmp, ตรวจด้วย scripts/verify_media.py
#    แล้วลบ scratch ทิ้ง (เว้นแต่ --keep)
#
# ใช้:
#   ops/backup/restore.sh --dump ~/backups/prsc/production/db/db-production-20261125-023000.dump
#   ops/backup/restore.sh --dump … --media ~/backups/prsc/production/media/media-production-….tgz
#   ops/backup/restore.sh --dump … --env staging --keep --skip-verify
#
# exit: 0 = drill ผ่าน · 1 = restore/verify ล้ม · 2 = ใช้ผิด
# =============================================================================
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
REPO_DIR=$(cd "$SCRIPT_DIR/../.." && pwd)
cd "$REPO_DIR"

log() { printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"; }
die() { log "❌ $*"; exit 1; }
usage() {
    cat <<'EOF'
ใช้: ops/backup/restore.sh --dump <file.dump> [options]

  --dump <file>     dump ที่จะซ้อมกู้ (จำเป็น)
  --media <file>    media tarball ที่จะซ้อมกู้ (ถ้าไม่ใส่ จะตรวจได้แค่ว่าไฟล์ขาด)
  --env <name>      production | staging (ค่าเริ่มต้น: ENV_NAME ใน .env)
  --keep            เก็บ scratch DB และโฟลเดอร์ media ไว้หลังจบ
  --skip-verify     ไม่รัน verify_media.py (ตรวจแค่ว่า pg_restore ผ่าน)

⚠️ ไม่แตะ DB/volume จริง — สร้าง <db>_drill_<ts> แล้วลบเองเมื่อจบ
EOF
    exit 2
}

DUMP=""
MEDIA=""
ENV_ARG=""
KEEP=0
SKIP_VERIFY=0
while [ $# -gt 0 ]; do
    case "$1" in
        --dump) DUMP="${2:-}"; shift 2 ;;
        --media) MEDIA="${2:-}"; shift 2 ;;
        --env) ENV_ARG="${2:-}"; shift 2 ;;
        --keep) KEEP=1; shift ;;
        --skip-verify) SKIP_VERIFY=1; shift ;;
        -h|--help) usage ;;
        *) die "ไม่รู้จัก argument: $1" ;;
    esac
done
[ -n "$DUMP" ] || usage
[ -f "$DUMP" ] || die "ไม่พบ dump: $DUMP"
[ -z "$MEDIA" ] || [ -f "$MEDIA" ] || die "ไม่พบ media: $MEDIA"

[ -f .env ] || die "ไม่พบไฟล์ .env"
set -a
# shellcheck disable=SC1091
. ./.env
set +a
# --env ชนะค่าใน .env (ค่าใน .env ถูก source ทับไปแล้ว จึงต้องเก็บ argument ไว้ก่อน)
ENV_NAME="${ENV_ARG:-${ENV_NAME:-}}"
[ -n "$ENV_NAME" ] || die "ระบุ --env (เช่น --env staging) หรือตั้ง ENV_NAME ใน .env"
: "${POSTGRES_USER:?POSTGRES_USER ไม่มีใน .env}"
: "${POSTGRES_PASSWORD:?POSTGRES_PASSWORD ไม่มีใน .env}"
: "${POSTGRES_DB:?POSTGRES_DB ไม่มีใน .env}"

DB_CID=$(docker ps -q -f "name=^${ENV_NAME}_infra_db([.]|$)" | head -n1)
[ -n "$DB_CID" ] || die "ไม่พบ container ${ENV_NAME}_infra_db"

TS=$(date +%Y%m%d_%H%M%S)
SCRATCH_DB="${POSTGRES_DB}_drill_${TS}"
MEDIA_TMP=$(mktemp -d /tmp/prsc-restore-XXXXXX)

cleanup() {
    if [ "$KEEP" -eq 1 ]; then
        log "ℹ️ --keep: เก็บ $SCRATCH_DB และ $MEDIA_TMP ไว้ (ลบเองภายหลัง)"
        return
    fi
    log "🧹 ลบ scratch DB $SCRATCH_DB"
    docker exec -e PGPASSWORD="$POSTGRES_PASSWORD" "$DB_CID" \
        psql -U "$POSTGRES_USER" -d postgres -qAt \
        -c "DROP DATABASE IF EXISTS \"$SCRATCH_DB\"" > /dev/null 2>&1 || \
        log "⚠️ drop scratch DB ไม่สำเร็จ — ลบเองด้วย: DROP DATABASE $SCRATCH_DB;"
    rm -rf "$MEDIA_TMP"
}
trap cleanup EXIT

log "🟢 restore drill: $DUMP → $SCRATCH_DB"

# ---------- 1) สร้าง scratch DB ----------
docker exec -e PGPASSWORD="$POSTGRES_PASSWORD" "$DB_CID" \
    psql -U "$POSTGRES_USER" -d postgres -qAt \
    -c "CREATE DATABASE \"$SCRATCH_DB\"" > /dev/null || die "สร้าง scratch DB ไม่สำเร็จ"

# ---------- 2) pg_restore ----------
log "🐘 pg_restore…"
if ! docker exec -i -e PGPASSWORD="$POSTGRES_PASSWORD" "$DB_CID" \
        pg_restore -U "$POSTGRES_USER" -d "$SCRATCH_DB" \
        --no-owner --no-privileges --exit-on-error < "$DUMP"; then
    die "pg_restore ล้ม"
fi
log "✅ restore DB สำเร็จ"

# ---------- 3) media ----------
if [ -n "$MEDIA" ]; then
    log "🖼️ แตก media ลง $MEDIA_TMP…"
    # tar ของ host (Ubuntu GNU tar) อ่าน tarball ที่ alpine สร้างได้ — ใช้ฝั่ง host
    # เพราะต้องแตกไฟล์ลงโฟลเดอร์ชั่วคราวบน host เพื่อส่งเข้า container ตรวจทีหลัง
    rm -rf "$MEDIA_TMP"
    mkdir -p "$MEDIA_TMP"
    tar -C "$MEDIA_TMP" -xzf "$MEDIA" || die "แตก media ไม่สำเร็จ"
    log "✅ แตก media สำเร็จ ($(du -sh "$MEDIA_TMP" | cut -f1))"
else
    log "⚠️ ไม่ได้ระบุ --media — จะตรวจได้แค่ว่าแถว DB ชี้ไฟล์ที่ขาด"
fi

# ---------- 4) verify_media.py ----------
if [ "$SKIP_VERIFY" -eq 1 ]; then
    log "⚠️ --skip-verify: ข้ามการตรวจ sha256"
    exit 0
fi

BACKEND_IMAGE=$(docker ps -q -f "name=^${ENV_NAME}_backend([.]|$)" | head -n1 | xargs -r docker inspect -f '{{.Config.Image}}')
if [ -z "$BACKEND_IMAGE" ]; then
    log "❌ ไม่พบ backend container ที่รันอยู่ของ $ENV_NAME — ตรวจด้วยมือหรือใช้ --skip-verify"
    exit 1
fi
NETWORK="app-internal-${ENV_NAME}"
docker network inspect "$NETWORK" > /dev/null 2>&1 || NETWORK="bridge"

log "🔍 verify_media.py ด้วย image $BACKEND_IMAGE (network $NETWORK)"
if ! docker run --rm --network "$NETWORK" \
        -e "DATABASE_URL=postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@${ENV_NAME}_infra_db:5432/${SCRATCH_DB}" \
        -e MEDIA_STORAGE_DIR=/data/media \
        -v "$MEDIA_TMP":/data/media:ro \
        "$BACKEND_IMAGE" python scripts/verify_media.py; then
    die "verify_media.py พบความไม่สอดคล้อง"
fi

log "🟢 restore drill ผ่าน"
