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
| รูปแคปที่แคปใหม่ | **84 / 86** |
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

## 3. เหลือ 2 รูป — แคปจากมือถือจริงเท่านั้น

> ✅ **staff (5) เสร็จแล้ว 27 พ.ย. 2026** — `issue-add-step` · `issue-extend` · `event-management`
> · `announcement-new` · `student-import-upload` แคปใหม่ตามเลขในบท 12.3 / 12.7 / 11.2+13.1 / 14.2 / 17.2
> (เครื่องแคปเพิ่ม `type` · `setFiles` · `within` · `scrollFirst` แล้ว — ดู README)
>
> ✅ **admin (3) เสร็จแล้ว 27 พ.ย. 2026** — `audit-table` (UI เป็น **การ์ด** ไม่ใช่ตาราง ⇒ ปรับบท 23
> ทั้งบทให้ตรง: 5 จุด = เวลา/ผู้ใช้/ป้ายการกระทำ/ข้อมูลอ้างอิง/รายละเอียด) · `quiet-hours-settings`
> (วง 5 จุด รวมสวิตช์ `button[role=switch]`) · `year-new` (ปุ่มจริงคือ **“เพิ่มปีการศึกษา”** ⇒ แก้บท 25.3 ด้วย)
>
> ✅ **user — หน้าเว็บเสร็จแล้ว 27 พ.ย. 2026**
> · แคปใหม่ 6 รูป: `notifications-filter` (วงใน `[role=dialog]`) · `my-issues-filter` (วงชิป "ทั้งหมด" +
> การ์ด) · `home-shortcuts-card` (height 1000 ให้การ์ดสรุปพ้น FAB)
> · `new-issue` · `new-issue-detail` (คลิกการ์ดหมวด div → หมวดย่อย → ถัดไป + กรอกตัวอย่าง) ·
> `new-issue-send` (ใช้ `clickAfter` กด "ถัดไป" หลังกรอก)
> · `notifications` และ `my-issues` ตรวจแล้ว **ไม่ต้องมีวง** (บทไม่มีรายการหมายเลข) — คงไฟล์เดิม
>
> ✅ **public (2) เสร็จแล้ว 27 พ.ย. 2026** — `landing-hero` (วง 4 จุด; ปุ่ม "เข้าสู่ระบบ" มี 2 ตัว
> ในหน้า ⇒ ต้องจำกัด `within: "header"` ไม่งั้นวงไปเกาะลิงก์ท้ายหน้า) · `login` (วง 1–4:
> ช่องรหัสนักเรียน · ช่องรหัสผ่าน · ปุ่มเข้าสู่ระบบ · กล่องรหัสผ่านเริ่มต้น)

### ยังเหลือ — 2 รูป OS (ไม่ใช่หน้าเว็บ)
| รูป | ต้องทำอะไร |
|---|---|
| `install-android` | แคปจากมือถือ Android จริง (หน้าติดตั้ง PWA / เมนู Chrome) |
| `ios-install` | แคปจาก iPhone จริง (Safari → เพิ่มไปยังหน้าจอโฮม) |

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
