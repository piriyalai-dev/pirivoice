# ops/backup — สำรองข้อมูลและซ้อมกู้คืน (PRSC Portal)

ชุดสคริปต์นี้อยู่ **ใน repo** เพื่อให้ย้ายเครื่องแล้วติดตั้งใหม่ได้ทันที
ไม่ต้อง sudo — ใช้เฉพาะ `docker` (user อยู่ใน group `docker`)

| ไฟล์ | ใช้ทำอะไร | รันเมื่อไหร่ |
|---|---|---|
| `backup.sh` | pg_dump → media tar → retention → offsite (rclone) | cron วันละครั้ง |
| `check_disk.sh` | ดิสก์ 80/90% · อายุ backup · docker df · rclone quota | cron ทุกชั่วโมง |
| `restore.sh --dump …` | **ซ้อมกู้** บน scratch DB + scratch media (ไม่แตะของจริง) | ก่อนขึ้น production / เดือนละครั้ง |
| `purge_media.sh [--apply]` | ลบรูปที่ soft-delete เกิน 30 วัน + ไฟล์ orphan | cron วันละครั้ง (ใช้ `--apply`) |
| `../../backend/scripts/verify_media.py` | เทียบ sha256 ของไฟล์กับ DB | เรียกผ่าน `restore.sh` หรือรันมือ |

## ลำดับที่สำคัญ

1. **pg_dump ก่อน media เสมอ** — ไฟล์รูปถูกเขียนแบบ atomic และแถว DB ถูก INSERT
   หลังไฟล์อยู่ครบ ⇒ dump ที่ถ่ายก่อน tar ไม่มีทางอ้างรูปที่ "ยังไม่เกิด"
2. **offsite ไม่มี config = WARN + exit 0** — local backup ต้องไม่ล้มเพราะ rclone
   ยังไม่พร้อม · แต่ถ้ามี config แล้วอัปโหลดล้ม → exit 3 (cron เห็นว่าผิด)

## 1) ติดตั้ง cron (ไม่ต้อง sudo)

รัน `crontab -e` ด้วย user ที่มี docker group (เช่น `prscportal`) แล้วเพิ่ม:

```cron
# PRSC Portal — backup production (02:30) / staging (อาทิตย์ 04:00)
# ⚠️ ไม่ต้องใส่ชื่อ env: สคริปต์อ่าน ENV_NAME จาก .env ของ checkout นั้นเอง
#    (พิมพ์ชื่อผิด เช่น "staging" ทั้งที่ .env เป็น "pirivoice_staging" → หา container ไม่เจอ)
30 2 * * * /home/prscportal/prsc_portal/piri_voice/ops/backup/backup.sh >> /home/prscportal/backups/backup.log 2>&1
0 4 * * 0  /home/prscportal/prsc_portal/prsc_test/ops/backup/backup.sh >> /home/prscportal/backups/backup-staging.log 2>&1
# เฝ้าดิสก์ทุกชั่วโมง (:15)
15 * * * * /home/prscportal/prsc_portal/piri_voice/ops/backup/check_disk.sh >> /home/prscportal/backups/disk.log 2>&1
# purge รูปที่ลบเกิน 30 วัน + orphan (05:00)
0 5 * * *  /home/prscportal/prsc_portal/piri_voice/ops/backup/purge_media.sh --apply >> /home/prscportal/backups/purge.log 2>&1
```

> ⚠️ cron มี PATH แคบ — สคริปต์เรียก `docker`, `find`, `tar`, `flock` จาก `/usr/bin`
> ทั้งหมด ถ้าย้าย path ของ repo ต้องแก้ cron ตาม (ดู `~/CLAUDE.md` เรื่อง symlink)

## 2) Offsite Google Drive ด้วย rclone (owner ทำครั้งเดียว)

**ขั้นที่ 1 — บนเครื่องของคุณเอง (ที่มีเบราว์เซอร์)**

```bash
rclone config
#   n) New remote
#   name> gdrive
#   Storage> drive
#   client_id> (เว้นว่าง)
#   client_secret> (เว้นว่าง)
#   scope> 1
#   root_folder_id> (เว้นว่าง)
#   service_account_file> (เว้นว่าง)
#   Edit advanced config?> n
#   Use web browser to automatically authenticate?> y
#   → เบราว์เซอร์เปิด ให้ login Google แล้วกด Allow
#   Configure this as a Shared Drive?> n
#   y) Yes this is OK
```

ตรวจฝั่งเครื่องตัวเองก่อน:

```bash
rclone lsd gdrive:
rclone about gdrive:          # ดู quota — Media+DB ต้องพอ
```

**ขั้นที่ 2 — คัดลอก config ขึ้นเซิร์ฟเวอร์**

```bash
# สร้างโฟลเดอร์บนเซิร์ฟเวอร์ (ครั้งแรกครั้งเดียว)
ssh prscportal@pirivoice-prod 'mkdir -p ~/.config/rclone && chmod 700 ~/.config/rclone'

# ส่ง config (⚠️ มี token — อย่า commit, อย่าแปะในแชต)
scp ~/.config/rclone/rclone.conf \
    prscportal@pirivoice-prod:/home/prscportal/.config/rclone/rclone.conf

ssh prscportal@pirivoice-prod 'chmod 600 ~/.config/rclone/rclone.conf'
```

**ขั้นที่ 3 — ทดสอบผ่าน Docker (ภาพเดียวกับที่ backup.sh ใช้)**

> ⚠️ mount **โฟลเดอร์** `~/.config/rclone` แบบ read-write (ห้ามใส่ `:ro`)
> และรันด้วย `--user "$(id -u):$(id -g)"` — rclone ต้อง refresh OAuth token แล้วเขียน
> `rclone.conf` กลับ ถ้า mount แบบ ro จะ refresh ไม่ได้และไฟล์อาจกลายเป็นของ root

```bash
ssh prscportal@pirivoice-prod
docker run --rm --user "$(id -u):$(id -g)" \
  -v ~/.config/rclone:/config/rclone \
  -e RCLONE_CONFIG=/config/rclone/rclone.conf \
  -e HOME=/tmp \
  rclone/rclone:1.68.1 lsd gdrive:

# สร้างโฟลเดอร์ปลายทาง + ทดสอบเขียน
docker run --rm --user "$(id -u):$(id -g)" \
  -v ~/.config/rclone:/config/rclone \
  -e RCLONE_CONFIG=/config/rclone/rclone.conf \
  -e HOME=/tmp \
  rclone/rclone:1.68.1 mkdir gdrive:PIRIvoiceBackup

docker run --rm --user "$(id -u):$(id -g)" \
  -v ~/.config/rclone:/config/rclone \
  -e RCLONE_CONFIG=/config/rclone/rclone.conf \
  -e HOME=/tmp \
  rclone/rclone:1.68.1 lsd gdrive:PIRIvoiceBackup
```

**ขั้นที่ 4 — รัน backup มือหนึ่งรอบ**

```bash
cd /home/prscportal/prsc_portal/piri_voice
./ops/backup/backup.sh          # อ่าน ENV_NAME จาก .env ของ checkout นี้
tail -n 30 ~/backups/backup.log # หรือดู log ที่ cron ใช้
```

> หมายเหตุการตัดสินใจ: ใช้ `rclone copy` **ไม่ใช่ `sync`** และ **ยังไม่ลบไฟล์เก่าฝั่ง
> Google Drive** ในเฟสนี้ (กันลบผิดตอน config ยังใหม่) → ต้องดู `rclone about` เป็นระยะ
> ถ้า quota ใกล้เต็ม ให้คุยก่อนว่าจะเพิ่ม retention ฝั่ง remote อย่างไร

## 3) ซ้อมกู้คืน (restore drill)

```bash
cd /home/prscportal/prsc_portal/prsc_test        # staging checkout

# ซ้อมกู้จาก dump ล่าสุด + media ล่าสุด (env อ่านจาก .env; BACKUP_ROOT คือ ~/backups/prsc)
ENV_NAME=$(grep -E '^ENV_NAME=' .env | cut -d= -f2-)
./ops/backup/restore.sh \
  --dump  "$(ls -t ~/backups/prsc/$ENV_NAME/db/*.dump | head -1)" \
  --media "$(ls -t ~/backups/prsc/$ENV_NAME/media/*.tgz | head -1)"
```

สิ่งที่สคริปต์ทำ:

1. สร้าง DB ชั่วคราว `<db>_drill_<timestamp>` ใน Postgres container เดียวกัน
2. `pg_restore --exit-on-error`
3. แตก media ลง `/tmp/prsc-restore-*`
4. รัน `verify_media.py` ใน container ของ backend image (อ่าน DB scratch + media ที่แตก)
5. ลบ scratch ทั้งหมด (เว้นแต่ `--keep`)

**ผ่าน** = `🟢 ตรงกันทั้งหมด — ไม่มีไฟล์ขาด/เสีย/orphan` และ exit 0
**ไม่ผ่าน** = รายการไฟล์ที่ขาด/sha256 ไม่ตรง/orphan + exit 1 — **อย่าลบแถว DB อัตโนมัติ**
ให้ตรวจก่อนว่ากู้ dump กับ media มาจากเวลาเดียวกันหรือไม่

## 4) ตรวจสุขภาพประจำ

```bash
./ops/backup/check_disk.sh                  # 0 = ปกติ/เตือน · 1 = วิกฤต
CHECK_PATHS="/" BACKUP_ENVS="production" ./ops/backup/check_disk.sh
```

- `ALERT WARN` = 80% / backup เก่า / ไม่พบ backup ของ env นั้น
- `ALERT CRITICAL` = 90% หรือ dump ล่าสุดเก่ากว่า `BACKUP_MAX_AGE_HOURS` (default 30)

## 5) purge (ลบจริง)

```bash
./ops/backup/purge_media.sh             # dry-run — แสดงสิ่งที่จะลบ
./ops/backup/purge_media.sh --apply     # ลบจริง (นี่คือที่ cron เรียก)
```

- แถวที่ `deleted_at` เกิน `MEDIA_PURGE_AFTER_DAYS` (default 30) → ลบแถว **ก่อน** แล้วลบไฟล์
- ไฟล์ orphan ที่เก่ากว่า `--orphan-age-hours` (default 24) → ลบ (กันชนกับ upload ที่ยังไม่ commit)

## 6) สิ่งที่ backup **ไม่รวม**

- ไฟล์ `.env` (มีความลับ) — สำรองด้วยวิธีอื่นที่ปลอดภัย
- Docker images / build cache — สร้างใหม่ได้จาก `pull_all.sh`
- ไฟล์ใน `media/tmp/` — ไฟล์ชั่วคราวระหว่างประมวลผล (`--exclude=./tmp`)
