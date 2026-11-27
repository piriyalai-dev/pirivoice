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
| รูปแคปที่แคปใหม่ | **68 / 86** |
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
`scrollToText` + `scrollAdjust` · `replace` · `setToken`
`marks`: `{text|sel|selText|selN, n, box, radius, at}`

## 3. เหลือ 18 รูป — รายละเอียดต่อรูป

### staff (5)
| รูป | ตัวบล็อก | แนวทาง |
|---|---|---|
| `issue-add-step` | ปุ่ม "เพิ่มขั้นตอน" อยู่ในแผง | เปิดแผงตัวเลือกก่อน (`js:`/aria) แล้วกด |
| `issue-extend` | ไม่มีปุ่มขยายเวลาบนหน้า | ตรวจว่าอยู่ในเมนูนับถอยหลังหรือไม่มีจริง → ปรับบท |
| `event-management` | วงกลม 4 (FAB "สร้างกิจกรรม") เป็น element ขนาดศูนย์ | หาคลาสของ FAB (`fixed bottom`) แล้ว mark ตรง ๆ |
| `announcement-new` | บทอ้าง 6 จุด แต่ 4 จุดแรกไม่มีป้ายใน label list | เปิด DOM กล่อง "เพิ่มประกาศ" แล้วกำหนด marks |
| `student-import-upload` | ต้องเลือกไฟล์ก่อนถึงเข้าขั้นอัปโหลด | ใช้ `input[type=file]` setInputFiles หรือแคปเฉพาะโซนลากวาง |

### admin (3)
| รูป | ตัวบล็อก | แนวทาง |
|---|---|---|
| `audit-table` | UI แสดง **การ์ด ไม่มีตาราง/หัวคอลัมน์** (ลอง 1200px แล้ว) | ตัดสินใจ: ปรับบท 23.2 ให้ตรง UI หรือเปลี่ยนภาพ |
| `quiet-hours-settings` | วงกลม 5 (สวิตช์เปิดใช้) | mark ที่ป้าย/สวิตช์ในหัวการ์ด |
| `year-new` | วงกลม 5 (ปุ่มบันทึก) | หาชื่อปุ่มจริง (อาจเป็น "บันทึกข้อมูล") |

### user (10 = 8 หน้าเว็บ + 2 OS)
| รูป | ตัวบล็อก |
|---|---|
| `notifications-filter` | วงกลม 2–4 ไปเกาะแท็บล่าง — จำกัด selector ในแผ่น `[role="dialog"]` |
| `my-issues-filter` | ปุ่ม "กรอง" ไม่มีข้อความ — คลิกด้วย `sel`/`js:` |
| `home-shortcuts-card` | ยังไม่พบ anchor การ์ดทางลัด |
| `new-issue` ×3 | ต้องคลิก **การ์ดหมวดหลัก (div)** → หมวดย่อย → "ถัดไป" (ต้องเพิ่มโหมดคลิก div) |
| `install-android`, `ios-install` | **ไม่ใช่หน้าเว็บ** — แคปจากมือถือจริง |

### public (3)
| รูป | ตัวบล็อก |
|---|---|
| `landing-hero` | วงกลม 4 จุด (เข้าสู่ระบบ/ประกาศ/แจ้งเรื่อง/รายงานสถิติ) |
| `login` | วงกลมครบ 4 (ป้าย 2 จุดในบทว่าง) |
| `landing-stats` | ✅ แคปใหม่แล้ว (ไม่ต้องทำ) |

## 4. ข้อมูล staging ที่แก้ไว้แล้ว (ตามที่เจ้าของเครื่องอนุญาต)

- ให้สิทธิ์ `is_admin` + permissions ครบกับ `e2ehead` / `e2eadm`
- แก้ชื่อเรื่องทดสอบ: `gggg` → "ขอพัดลมเพิ่มในห้องเรียน", `คิดว่างบโรงเรียนไปไหนหมด` → "ขอถังน้ำดื่มเพิ่มบริเวณอาคาร 3", `ทดสอบอัตโนมัติ…` → ข้อความจริง, `เทส`/`abc`/หัวข้อไม่สุภาพ
- ล้างข้อความทดสอบใน `notifications` (เช่น `[PR4 verify]`, `E2E e2ehead`, อีโมจิที่ขึ้นเป็นกล่อง)
- กระทู้ 2 ใช้ "ผมอยากให้มีการทัศนศึกษา" + แก้คำผิด `ตอนนนั้น`/`รึปล่าว`
- สร้างเรื่องทดสอบ 38 (pending) / 39 (in_progress) / 40 (escalated) — ไม่ระบุตัวตน ไม่มีรูป
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
