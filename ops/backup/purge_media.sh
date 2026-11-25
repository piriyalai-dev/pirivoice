#!/bin/bash
# =============================================================================
# purge_media.sh — wrapper ให้ cron เรียก purge_media.py บน backend image
# =============================================================================
#
# ใช้:
#   ops/backup/purge_media.sh production            # dry-run
#   ops/backup/purge_media.sh production --apply    # ลบจริง (cron ใช้ตัวนี้)
#
# ทำไมต้องเป็น wrapper: purge ต้องเห็นทั้ง DB (DATABASE_URL) และ media volume
# ⇒ รันใน one-off container ของ backend image บน network เดียวกับ infra
# =============================================================================
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
REPO_DIR=$(cd "$SCRIPT_DIR/../.." && pwd)
cd "$REPO_DIR"

log() { printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"; }
die() { log "❌ $*"; exit 1; }

[ -f .env ] || die "ไม่พบไฟล์ .env ที่ $REPO_DIR"
set -a
# shellcheck disable=SC1091
. ./.env
set +a

# อ่าน ENV_NAME จาก .env เป็นค่าเริ่มต้น (เหมือน backup.sh) — รับ positional แรก
# เฉพาะเมื่อ argument แรกไม่ใช่ flag; `purge_media.sh --apply` ต้องไม่เอา --apply ไปเป็นชื่อ env
ENV_NAME="${ENV_NAME:-}"
if [ $# -gt 0 ] && [ "${1#-}" = "$1" ]; then
    ENV_NAME="$1"; shift
fi
[ -n "$ENV_NAME" ] || die "ไม่พบ ENV_NAME ใน .env (หรือระบุ: purge_media.sh <env> [--apply])"
: "${POSTGRES_USER:?POSTGRES_USER ไม่มีใน .env}"
: "${POSTGRES_PASSWORD:?POSTGRES_PASSWORD ไม่มีใน .env}"
: "${POSTGRES_DB:?POSTGRES_DB ไม่มีใน .env}"

# ⚠️ ชื่อจริงของ service คือ <ENV>_app_backend (ไม่ใช่ <ENV>_backend)
BACKEND_CID=$(docker ps -q -f "name=^${ENV_NAME}_app_backend([.]|$)" | head -n1)
[ -n "$BACKEND_CID" ] || die "ไม่พบ backend container ที่รันอยู่ของ $ENV_NAME"
BACKEND_IMAGE=$(docker inspect -f '{{.Config.Image}}' "$BACKEND_CID")

log "🧹 purge_media $ENV_NAME ด้วย image $BACKEND_IMAGE"
# overlay ของ Swarm ไม่ใช่ manually attachable ⇒ ใช้ netns ของ backend (เหมือน restore.sh)
# purge_media.py import core.config ⇒ ต้องส่ง secret จาก .env ไปด้วย
exec docker run --rm --network container:"$BACKEND_CID" \
    -e "DATABASE_URL=postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@${ENV_NAME}_infra_db:5432/${POSTGRES_DB}" \
    -e MEDIA_STORAGE_DIR=/data/media \
    -e "API_KEY=${API_KEY:-}" \
    -e "SECRET_KEY=${SECRET_KEY:-}" \
    -e "JWT_SECRET=${JWT_SECRET:-}" \
    -v "${ENV_NAME}_media_data":/data/media \
    "$BACKEND_IMAGE" python scripts/purge_media.py "$@"
