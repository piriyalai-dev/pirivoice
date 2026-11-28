# HANDOFF — งานคู่มือ PIRIvoice (.odt) + แคปหน้าจอ

> อัปเดต: 27 พ.ย. 2026 · ใช้ต่อในแชทใหม่ได้ทันที

## 1. สถานะปัจจุบัน

| รายการ | สถานะ |
|---|---|
| สคริปต์สร้างเล่ม | ✅ `reports/build_odt.py` (ODF ตรงด้วย lxml+zipfile+Pillow) |
| อัปเดตสารบัญ + PDF | ✅ `reports/odt_update_indexes.py` (UNO) |
| เล่มล่าสุด | **263 หน้า** · A4 · ระยะขอบ 3.0/2.0/2.5/2.0 ซม. |
| ฟอนต์ | TH Sarabun New (Regular/Bold) ฝังใน PDF จริง |
| สารบัญ / ภาพ / ตาราง | 313 / 98 / 66 รายการ (อัปเดตอัตโนมัติ) |
| กล่องหมายเหตุ | ย่อหน้าพื้นขาว + ตัวหนา (ไม่มีแถบสี) |
| ข้อความใน `` `...` `` | แสดงเป็น **ตัวหนา** (ไม่ใช้ monospace) |
| วงกลมครบตามบท | **ตรวจภาพจริงแล้ว: 43 / 64 ภาพที่มีรายการหมายเลข** (28 พ.ย. 2026) |
| ไฟล์ส่งมอบ | `reports/คู่มือการใช้งานระบบ_PIRIvoice.odt` + `.pdf` · สำเนาใน `~/reports/` |

## 2. เครื่องมือแคป (ใช้ต่อ)

```bash
CHROME_PATH=$(ls -d ~/.cache/ms-playwright/chromium-*/chrome-linux64/chrome | tail -1) \
  node reports/screenshot_capture/capture.mjs --all            # ทั้งหมด
  node reports/screenshot_capture/capture.mjs user/home        # เป้าหมายเดียว
```

- targets อยู่ใน `reports/screenshot_capture/targets.json`
- ผลลัพธ์ PNG → `out/` · สถานะอยู่ `out/_status.json` (`ok` = วงกลมครบ)
- **ตรวจ contact sheet ก่อนทับไฟล์จริงเสมอ** แล้วค่อย copy เป็น `.webp` (quality 82) ลง `docs/assets/screenshots/`

ความสามารถของ target:
`user` · `anon` · `path` · `width` (760 สำหรับแอดมิน) · `height` · `wait`
`click` (`text=`, `button:has-text()`, `js:ข้อความ`, ลงท้าย `|last`) ·
`type` · `setFiles` · `scrollFirst` · `scrollToText` + `scrollAdjust` · `replace` · `setToken`
`marks`: `{text|sel|selText|selN|selAll, n, box, radius, at, within}`
(`at`: `left` · `outside-left` · `outside-right` — ใช้กับข้อความล้วนไม่ให้วงทับตัวอักษร)

## 3. สถานะจริงหลังตรวจภาพทุกใบ (28 พ.ย. 2026)

> ⚠️ ตัวเลข "84/86" เดิมนับเฉพาะรูปที่ยังไม่เคยแคป **ไม่ได้ตรวจว่าวงครบตามบท**
> ตรวจใหม่ด้วยสคริปต์นับวงกลมแดงในภาพ (`/tmp` — ดูวิธีใน log) เทียบกับรายการในแต่ละบท
> ⇒ จาก 64 ภาพที่มีรายการหมายเลข มี **21 ภาพ** ที่วงไม่ครบ/ไม่มีวง

**แก้แล้วรอบนี้ (16 รูป · ตรวจด้วย DEBUG_MARKS + contact sheet):**
`received-issues` · `issue-accept-dialog` · `issue-close` · `issue-reject` · `issue-change-destination`
· `issue-menu` (ย้ายไปเรื่อง 36 เพราะเรื่อง 39 ไม่มีนับถอยหลัง ⇒ เมนูไม่มี "ยืดเวลา") ·
`event-create` · `event-registrations` · `student-records` · `student-role-menu` · `student-moves`
· `student-import` · `student-promote` · `user/more` · `user/profile-edit` · `user/issue-detail-actions`

**เหลือ 21 ภาพ:**

| กลุ่ม | รูป | ต้องทำ |
|---|---|---|
| user บอร์ด | `boards` · `board-vote` · `board-comment` · `new-suggestion` | เพิ่ม mark/ทำ target ใหม่ (board-vote กับ new-suggestion ยังไม่มี target) |
| user กิจกรรม | `events-list` · `event-detail` | ภาพปกเป็น `background-image` ไม่ใช่ `<img>` — ต้องหา selector |
| staff เรื่อง (ต้องแก้ข้อมูล staging) | `issue-in-progress` · `issue-escalated` · `issue-pending` · `issue-approve` | 39 ต้องมี countdown+steps · 40 ต้องมี countdown overdue · 38 ต้อง `requested_destination='talk'` (บท 12.4/12.6/12.11/12.12) |
| staff/บอร์ด | `moderation-queue` | บทมีข้อ 4 "สถานะว่าง" แต่หน้ามีรายการ — ต้องปรับบทหรือใช้ภาพสถานะว่าง |
| admin แดชบอร์ด | `dashboard-overview` (ขาดข้อ 5) · `dashboard-categories` · `dashboard-issue-trend` · `dashboard-system` · `dashboard-traffic` · `dashboard-login-chart` · `dashboard-activity-chart` | 6 รูปยังไม่มี mark เลย |
| admin อื่น | `user-add` · `users-list` · `term-new` · `terms-list` | users-list บทอ้าง "แท็บเจ้าหน้าที่" ซึ่ง UI เปลี่ยนเป็นชิปบทบาท — ต้องปรับบท |

## 4. ข้อมูล staging ที่แก้ไว้แล้ว (ตามที่เจ้าของเครื่องอนุญาต)

- ให้สิทธิ์ `is_admin` + permissions ครบกับ `e2ehead` / `e2eadm`
- แก้ชื่อเรื่องทดสอบ: `gggg` → "ขอพัดลมเพิ่มในห้องเรียน", `คิดว่างบโรงเรียนไปไหนหมด` → "ขอถังน้ำดื่มเพิ่มบริเวณอาคาร 3", `ทดสอบอัตโนมัติ…` → ข้อความจริง, `เทส`/`abc`/หัวข้อไม่สุภาพ
- ล้างข้อความทดสอบใน `notifications` (เช่น `[PR4 verify]`, `E2E e2ehead`, อีโมจิที่ขึ้นเป็นกล่อง)
- กระทู้ 2 ใช้ "ผมอยากให้มีการทัศนศึกษา" + แก้คำผิด `ตอนนนั้น`/`รึปล่าว`
- สร้างเรื่องทดสอบ 38 (pending) / 39 (in_progress) / 40 (escalated) — ไม่ระบุตัวตน ไม่มีรูป
- แก้ `main_category`/`category` ของ 38/39/40 ที่ค้างเป็นค่าไม่จริง `ecc` (ทำ UI ขึ้น "· ecc"
  เหนือหัวเรื่อง) เป็น `suggestion/academic` (38, 40) และ `report/complaint` (39) — 27 พ.ย. 2026
  ⇒ แคป `issue-pending` · `issue-in-progress` · `issue-escalated` · `issue-add-step` ·
  `issue-accept-dialog` · `issue-close` · `my-issues-filter` ใหม่ให้ไม่มีอักขระค้าง
- สร้างรายงานความคิดเห็น 4 รายการ (2 open · 1 resolved · 1 dismissed)
- สร้างกิจกรรม 4 (กีฬาสี 2569) + ผู้ลงทะเบียน (ยังอยู่บน staging — ลบได้เมื่อไม่ใช้)

## 5. ข้อควรระวัง

- รูปที่วงกลมไม่ครบ **ห้ามทับของเดิม** — บทอ้าง "หมายเลข 1–4" จะชี้ผิด
- ตรวจ `out/_status.json` + contact sheet ทุกครั้ง
- `python3 reports/build_odt.py` จะอัปเดตสารบัญและ export PDF เอง (ต้องมี LibreOffice + python3-uno)
- ถ้าไฟล์ `.odt` ค้าง lock (`reports/.~lock.*`) ให้ลบก่อนรัน
- ทุกงานต้องเข้า branch + PR (ห้ามคอมมิตเข้า `main` ตรง)

## 6. คำสั่งที่ใช้บ่อย

```bash
python3 reports/lint_manual.py reports/formal-manual      # ตรวจคำ/โครงสร้าง (ต้อง 0 error)
python3 reports/build_odt.py                              # สร้างเล่ม + PDF
pdfinfo reports/คู่มือการใช้งานระบบ_PIRIvoice.pdf | grep Pages
pdffonts reports/คู่มือการใช้งานระบบ_PIRIvoice.pdf         # ต้องเห็น THSarabunNew
```
