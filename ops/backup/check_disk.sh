#!/bin/bash
# =============================================================================
# check_disk.sh — เฝ้าดิสก์และสุขภาพของ backup (รันรายชั่วโมงผ่าน cron)
# =============================================================================
#
# ตรวจ:
#   1. % การใช้ดิสก์ของทุก mount ที่กำหนด (default: /)
#   2. อายุ backup ล่าสุดของแต่ละ env — เตือนถ้าเก่ากว่าที่ควร
#   3. ขนาดโฟลเดอร์ backup + docker system df
#   4. rclone about (ถ้ามี config) — ดู quota ก่อน Drive เต็ม
#
# ใช้:
#   ops/backup/check_disk.sh
#   CHECK_PATHS="/ /var" ops/backup/check_disk.sh
#
# env ที่ปรับได้:
#   CHECK_PATHS="/"               · path ที่ตรวจ (คั่นด้วยช่องว่าง)
#   DISK_WARN_PCT=80 · DISK_CRIT_PCT=90
#   BACKUP_ROOT=$HOME/backups/prsc
#   BACKUP_ENVS=""                     · env ที่ต้องมี backup สด (ว่าง = ค้นหาเองจากโฟลเดอร์)
#   BACKUP_MAX_AGE_HOURS=30           · เตือนถ้า dump ล่าสุดเก่ากว่านี้
#   RCLONE_CONFIG=... · RCLONE_IMAGE=... (เหมือน backup.sh)
#
# exit: 0 = ปกติ/เตือน · 1 = วิกฤต (ดิสก์ ≥ CRIT หรือ backup ขาดเกินกำหนด)
# =============================================================================
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
REPO_DIR=$(cd "$SCRIPT_DIR/../.." && pwd)

log() { printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"; }

CHECK_PATHS="${CHECK_PATHS:-/}"
DISK_WARN_PCT="${DISK_WARN_PCT:-80}"
DISK_CRIT_PCT="${DISK_CRIT_PCT:-90}"
BACKUP_ROOT="${BACKUP_ROOT:-$HOME/backups/prsc}"
BACKUP_ENVS="${BACKUP_ENVS:-}"   # ว่าง = ค้นหา env ที่มีโฟลเดอร์ db ใต้ BACKUP_ROOT เอง
BACKUP_MAX_AGE_HOURS="${BACKUP_MAX_AGE_HOURS:-30}"
RCLONE_CONFIG="${RCLONE_CONFIG:-$HOME/.config/rclone/rclone.conf}"
RCLONE_IMAGE="${RCLONE_IMAGE:-rclone/rclone:1.68.1}"
RCLONE_REMOTE="${RCLONE_REMOTE:-gdrive}"

ALERTS=0
CRITICAL=0

# ---------- 1) ดิสก์ ----------
for path in $CHECK_PATHS; do
    [ -d "$path" ] || { log "ALERT path '$path' ไม่มีอยู่"; ALERTS=$((ALERTS + 1)); continue; }
    read -r used_pct avail < <(df -P "$path" | awk 'NR==2 {gsub("%","",$5); print $5, $4}')
    line="💽 $path ใช้ ${used_pct}% (เหลือ $((avail / 1024 / 1024)) GB)"
    if [ "$used_pct" -ge "$DISK_CRIT_PCT" ]; then
        log "ALERT CRITICAL $line (เกณฑ์ ${DISK_CRIT_PCT}%) — ลบ backup เก่า/รูปที่ purge ได้ทันที"
        CRITICAL=$((CRITICAL + 1))
    elif [ "$used_pct" -ge "$DISK_WARN_PCT" ]; then
        log "ALERT WARN $line (เกณฑ์ ${DISK_WARN_PCT}%)"
        ALERTS=$((ALERTS + 1))
    else
        log "OK $line"
    fi
done

# ---------- 2) อายุ backup ล่าสุด ----------
# ไม่ระบุ BACKUP_ENVS ⇒ ใช้ชื่อโฟลเดอร์ที่มี db/ อยู่จริง (กันพิมพ์ชื่อ env ผิดจาก .env)
if [ -z "$BACKUP_ENVS" ] && [ -d "$BACKUP_ROOT" ]; then
    BACKUP_ENVS=$(find "$BACKUP_ROOT" -mindepth 2 -maxdepth 2 -type d -name db -printf '%h\n' \
        | xargs -r -n1 basename | sort -u | tr '\n' ' ')
fi
[ -n "$BACKUP_ENVS" ] || log "ℹ️ ยังไม่มี backup ของ env ใดใต้ $BACKUP_ROOT"

for env in $BACKUP_ENVS; do
    dir="$BACKUP_ROOT/$env/db"
    latest=$(find "$dir" -maxdepth 1 -type f -name '*.dump' -printf '%T@ %p\n' 2>/dev/null \
        | sort -nr | head -n1 | cut -d' ' -f2-)
    if [ -z "$latest" ]; then
        # env ที่ยังไม่เคยติดตั้ง/ยังไม่เปิดใช้ ไม่ควรทำให้ทั้งเครื่องขึ้นวิกฤต
        log "ALERT WARN ไม่พบ backup ของ '$env' ใน $dir"
        ALERTS=$((ALERTS + 1))
        continue
    fi
    age_h=$(( ( $(date +%s) - $(stat -c %Y "$latest") ) / 3600 ))
    if [ "$age_h" -gt "$BACKUP_MAX_AGE_HOURS" ]; then
        log "ALERT CRITICAL backup '$env' เก่า ${age_h} ชม. (> ${BACKUP_MAX_AGE_HOURS}) — $(basename "$latest")"
        CRITICAL=$((CRITICAL + 1))
    else
        log "OK backup '$env' ล่าสุด ${age_h} ชม.ก่อน — $(basename "$latest")"
    fi
done

# ---------- 3) พื้นที่ที่ backup + docker ใช้ ----------
if [ -d "$BACKUP_ROOT" ]; then
    log "📦 ขนาด backup: $(du -sh "$BACKUP_ROOT" | cut -f1) → $BACKUP_ROOT"
    du -sh "$BACKUP_ROOT"/* 2>/dev/null | sed 's/^/    /' || true
fi
log "🐳 docker system df:"
docker system df 2>/dev/null | sed 's/^/    /' || log "ALERT WARN อ่าน docker system df ไม่ได้"

# ---------- 4) rclone quota ----------
if [ -f "$RCLONE_CONFIG" ]; then
    # เหมือน backup.sh: mount โฟลเดอร์ config แบบ rw + รันด้วย uid ของเจ้าของ
    # (rclone refresh token ระหว่างเรียก API แล้วเขียน rclone.conf กลับ)
    if about=$(timeout 60 docker run --rm \
            --user "$(id -u):$(id -g)" \
            -v "$(dirname "$RCLONE_CONFIG")":/config/rclone \
            -e RCLONE_CONFIG=/config/rclone/rclone.conf \
            -e HOME=/tmp \
            "$RCLONE_IMAGE" about "$RCLONE_REMOTE": 2>&1); then
        log "☁️ rclone about $RCLONE_REMOTE:"
        printf '%s\n' "$about" | sed 's/^/    /'
    else
        log "ALERT WARN rclone about ล้ม — ตรวจ config/เน็ต/OAuth"
        ALERTS=$((ALERTS + 1))
    fi
else
    log "⚠️ ยังไม่มี rclone config ($RCLONE_CONFIG) — ข้ามการตรวจ offsite"
fi

if [ "$CRITICAL" -gt 0 ]; then
    log "🔴 สรุป: วิกฤต $CRITICAL · เตือน $ALERTS"
    exit 1
fi
log "🟢 สรุป: เตือน $ALERTS · ไม่มีวิกฤต"
exit 0
