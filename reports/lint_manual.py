#!/usr/bin/env python3
"""ตรวจคุณภาพคู่มือภาษาทางการ PIRIvoice.

สแกนไฟล์ Markdown ใต้ reports/formal-manual/ และรายงานข้อผิดพลาด 16 ประเภท:
  1. emoji              – อิโมจิหลงเหลือ (รวมลูกศร ➔ ซึ่งต้องเปลี่ยนเป็น →)
  2. thai-en-paren      – วงเล็บคำแปลภาษาอังกฤษต่อท้ายคำไทย
  3. banned-term        – คำต้องห้าม (ภาษาพูด/สรรพนาม/คำทับศัพท์/คำสะกดผิด) นอกเครื่องหมายคำพูด
  4. ai-smell           – ประโยคกลิ่น AI (เช่น "ไม่ดำเนินการใด")
  5. vitepress-html     – เศษ VitePress หรือแท็ก HTML
  6. image-caption      – รูปภาพไม่มีจริงหรือขาดคำบรรยาย
  7. heading-number     – โครงสร้างหัวข้อและลำดับเลขไม่ถูกต้อง
  8. heading-on-label   – ห้ามใช้ # กับป้ายกำกับขั้นตอน/กล่องหมายเหตุ
  9. cross-link         – ลิงก์ข้ามหน้าแบบ VitePress หลงเหลือ
  10. table-caption     – ตารางขาดคำบรรยาย **ตารางที่ X.Y** เหนือตาราง
  11. faq-table         – ตาราง FAQ ต้องมีหัวตาราง 2 คอลัมน์และจำนวนแถวเท่าต้นฉบับ
  12. numbered-image-item – คำอธิบายหมายเลขบนภาพต้องขึ้นต้นด้วยเลขข้อ 1. 2. ...
  13. source-parity     – จำนวนภาพ/กล่องคำแนะนำ/แผนผัง/FAQ ไม่ตรงกับต้นฉบับใน docs/
  14. dash-list         – รายการต้องใช้เลขข้อ 1. 2. 3. ห้ามใช้ขีด -
  15. terse-faq         – คำตอบในตาราง FAQ ต้องเป็นประโยคเต็ม ห้ามตอบห้วน (ไม่/ได้/ไม่ได้)
  16. intro-paragraph   – หัวข้อต้องมีย่อหน้าเกริ่นนำก่อน **ลำดับขั้นตอนการปฏิบัติงาน**

ใช้งาน:
    python3 reports/lint_manual.py
    python3 reports/lint_manual.py reports/formal-manual/01-user-guide/ch01-overview.md
"""
from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO_ROOT = ROOT.parent
DEFAULT_TARGET = ROOT / "formal-manual"
DOCS_ROOT = REPO_ROOT / "docs"

RULES = {
    "emoji": "ห้ามมีอิโมจิ (ลูกศรต้องใช้ → เท่านั้น)",
    "thai-en-paren": "ห้ามมีวงเล็บคำแปลภาษาอังกฤษต่อท้ายคำไทย",
    "banned-term": "ห้ามใช้คำต้องห้าม (ภาษาพูด/สรรพนาม/คำทับศัพท์/คำสะกดผิด) นอกเครื่องหมายคำพูด",
    "ai-smell": "ห้ามใช้ประโยคกลิ่น AI เช่น 'ไม่ดำเนินการใด' 'สำหรับอ่านเท่านั้น' 'องค์ประกอบสำหรับแสดงผล' 'เป็นข้อมูลแสดงผล' 'มิได้เป็นปุ่มที่กดได้'",
    "vitepress-html": "ห้ามเหลือบล็อก VitePress หรือแท็ก HTML",
    "image-caption": "รูปภาพต้องมีไฟล์จริงและมีคำบรรยาย **ภาพที่ X.Y** ใต้ภาพทันที",
    "heading-number": "หัวข้อต้องมีลำดับเลขถูกต้องและตรงกับหมายเลขบท",
    "heading-on-label": "ห้ามใช้หัวข้อ # กับป้ายกำกับขั้นตอนหรือกล่องหมายเหตุ",
    "cross-link": "ห้ามเหลือลิงก์ข้ามหน้าแบบ VitePress",
    "table-caption": "ทุกตารางต้องมีคำบรรยาย **ตารางที่ X.Y** อยู่เหนือตาราง",
    "faq-table": "ตาราง FAQ ต้องมีหัวตาราง 2 คอลัมน์และจำนวนแถวเท่าต้นฉบับ",
    "numbered-image-item": "คำอธิบายหมายเลขบนภาพต้องขึ้นต้นด้วยเลขข้อ 1. 2. ...",
    "source-parity": "จำนวนภาพ กล่องคำแนะนำ แผนผัง และจำนวนหัวข้อต้องไม่น้อยกว่าต้นฉบับ",
    "dash-list": "รายการต้องขึ้นต้นด้วยเลขข้อ 1. 2. 3. ห้ามใช้ขีด -",
    "terse-faq": "คำตอบในตาราง FAQ ต้องเป็นประโยคเต็ม ห้ามตอบห้วน ๆ ว่า ไม่/ได้/ไม่ได้",
    "intro-paragraph": "หัวข้อต้องมีย่อหน้าเกริ่นนำก่อนป้ายลำดับขั้นตอน",
}

# แมปไฟล์ปลายทาง -> ไฟล์ต้นฉบับใน docs/ (ใช้ตรวจความครบถ้วน)
CHAPTER_SOURCES = {
    "ch01-overview.md": "1-user-guide/index.md",
    "ch02-public-landing.md": "1-user-guide/public-landing.md",
    "ch03-getting-started-pwa.md": "1-user-guide/getting-started-pwa.md",
    "ch04-notifications-settings.md": "1-user-guide/notifications-settings.md",
    "ch05-home-and-navigation.md": "1-user-guide/home-and-navigation.md",
    "ch06-issue-reporting-tracking.md": "1-user-guide/issue-reporting-tracking.md",
    "ch07-boards-and-voting.md": "1-user-guide/boards-and-voting.md",
    "ch08-events-and-checkin.md": "1-user-guide/events-and-checkin.md",
    "ch09-profile-and-activity.md": "1-user-guide/profile-and-activity.md",
    "ch10-playbooks.md": "1-user-guide/playbooks.md",
    "ch11-staff-overview.md": "2-staff-operations/index.md",
    "ch12-issue-management-sop.md": "2-staff-operations/issue-management-sop.md",
    "ch13-event-management-scanner.md": "2-staff-operations/event-management-scanner.md",
    "ch14-announcement-management.md": "2-staff-operations/announcement-management.md",
    "ch15-content-moderation.md": "2-staff-operations/content-moderation.md",
    "ch16-student-records.md": "2-staff-operations/student-records.md",
    "ch17-student-import.md": "2-staff-operations/student-import.md",
    "ch18-student-moves.md": "2-staff-operations/student-moves.md",
    "ch19-student-promotion.md": "2-staff-operations/student-promotion.md",
    "ch20-reassignment-and-reconciliation.md": "2-staff-operations/reassignment-and-reconciliation.md",
    "ch21-admin-overview.md": "3-admin-guide/index.md",
    "ch22-user-and-role-management.md": "3-admin-guide/user-and-role-management.md",
    "ch23-audit-logs-investigation.md": "3-admin-guide/audit-logs-investigation.md",
    "ch24-system-configuration.md": "3-admin-guide/system-configuration.md",
    "ch25-academic-calendar.md": "3-admin-guide/academic-calendar.md",
    "ch26-dashboard-and-reports.md": "3-admin-guide/dashboard-and-reports.md",
    "ch27-technical-appendix.md": "3-admin-guide/technical-appendix.md",
}

# ช่วงอิโมจิที่ใช้บ่อย ไม่รวมลูกศรและเครื่องหมายวรรคตอนทั่วไป
EMOJI_RE = re.compile(
    "[\U0001F000-\U0001FAFF☀-➿⬀-⯿️‍⃣]"
)
TH_EN_PAREN_RE = re.compile(r"[ก-๙]\s*\([^)\n]*[A-Za-z][^)\n]*\)")
# คำภาษาอังกฤษที่อนุญาตให้แทรกในวงเล็บต่อท้ายคำไทยได้ (ตามสเปก 4.1)
ALLOWED_PARENS = {
    "PIRIvoice", "PIRI Talk", "PIRI Vote", "PIRI Board", "PIRI-EVT1",
    "Chrome", "Safari", "Android", "iPhone", "iPad",
    "Excel", "PDF", "QR Code", "URL", "HTTP", "HTTPS", "OTP", "SMS",
    "HEIC", "MB", "API Endpoint", "Permissions", "Signed URL",
}
QUOTED_RE = re.compile(r"“[^”]*”")
INLINE_CODE_RE = re.compile(r"`[^`\n]*`")
IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
LINK_RE = re.compile(r"(?<!!)\[[^\]]*\]\(([^)]+)\)")
FIG_CAPTION_RE = re.compile(r"^\*\*ภาพที่ (\d+)\.(\d+)\*\*\s*แสดง")
FIG_PLACEHOLDER_RE = re.compile(
    r"^\s*>\s*\*\*\[แทรกภาพที่ (\d+)\.(\d+)\s*:.*\]\*\*\s*$"
)
TABLE_CAPTION_RE = re.compile(r"^\*\*ตารางที่ (\d+)\.(\d+)\*\*\s*(.*)$")
H1_RE = re.compile(r"^#\s+บทที่\s+(\d+)\s+(\S.*)$")
H2_RE = re.compile(r"^##\s+(\d+)\.(\d+)\s+(\S.*)$")
H3_RE = re.compile(r"^###\s+(\d+)\.(\d+)\.(\d+)\s+(\S.*)$")
H4_RE = re.compile(r"^#{4,}\s+")
HTML_TAG_RE = re.compile(
    r"</?(?:div|span|p|br|img|a|b|i|strong|em|table|thead|tbody|tr|td|th|ul|ol|li|h[1-6])\b[^>]*>",
    re.IGNORECASE,
)
FAQ_HEADING_RE = re.compile(
    r"^##\s+(\d+)\.(\d+)\s+แนวทางการแก้ไขปัญหาที่พบบ่อยในการใช้งาน\s*$"
)
FAQ_HEADERS = ["ปัญหาหรือสถานการณ์ที่พบ", "สาเหตุและแนวทางการแก้ไข"]
BOX_LABEL_RE = re.compile(r"^>\s*\*\*(ข้อแนะนำในการใช้งาน|ข้อควรระวังสำคัญ|ข้อสังเกต):")

BANNED_COLLOQUIAL = [
    "พี่เล่าให้น้องฟัง", "ปุ๊บ", "ปั๊บ", "สามวิ", "ทำไงดี", "ยังไง",
    "โชว์", "เคส", "สตาฟ", "เด้ง", "โผล่", "ล่องหน", "รกจอ",
    "ยุ่งนิดนึง", "ชัวร์", "เพียบ", "เจ๋ง", "คุณครู", "แอดมิน",
    "ครับ", "ค่ะ", "นะครับ", "นะคะ", "นะจ๊ะ",
    "เล่มที่หนึ่ง", "เล่มที่สอง", "เล่มที่สาม", "คู่มือเล่มนี้",
    "Landing Page", "หน้า Landing", "รีเฟรช", "รีเซ็ต", "แคช",
    "แกลเลอรีรูป", "แกลเลอรี", "คอมเมนต์", "ความรู้จัก",
    "เมนูแบ่งปัน", "หากยังไม่หาย", "หายไปจากสายตา",
    "IPhone", "IPad", "การส่งองงาน",
    "ครอป", "แบบทันเวลา", "การรู้จัก", "มีความเห็นมีกล่อง", "หน้าปกใน",
    "ติ๊ก", "ชิป", "หัวจอ", "พิมพ์ค้าง", "ค่าสำเร็จรูป",
    "ไม่ต้องกังวล", "เรื่องใหญ่โต", "เล่มหนา",
]
BANNED_PRONOUNS = ["เรา", "น้อง", "เพื่อน", "ฉัน", "ตัวเอง"]
AI_SMELL_TERMS = [
    "ไม่ดำเนินการใด",
    "สำหรับอ่านเท่านั้น",
    "องค์ประกอบสำหรับแสดงผล",
    "มิได้เป็นปุ่มที่กดได้",
    "ไม่สามารถกดได้",
    "เป็นข้อมูลแสดงผล",
]

# คำต้องห้ามแบบขึ้นกับบริบท (ต้องดูอักษรที่ตามมา)
CONTEXT_BANNED = [
    (re.compile(r"แอป(?!พลิเคชัน)"), "แอป (ต้องใช้คำว่า แอปพลิเคชัน)"),
    (re.compile(r"ผู้ใช้(?!งาน)"), "ผู้ใช้ (ต้องใช้คำว่า ผู้ใช้งาน)"),
    (re.compile(r"คิวอาร์(?!เช็คอิน)"), "คิวอาร์ (ต้องใช้คำว่า รหัส QR Code หรือ คิวอาร์เช็คอิน)"),
    (re.compile(r"เช็กอิน"), "เช็กอิน (ต้องใช้ เช็คอิน ตามข้อความจริงบนหน้าจอ)"),
    (re.compile(r"เช็ก(?!อิน)"), "เช็ก (ต้องใช้ ตรวจสอบ หรือ เช็กอิน ตามบริบท)"),
    (re.compile(r"ไอเดีย"), "ไอเดีย (ต้องใช้ ข้อเสนอแนะ/แนวคิด เว้นชื่อปุ่ม “เสนอไอเดีย”)"),
    (re.compile(r"ครู(?!ที่ปรึกษา|ประจำชั้น|ผู้ดูแลระบบ|สภานักเรียน|ทั่วไป|[่้๊๋])"), "ครู (ต้องใช้ ครูที่ปรึกษา/ครูประจำชั้น/ครูผู้ดูแลระบบ/ครูสภานักเรียน/ครูทั่วไป ตามบริบท)"),
    (re.compile(r"เล่มที่\s*[1-3๑-๓]"), "เล่มที่ 1/2/3 (ต้องใช้คำว่า ภาคที่ 1/2/3)"),
    (re.compile(r"ล็อกอิน"), "ล็อกอิน (ต้องใช้ การเข้าสู่ระบบ หรือครอบ “...” หากเป็นชื่อป้ายบนหน้าจอ)"),
    (re.compile(r"ผู้เข้าใช้(?!งาน)"), "ผู้เข้าใช้ (ต้องใช้ ผู้ใช้งาน)"),
    (re.compile(r"(?<!แพลต)(?<!แบบ)ฟอร์ม"), "ฟอร์ม (ต้องใช้ แบบฟอร์ม)"),
    (re.compile(r"พฤติกรรม"), "พฤติกรรม (ต้องใช้ ลักษณะการทำงาน หรือ สถานะการทำงาน)"),
]

# ป้ายกำกับขั้นตอน/กล่องหมายเหตุที่ห้ามใช้เป็นหัวข้อ #
HEADING_LABELS = [
    "เส้นทางการเข้าถึงเมนู",
    "สิ่งที่ต้องเตรียม",
    "ลำดับขั้นตอน",
    "ผลลัพธ์การทำงาน",
    "ข้อควรระวังสำคัญ",
    "ข้อแนะนำในการใช้งาน",
]


@dataclass
class Finding:
    rule: str
    path: Path
    line: int
    message: str
    severity: str = "error"


def strip_code_and_quotes(line: str) -> str:
    """ตัดข้อความในโค้ดอินไลน์ เครื่องหมายคำพูด และคำบรรยายภาพออกก่อนตรวจคำต้องห้าม."""
    line = INLINE_CODE_RE.sub("", line)
    line = IMAGE_RE.sub("", line)
    line = QUOTED_RE.sub("", line)
    return line


def chapter_from_filename(path: Path) -> int | None:
    match = re.search(r"ch(\d{2})-", path.name)
    return int(match.group(1)) if match else None


def is_chapter_file(path: Path) -> bool:
    return chapter_from_filename(path) is not None


def relative(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def add(findings, rule, path, line, message, severity="error"):
    findings.append(Finding(rule, path, line, message, severity))


def check_emoji(path, lines, findings):
    for no, line in enumerate(lines, 1):
        for match in EMOJI_RE.finditer(line):
            add(findings, "emoji", path, no, f"พบอิโมจิ {match.group(0)!r}")


def check_thai_english_parens(path, lines, findings):
    for no, line in enumerate(lines, 1):
        cleaned = strip_code_and_quotes(line)
        for match in TH_EN_PAREN_RE.finditer(cleaned):
            text = match.group(0)
            inner = text[text.find("(") + 1:text.rfind(")")].strip()
            if inner in ALLOWED_PARENS:
                continue
            if not re.search(r"[A-Za-z]", inner):
                continue
            add(
                findings, "thai-en-paren", path, no,
                f"พบวงเล็บคำแปลภาษาอังกฤษ “({inner})”",
            )


def check_banned_terms(path, lines, findings):
    for no, line in enumerate(lines, 1):
        cleaned = strip_code_and_quotes(line)
        for term in BANNED_COLLOQUIAL + BANNED_PRONOUNS:
            if term in cleaned:
                add(findings, "banned-term", path, no, f"พบคำต้องห้าม “{term}”")
        for pattern, hint in CONTEXT_BANNED:
            if pattern.search(cleaned):
                add(findings, "banned-term", path, no, f"พบคำต้องห้าม: {hint}")


def check_ai_smell(path, lines, findings):
    for no, line in enumerate(lines, 1):
        cleaned = strip_code_and_quotes(line)
        for term in AI_SMELL_TERMS:
            if term in cleaned:
                add(findings, "ai-smell", path, no, f"พบประโยคกลิ่น AI “{term}”")


def check_vitepress_and_html(path, lines, findings):
    for no, line in enumerate(lines, 1):
        if re.match(r"^\s*:::", line):
            add(findings, "vitepress-html", path, no, "พบบล็อก VitePress :::")
        if re.match(r"^\s*```mermaid", line):
            add(findings, "vitepress-html", path, no, "พบโค้ด mermaid")
        if line.strip().startswith("```"):
            add(findings, "vitepress-html", path, no, "พบโค้ดบล็อก triple backtick")
        if re.search(r"\{\{.*?\}\}", line):
            add(findings, "vitepress-html", path, no, "พบนิพจน์ {{ }} ของ VitePress")
        if HTML_TAG_RE.search(line):
            add(findings, "vitepress-html", path, no, "พบแท็ก HTML")


def check_images_and_captions(path, lines, findings):
    chapter = chapter_from_filename(path)
    is_chapter = chapter is not None
    for no, line in enumerate(lines, 1):
        for match in IMAGE_RE.finditer(line):
            target = match.group(2)
            if target.startswith(("http://", "https://", "data:")):
                continue
            resolved = (path.parent / target).resolve()
            if not resolved.exists():
                add(findings, "image-caption", path, no, f"ไม่พบไฟล์รูป {target}")
                continue
            try:
                resolved.relative_to(REPO_ROOT)
            except ValueError:
                add(findings, "image-caption", path, no, f"รูปอยู่นอกรีโป {target}")
            if not is_chapter:
                continue
            next_line = lines[no] if no < len(lines) else ""
            caption = FIG_CAPTION_RE.match(next_line)
            if not caption:
                add(
                    findings, "image-caption", path, no,
                    "บรรทัดถัดไปต้องเป็นคำบรรยาย **ภาพที่ X.Y** แสดง...",
                )
                continue
            figure_chapter = int(caption.group(1))
            if figure_chapter != chapter:
                add(
                    findings, "image-caption", path, no,
                    f"เลขบทในคำบรรยายเป็น {figure_chapter} แต่ไฟล์เป็นบทที่ {chapter}",
                )
        placeholder = FIG_PLACEHOLDER_RE.match(line)
        if placeholder and is_chapter:
            if int(placeholder.group(1)) != chapter:
                add(
                    findings, "image-caption", path, no,
                    f"เลขบทในที่แทรกภาพเป็น {placeholder.group(1)} "
                    f"แต่ไฟล์เป็นบทที่ {chapter}",
                )
            found_caption = False
            for ahead in range(no, min(no + 2, len(lines))):
                if FIG_CAPTION_RE.match(lines[ahead]):
                    found_caption = True
                    break
            if not found_caption:
                add(
                    findings, "image-caption", path, no,
                    "ที่แทรกภาพต้องมีคำบรรยาย **ภาพที่ X.Y** ตามมาภายใน 2 บรรทัด",
                )

    if not is_chapter:
        return
    # ลำดับภาพนับจากคำบรรยาย (ทุกภาพจริงและที่แทรกแทนแผนผังล้วนมีคำบรรยายกำกับ)
    order = [int(m.group(2)) for line in lines if (m := FIG_CAPTION_RE.match(line))]
    expected = list(range(1, len(order) + 1))
    if order != expected:
        add(
            findings, "image-caption", path, 1,
            f"ลำดับภาพไม่ต่อเนื่อง: {order} (คาดว่า {expected})",
        )


def check_headings(path, lines, findings):
    chapter = chapter_from_filename(path)
    if lines and lines[0].strip() == "---":
        add(findings, "heading-number", path, 1, "ห้ามมี YAML frontmatter")

    h1 = []
    h2 = []
    h3 = []
    for no, line in enumerate(lines, 1):
        if line.startswith("# "):
            match = H1_RE.match(line)
            if not match:
                add(findings, "heading-number", path, no, "H1 ต้องอยู่ในรูป '# บทที่ N ชื่อบท'")
            else:
                h1.append((no, int(match.group(1))))
        elif line.startswith("## "):
            match = H2_RE.match(line)
            if not match:
                add(findings, "heading-number", path, no, "H2 ต้องอยู่ในรูป '## N.M ชื่อหัวข้อ'")
            else:
                h2.append((no, int(match.group(1)), int(match.group(2))))
        elif line.startswith("### "):
            match = H3_RE.match(line)
            if not match:
                add(findings, "heading-number", path, no, "H3 ต้องอยู่ในรูป '### N.M.K ชื่อหัวข้อย่อย'")
            else:
                h3.append((no, int(match.group(1)), int(match.group(2)), int(match.group(3))))
        elif H4_RE.match(line):
            add(findings, "heading-number", path, no, "ไม่ควรใช้หัวข้อระดับ H4 ขึ้นไป", "warning")

    if len(h1) != 1:
        add(findings, "heading-number", path, 1, f"ต้องมี H1 เพียงหนึ่งหัวข้อ (พบ {len(h1)})")
        return

    h1_line, h1_chapter = h1[0]
    if chapter is not None and h1_chapter != chapter:
        add(
            findings, "heading-number", path, h1_line,
            f"H1 ระบุบทที่ {h1_chapter} แต่ชื่อไฟล์เป็นบทที่ {chapter}",
        )
    for no, chapter_no, _ in h2:
        if chapter_no != h1_chapter:
            add(
                findings, "heading-number", path, no,
                f"H2 ระบุบทที่ {chapter_no} ไม่ตรงกับ H1 ({h1_chapter})",
            )
    sequence = [number for _, _, number in h2]
    expected = list(range(1, len(sequence) + 1))
    if sequence != expected:
        add(
            findings, "heading-number", path, 1,
            f"ลำดับ H2 ไม่ต่อเนื่อง: {sequence} (คาดว่า {expected})",
        )
    h2_numbers = set(sequence)
    for no, chapter_no, parent, _ in h3:
        if chapter_no != h1_chapter:
            add(
                findings, "heading-number", path, no,
                f"H3 ระบุบทที่ {chapter_no} ไม่ตรงกับ H1 ({h1_chapter})",
            )
        if parent not in h2_numbers:
            add(
                findings, "heading-number", path, no,
                f"H3 อ้างหัวข้อ {chapter_no}.{parent} ที่ไม่มีอยู่",
            )


def check_heading_labels(path, lines, findings):
    for no, line in enumerate(lines, 1):
        stripped = line.strip()
        if not stripped.startswith("#"):
            continue
        text = stripped.lstrip("#").strip()
        for label in HEADING_LABELS:
            if text.startswith(label):
                add(
                    findings, "heading-on-label", path, no,
                    f"ห้ามใช้หัวข้อ # กับป้ายกำกับ “{label}” "
                    f"ให้ใช้ตัวหนา **{label}** หรือ blockquote แทน",
                )
                break


def check_table_captions(path, lines, findings):
    """ทุกตารางต้องมีคำบรรยาย **ตารางที่ X.Y** อยู่เหนือตาราง และเลขต้องเรียงต่อเนื่อง."""
    chapter = chapter_from_filename(path)
    if chapter is None:
        return
    numbers = []
    index = 0
    total = len(lines)
    while index < total:
        if lines[index].strip().startswith("|"):
            start = index
            end = index
            while end + 1 < total and lines[end + 1].strip().startswith("|"):
                end += 1
            # หาคำบรรยายเหนือตาราง: สแกนขึ้นจาก start-1 ข้ามบรรทัดว่าง
            caption_line = -1
            probe = start - 1
            blanks = 0
            while probe >= 0:
                s = lines[probe].strip()
                if not s:
                    blanks += 1
                    probe -= 1
                    if blanks > 3:
                        break
                    continue
                caption_line = probe
                break
            matched = False
            if caption_line >= 0:
                m = TABLE_CAPTION_RE.match(lines[caption_line].strip())
                if m:
                    matched = True
                    if int(m.group(1)) != chapter:
                        add(
                            findings, "table-caption", path, caption_line + 1,
                            f"เลขบทในคำบรรยายตารางเป็น {m.group(1)} "
                            f"แต่ไฟล์เป็นบทที่ {chapter}",
                        )
                    numbers.append(int(m.group(2)))
                    caption_text = m.group(3).strip()
                    if not caption_text.startswith("แสดง"):
                        add(
                            findings, "table-caption", path, caption_line + 1,
                            "คำบรรยายตารางต้องขึ้นต้นด้วย “แสดง” "
                            "(เช่น **ตารางที่ X.Y** แสดง...)",
                        )
            if not matched:
                add(
                    findings, "table-caption", path, start + 1,
                    "ตารางขาดคำบรรยาย **ตารางที่ X.Y** เหนือตาราง",
                )
            # ตรวจว่ามีคำบรรยายวางไว้ใต้ตาราง (แบบเก่า) หรือไม่
            below = end + 1
            while below < total and not lines[below].strip():
                below += 1
            if below < total and TABLE_CAPTION_RE.match(lines[below].strip()):
                add(
                    findings, "table-caption", path, below + 1,
                    "ป้ายชื่อตารางต้องอยู่เหนือตาราง ไม่ใช่ใต้ตาราง",
                )
            index = end + 1
        else:
            index += 1
    expected = list(range(1, len(numbers) + 1))
    if numbers != expected:
        add(
            findings, "table-caption", path, 1,
            f"ลำดับตารางไม่ต่อเนื่อง: {numbers} (คาดว่า {expected})",
        )


def check_cross_links(path, lines, findings):
    for no, line in enumerate(lines, 1):
        without_images = IMAGE_RE.sub("", line)
        for match in LINK_RE.finditer(without_images):
            target = match.group(1).strip()
            if target.startswith(("http://", "https://", "#", "mailto:")):
                continue
            if target.startswith("./") or re.search(r"\.md(?:[#?].*)?$", target):
                add(findings, "cross-link", path, no, f"พบลิงก์ข้ามหน้า {target}")


def check_numbered_image_items(path, lines, findings):
    for no, line in enumerate(lines, 1):
        if re.match(r"^\s*\*\*หมายเลข", line):
            add(
                findings, "numbered-image-item", path, no,
                "คำอธิบายหมายเลขบนภาพต้องขึ้นต้นด้วยเลขข้อ (1. 2. ...) ห้ามเป็นย่อหน้าตัวหนาลอย ๆ",
            )


def check_dash_lists(path, lines, findings):
    for no, line in enumerate(lines, 1):
        if re.match(r"^\s*-\s+", line):
            add(
                findings, "dash-list", path, no,
                "รายการต้องใช้เลขข้อ 1. 2. 3. ห้ามใช้ขีด -",
            )


def check_intro_paragraph(path, lines, findings):
    """หัวข้อ (H2/H3) ต้องมีย่อหน้าเกริ่นนำก่อนป้ายขั้นตอนแรก."""
    if not is_chapter_file(path):
        return
    for no, line in enumerate(lines, 1):
        if not (H2_RE.match(line) or H3_RE.match(line)):
            continue
        next_no = no
        while next_no < len(lines) and not lines[next_no].strip():
            next_no += 1
        if next_no >= len(lines):
            continue
        if re.match(r"^\*{0,2}(สิ่งที่ต้องเตรียมหรือเงื่อนไขก่อนดำเนินการ|ลำดับขั้นตอนการปฏิบัติงาน)", lines[next_no].strip()):
            heading = line.strip().lstrip("#").strip()
            add(
                findings, "intro-paragraph", path, no,
                f"หัวข้อ “{heading}” ต้องมีย่อหน้าเกริ่นนำก่อนป้ายขั้นตอนแรก",
            )


def check_frontmatter_signature(path, lines, findings):
    if path.name != "00-frontmatter.md":
        return
    for no, line in enumerate(lines, 1):
        if re.match(r"^\s*\*\*ประธานสภานักเรียน\*\*\s*$", line):
            add(
                findings, "banned-term", path, no,
                "ห้ามใช้ “ประธานสภานักเรียน” เป็นบรรทัดลายเซ็นในคำนำ ให้ใช้ “ผู้จัดทำ”",
            )


def split_cells(row: str) -> list[str]:
    return [cell.strip() for cell in row.strip().strip("|").split("|")]


def count_source_questions(source: Path) -> int:
    try:
        text = source.read_text(encoding="utf-8-sig")
    except OSError:
        return -1
    return len(re.findall(r"^\*\*Q:", text, re.MULTILINE))


def check_faq_table(path, lines, findings):
    start = None
    for index, line in enumerate(lines):
        if FAQ_HEADING_RE.match(line):
            start = index
            break
    if start is None:
        add(findings, "faq-table", path, 1, "ไม่พบหัวข้อ 'แนวทางการแก้ไขปัญหาที่พบบ่อยในการใช้งาน'")
        return 0

    section = []
    for index in range(start + 1, len(lines)):
        if re.match(r"^##\s+", lines[index]):
            break
        section.append((index + 1, lines[index]))

    table_rows = [(no, line) for no, line in section if line.strip().startswith("|")]
    if len(table_rows) < 3:
        add(findings, "faq-table", path, start + 1, "ไม่พบตาราง FAQ")
        return 0

    header = split_cells(table_rows[0][1])
    if header != FAQ_HEADERS:
        add(
            findings, "faq-table", path, table_rows[0][0],
            f"หัวตารางไม่ถูกต้อง: {header} (คาดว่า {FAQ_HEADERS})",
        )

    data_rows = table_rows[2:]
    for no, row in data_rows:
        cells = split_cells(row)
        if len(cells) != 2:
            add(findings, "faq-table", path, no, "แถวตารางต้องมี 2 คอลัมน์")
        else:
            for cell in cells:
                if re.search(r"ขึ้น\s*/\s*ไม่ขึ้น", cell):
                    add(
                        findings, "faq-table", path, no,
                        "ใช้คำห้วน 'ขึ้น/ไม่ขึ้น' ต้องเขียนเต็มประโยค เช่น 'แสดงผล/ไม่แสดงผล'",
                    )
            answer = re.sub(r"`[^`]*`|\*\*|__", "", cells[1]).strip()
            if answer.startswith(("ไม่", "ได้", "เปิดได้")) and not answer.startswith(("ได้แก่", "ไม่มี")):
                add(
                    findings, "terse-faq", path, no,
                    f"คำตอบ FAQ ขึ้นต้นห้วน “{cells[1]}” ต้องเขียนเป็นประโยคเต็มความ",
                )

    for no, line in enumerate(lines, 1):
        if "**Q:" in line or "วิธีแก้:" in line:
            add(
                findings, "faq-table", path, no,
                "พบรูปแบบคำถามเดิมที่ยังไม่ได้แปลงเป็นตาราง",
            )
    return len(data_rows)


def check_source_parity(path, lines, faq_rows, findings):
    source_rel = CHAPTER_SOURCES.get(path.name)
    if source_rel is None:
        add(
            findings, "source-parity", path, 1,
            f"ไม่พบไฟล์ต้นฉบับในสารบัญตรวจสอบสำหรับ {path.name}",
        )
        return
    source = DOCS_ROOT / source_rel
    if not source.exists():
        add(findings, "source-parity", path, 1, f"ไม่พบต้นฉบับ {source_rel}")
        return
    src = source.read_text(encoding="utf-8-sig")

    src_images = len(IMAGE_RE.findall(src))
    out_images = sum(len(IMAGE_RE.findall(line)) for line in lines)
    if src_images != out_images:
        add(
            findings, "source-parity", path, 1,
            f"จำนวนภาพไม่ตรงต้นฉบับ: ต้นฉบับ {src_images} ภาพ แต่ไฟล์นี้มี {out_images} ภาพ",
        )

    src_boxes = len(re.findall(r"^:::[ \t]*\S", src, re.MULTILINE))
    out_boxes = sum(1 for line in lines if BOX_LABEL_RE.match(line))
    if src_boxes > out_boxes:
        add(
            findings, "source-parity", path, 1,
            f"กล่องคำแนะนำขาด: ต้นฉบับ {src_boxes} กล่อง แต่แปลงแล้วมี {out_boxes} กล่อง",
        )
    elif out_boxes > src_boxes:
        add(
            findings, "source-parity", path, 1,
            f"มีกล่องคำแนะนำเกินต้นฉบับ: ต้นฉบับ {src_boxes} กล่อง "
            f"แต่แปลงแล้วมี {out_boxes} กล่อง",
            "warning",
        )

    src_mermaid = src.count("```mermaid")
    out_placeholder = sum(1 for line in lines if FIG_PLACEHOLDER_RE.match(line))
    if src_mermaid > out_placeholder:
        add(
            findings, "source-parity", path, 1,
            f"แผนผังขาด: ต้นฉบับ {src_mermaid} แผนผัง แต่แปลงแล้วมี {out_placeholder} ที่",
        )

    src_h2 = len(re.findall(r"^##\s+", src, re.MULTILINE))
    out_h2 = len(re.findall(r"^##\s+", "\n".join(lines), re.MULTILINE))
    if out_h2 < src_h2:
        add(
            findings, "source-parity", path, 1,
            f"หัวข้อหลักขาด: ต้นฉบับ {src_h2} หัวข้อ แต่แปลงแล้วมี {out_h2} หัวข้อ",
        )

    src_q = count_source_questions(source)
    if src_q >= 0 and faq_rows != src_q:
        add(
            findings, "faq-table", path, 1,
            f"จำนวนแถว FAQ ไม่ตรงต้นฉบับ: ต้นฉบับ {src_q} ข้อ แต่ตารางมี {faq_rows} แถว",
        )


def collect_files(paths):
    files = []
    for raw in paths:
        target = Path(raw)
        if not target.is_absolute():
            target = Path.cwd() / target
        if target.is_dir():
            files.extend(sorted(target.rglob("*.md")))
        elif target.is_file():
            files.append(target)
        else:
            print(f"ไม่พบ path: {raw}", file=sys.stderr)
            return []
    return sorted({item.resolve() for item in files})


def main(argv=None):
    parser = argparse.ArgumentParser(description="ตรวจคุณภาพคู่มือภาษาทางการ")
    parser.add_argument(
        "paths",
        nargs="*",
        help="ไฟล์หรือโฟลเดอร์ Markdown (ค่าเริ่มต้น: reports/formal-manual)",
    )
    parser.add_argument("--strict", action="store_true", help="ให้ warning ถือเป็น error")
    parser.add_argument("--list-rules", action="store_true", help="แสดงรายการกฎทั้งหมด")
    args = parser.parse_args(argv)

    if args.list_rules:
        for rule, description in RULES.items():
            print(f"{rule}: {description}")
        return 0

    files = collect_files(args.paths or [str(DEFAULT_TARGET)])
    if not files:
        print("ไม่พบไฟล์ Markdown ที่ต้องตรวจ", file=sys.stderr)
        return 2

    findings = []
    file_lines = []
    for path in files:
        try:
            text = path.read_text(encoding="utf-8-sig")
        except OSError as exc:
            print(f"อ่านไฟล์ไม่ได้ {path}: {exc}", file=sys.stderr)
            return 2
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        lines = text.split("\n")
        file_lines.append((path, lines))
        check_emoji(path, lines, findings)
        check_thai_english_parens(path, lines, findings)
        check_banned_terms(path, lines, findings)
        check_ai_smell(path, lines, findings)
        check_vitepress_and_html(path, lines, findings)
        check_images_and_captions(path, lines, findings)
        if is_chapter_file(path):
            check_headings(path, lines, findings)
        check_heading_labels(path, lines, findings)
        check_cross_links(path, lines, findings)
        check_numbered_image_items(path, lines, findings)
        check_dash_lists(path, lines, findings)
        check_intro_paragraph(path, lines, findings)
        check_frontmatter_signature(path, lines, findings)
        if is_chapter_file(path):
            check_table_captions(path, lines, findings)
            faq_rows = check_faq_table(path, lines, findings)
            check_source_parity(path, lines, faq_rows, findings)

    errors = [item for item in findings if item.severity == "error"]
    warnings = [item for item in findings if item.severity == "warning"]
    for item in sorted(findings, key=lambda found: (str(found.path), found.line, found.rule)):
        label = "error" if item.severity == "error" else "warning"
        print(f"{relative(item.path)}:{item.line}: [{item.rule}] {label}: {item.message}")

    print(f"{len(files)} file(s), {len(errors)} error(s), {len(warnings)} warning(s)")
    print("\nสถิติไฟล์ (บรรทัด / อักขระ):")
    for path, lines in file_lines:
        chars = sum(len(line) for line in lines)
        print(f"  {relative(path)}: {len(lines)} บรรทัด, {chars} อักขระ")

    if errors or (args.strict and warnings):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
