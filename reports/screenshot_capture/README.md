# เครื่องมือแคปหน้าจอคู่มือ PIRIvoice

แคปหน้าจอจริงจาก **staging** (`https://prsc-test.pirivoice.com`) ด้วย Playwright + Chromium
ขนาดมือถือ 390×844 @2x (ได้ไฟล์ 780×1688) ภาษา th-TH · เขตเวลา Asia/Bangkok

## ใช้งาน

```bash
# ต้องมี /tmp/e2e_credentials.json (สร้างโดย backend/scripts/e2e_seed.py)
CHROME_PATH=$(ls -d ~/.cache/ms-playwright/chromium-*/chrome-linux64/chrome | tail -1) \
  node reports/screenshot_capture/capture.mjs --all

node reports/screenshot_capture/capture.mjs user/home           # เป้าหมายเดียว
node reports/screenshot_capture/capture.mjs --all --only=user/  # เฉพาะกลุ่ม
```

ผลลัพธ์ PNG อยู่ที่ `out/<โฟลเดอร์>/ชื่อไฟล์.png` พร้อม `out/_status.json`
(บอกว่าวงกลมกำกับ "找了ครบ" หรือไม่) แล้วแปลงเป็น WebP ก่อนวางใน `docs/assets/screenshots/`

## targets.json

| ฟิลด์ | ความหมาย |
|---|---|
| `file` | ไฟล์ปลายทางใต้ `docs/assets/screenshots/` |
| `user` | บัญชี (`e2estu` / `e2ehead` / `e2eadm`) หรือ `anon: true` |
| `path` | เส้นทาง เช่น `/app/home` |
| `height` | ความสูงวิวพอร์ต (หน้าฟอร์มใช้ 950–1350) |
| `click` | selector ที่กดก่อนแคป (เช่น เลือกหมวดก่อนกด "ถัดไป") |
| `replace` | แทนข้อความบนหน้า — โดเมนทดสอบ/ชื่อจริง/อีโมจิที่ขึ้นเป็นกล่อง |
| `scrollToText` + `scrollAdjust` | เลื่อนไปยังหัวข้อที่ต้องการ |
| `marks` | วงกลม/กรอบสีแดง: `{text|sel|selText, n, box, radius, at}` |
| `setToken` | แทนข้อความรหัสบัตรเช็คอินให้สั้นอ่านง่าย |

## ข้อควรรู้

- แอปเปิด SSE ค้าง ⇒ ห้ามใช้ `waitUntil: 'networkidle'` (ใช้ `domcontentloaded` + `waitForTimeout`)
- หน้าแรกเลื่อนใน container ภายใน ⇒ `scrollToText` ใช้ `scrollIntoView` + `window.scrollBy`
- ข้อความทดลอง (ชื่อ E2E, โดเมนทดสอบ) ให้แก้ที่ **ข้อมูล staging** หรือใช้ `replace`
- ภาพทุกใบต้อง치้ากับเลขในรายการของบทนั้น — ตรวจ `_status.json` ว่าวงกลมครบก่อนแทนไฟล์
