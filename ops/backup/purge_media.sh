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

ENV_NAME="${1:-${ENV_NAME:-}}"
[ -n "$ENV_NAME" ] || die "ต้องระบุ env เช่น: purge_media.sh production --apply"
shift || true
: "${POSTGRES_USER:?POSTGRES_USER ไม่มีใน .env}"
: "${POSTGRES_PASSWORD:?POSTGRES_PASSWORD ไม่มีใน .env}"
: "${POSTGRES_DB:?POSTGRES_DB ไม่มีใน .env}"

BACKEND_CID=$(docker ps -q -f "name=^${ENV_NAME}_backend([.]|$)" | head -n1)
[ -n "$BACKEND_CID" ] || die "ไม่พบ backend container ที่รันอยู่ของ $ENV_NAME"
BACKEND_IMAGE=$(docker inspect -f '{{.Config.Image}}' "$BACKEND_CID")

NETWORK="app-internal-${ENV_NAME}"
docker network inspect "$NETWORK" > /dev/null 2>&1 || NETWORK="bridge"

log "🧹 purge_media $ENV_NAME ด้วย image $BACKEND_IMAGE"
exec docker run --rm --network "$NETWORK" \
    -e "DATABASE_URL=postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@${ENV_NAME}_infra_db:5432/${POSTGRES_DB}" \
    -e MEDIA_STORAGE_DIR=/data/media \
    -v "${ENV_NAME}_media_data":/data/media \
    "$BACKEND_IMAGE" python scripts/purge_media.py "$@"
