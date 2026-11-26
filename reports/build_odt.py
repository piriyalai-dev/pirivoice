#!/usr/bin/env python3
"""สร้างคู่มือการใช้งานระบบ PIRIvoice เป็นไฟล์ OpenDocument (.odt) มาตรฐานรายงานราชการ

อ่านต้นฉบับ Markdown จาก reports/formal-manual/ (ส่วนหน้า, บทที่ 1–27, บรรณานุกรม)
พร้อมรูปจริงจาก docs/assets/screenshots/ และโลโก้ docs/public/logos/school-logo.png

ผลลัพธ์: reports/คู่มือการใช้งานระบบ_PIRIvoice.odt

การใช้งาน
  python3 reports/build_odt.py                     # สร้างไฟล์ + อัปเดตสารบัญด้วย LibreOffice (ถ้ามี)
  python3 reports/build_odt.py --skip-libreoffice  # สร้างไฟล์อย่างเดียว
  python3 reports/build_odt.py --skip-mermaid      # ไม่เรนเดอร์แผนผัง Mermaid (ใช้กล่องเส้นประ)
  python3 reports/build_odt.py --keep-temp         # เก็บไฟล์ชั่วคราวไว้ตรวจ

ต้องมี: python3-lxml, python3-pil (apt) · LibreOffice + python3-uno (เฉพาะขั้นอัปเดตสารบัญ)
ฟอนต์ TH Sarabun New จะถูกดาวน์โหลดอัตโนมัติไปที่ ~/.local/share/fonts
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

from PIL import Image

REPO = Path(__file__).resolve().parent.parent
SRC = REPO / 'reports' / 'formal-manual'
DOCS = REPO / 'docs'
OUT_ODT = REPO / 'reports' / 'คู่มือการใช้งานระบบ_PIRIvoice.odt'
OUT_PDF = REPO / 'reports' / 'คู่มือการใช้งานระบบ_PIRIvoice.pdf'
CACHE = Path.home() / '.cache' / 'pirivoice-odt'
FONT_DIR = Path.home() / '.local' / 'share' / 'fonts'

FONT = 'TH Sarabun New'
MONO = 'DejaVu Sans Mono'

# --- ตัวเลขหน้ากระดาษ -------------------------------------------------------
PAGE_W, PAGE_H = 21.0, 29.7
M_LEFT, M_RIGHT, M_TOP, M_BOTTOM = 3.81, 2.54, 2.54, 2.54
TEXT_W = PAGE_W - M_LEFT - M_RIGHT          # 14.65 cm
PX2CM = 1 / (2 * 37.7955)                    # สมมติแคปหน้าจอ 2x DPR

COLOUR_WARN, COLOUR_WARN_BG = '#8A1C1C', '#FDF2F2'
COLOUR_TIP, COLOUR_TIP_BG = '#1F4D36', '#F0F7F2'
COLOUR_RULE = '#BFBFBF'
COLOUR_HEAD_BG = '#F2F2F2'

BOOKS = [
    ('01-user-guide', 'ภาคที่ 1', 'คู่มือการใช้งานสำหรับนักเรียน',
     'ว่าด้วยการใช้งานระบบของนักเรียนและผู้ใช้งานทั่วไป'),
    ('02-staff-operations', 'ภาคที่ 2', 'คู่มือการปฏิบัติงานของเจ้าหน้าที่สภานักเรียน',
     'ว่าด้วยการปฏิบัติงานของหัวหน้าห้องและคณะกรรมการสภานักเรียน'),
    ('03-admin-guide', 'ภาคที่ 3', 'คู่มือสำหรับครูที่ปรึกษาและผู้ดูแลระบบ',
     'ว่าด้วยการบริหารจัดการระบบของครูที่ปรึกษาและผู้ดูแลระบบ'),
]

STEP_LABELS = {
    'เส้นทางการเข้าถึงเมนู',
    'สิ่งที่ต้องเตรียมหรือเงื่อนไขก่อนดำเนินการ',
    'ลำดับขั้นตอนการปฏิบัติงาน',
    'ผลลัพธ์การทำงานของระบบ',
}

# Mermaid: หมายเลขภาพ -> ไฟล์ต้นฉบับใน docs/
MERMAID_SOURCES = {
    '6.8': 'docs/1-user-guide/issue-reporting-tracking.md',
    '12.13': 'docs/2-staff-operations/issue-management-sop.md',
    '13.7': 'docs/2-staff-operations/event-management-scanner.md',
    '15.4': 'docs/2-staff-operations/content-moderation.md',
    '17.3': 'docs/2-staff-operations/student-import.md',
    '19.2': 'docs/2-staff-operations/student-promotion.md',
    '20.2': 'docs/2-staff-operations/reassignment-and-reconciliation.md',
    '26.8': 'docs/3-admin-guide/dashboard-and-reports.md',
}

IMG_RE = re.compile(r'^!\[([^\]]*)\]\(([^)]+)\)\s*$')
PLACEHOLDER_RE = re.compile(r'^\s*>\s*\*\*\[(แทรกภาพที่ ([0-9]+\.[0-9]+)\s*:?[^\]]*)\]\*\*\s*$')
CAPTION_RE = re.compile(r'^\*\*(ภาพที่ [0-9]+\.[0-9]+)\*\*\s*(.*)$')
TBL_CAP_RE = re.compile(r'^\*\*(ตารางที่ [0-9]+\.[0-9]+)\*\*\s*(.*)$')
BOX_RE = re.compile(r'^>\s*\*\*(ข้อแนะนำในการใช้งาน|ข้อควรระวังสำคัญ|ข้อสังเกต):\*\*\s*(.*)$')
OL_RE = re.compile(r'^\d+\.\s+(.*)$')
UL_RE = re.compile(r'^-\s+(.*)$')
HEAD_RE = re.compile(r'^(#{1,4})\s+(.*)$')
BOLD_ONLY_RE = re.compile(r'^\*\*(.+)\*\*$')


# ===========================================================================
# ยูทิลิตี
# ===========================================================================
def e(text: str) -> str:
    """escape ข้อความสำหรับ XML content"""
    return xml_escape(text, {'"': '&quot;'})


def cm(v: float) -> str:
    return f'{v:.3f}cm'


def inline(text: str) -> str:
    """แปลง **ตัวหนา** และ `โค้ด` เป็น text:span"""
    text = e(text)
    out = []
    for part in re.split(r'(`[^`]+`)', text):
        if len(part) > 2 and part.startswith('`') and part.endswith('`'):
            out.append(f'<text:span text:style-name="CodeChar">{part[1:-1]}</text:span>')
            continue
        for piece in re.split(r'(\*\*.+?\*\*)', part):
            if len(piece) > 4 and piece.startswith('**') and piece.endswith('**'):
                out.append(f'<text:span text:style-name="StrongChar">{piece[2:-2]}</text:span>')
            else:
                out.append(piece)
    return ''.join(out)


def tprops(size: float, bold: bool = False, italic: bool = False,
           color: str | None = None, font: str | None = None,
           bg: str | None = None) -> str:
    """text-properties ครบทั้ง Western และ Complex Script (บังคับสำหรับภาษาไทย)"""
    f = font or FONT
    w = 'bold' if bold else 'normal'
    parts = [
        f'style:font-name="{f}"', f'fo:font-family="&apos;{f}&apos;"',
        f'fo:font-size="{size:g}pt"', f'fo:font-weight="{w}"',
        f'style:font-name-complex="{f}"', f'fo:font-family-complex="&apos;{f}&apos;"',
        f'style:font-size-complex="{size:g}pt"', f'style:font-weight-complex="{w}"',
        'fo:language="th"', 'fo:country="TH"',
        'style:language-asian="th"', 'style:country-asian="TH"',
        'style:language-complex="th"', 'style:country-complex="TH"',
        'fo:hyphenate="false"',
    ]
    if italic:
        parts += ['fo:font-style="italic"', 'style:font-style-asian="italic"',
                  'style:font-style-complex="italic"']
    if color:
        parts += [f'fo:color="{color}"', f'style:color-asian="{color}"',
                  f'style:color-complex="{color}"']
    if bg:
        parts += [f'fo:background-color="{bg}"']
    return ' '.join(parts)


def pstyle(name: str, *, parent: str = 'Standard', para: str = '', text: str = '',
           master: str | None = None, outline: int | None = None,
           children: str = '') -> str:
    attrs = f'style:name="{name}" style:family="paragraph"'
    if parent:
        attrs += f' style:parent-style-name="{parent}"'
    if master:
        attrs += f' style:master-page-name="{master}"'
    if outline is not None:
        attrs += f' style:default-outline-level="{outline}"'
    s = f'<style:style {attrs}>'
    if children:
        s += f'<style:paragraph-properties {para}>{children}</style:paragraph-properties>'
    elif para:
        s += f'<style:paragraph-properties {para}/>'
    if text:
        s += f'<style:text-properties {text}/>'
    return s + '</style:style>'


def tab_stops() -> str:
    return ('<style:tab-stops>'
            f'<style:tab-stop style:position="{cm(TEXT_W)}" style:type="right" '
            'style:leader-style="dotted" style:leader-text="."/>'
            '</style:tab-stops>')


# ===========================================================================
# ฟอนต์
# ===========================================================================
FONT_SOURCES = {
    'regular': [
        ('THSarabunNew.ttf', 'https://raw.githubusercontent.com/epsilonxe/SIPAFonts/master/THSarabunNew.ttf'),
        ('THSarabunNew.ttf', 'https://raw.githubusercontent.com/inwdragon/thsn-for-ubuntu/master/THSarabunNew.ttf'),
    ],
    'bold': [
        ('THSarabunNew Bold.ttf', 'https://raw.githubusercontent.com/epsilonxe/SIPAFonts/master/THSarabunNew%20Bold.ttf'),
        ('THSarabunNew Bold.ttf', 'https://raw.githubusercontent.com/inwdragon/thsn-for-ubuntu/master/THSarabunNew%20Bold.ttf'),
    ],
}
SARABUN_FALLBACK = {
    'regular': ('Sarabun-Regular.ttf', 'https://cdn.jsdelivr.net/gh/google/fonts@main/ofl/sarabun/Sarabun-Regular.ttf'),
    'bold': ('Sarabun-Bold.ttf', 'https://cdn.jsdelivr.net/gh/google/fonts@main/ofl/sarabun/Sarabun-Bold.ttf'),
}


def _download(url: str, dst: Path) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=60) as r:
            data = r.read()
        if len(data) < 50_000:
            return False
        dst.write_bytes(data)
        return True
    except Exception:
        return False


def ensure_fonts() -> str:
    """ติดตั้งฟอนต์ไทยให้ fontconfig คืนชื่อ family ที่ใช้จริง"""
    global FONT
    FONT_DIR.mkdir(parents=True, exist_ok=True)
    have = subprocess.run(['fc-list', ':family'], capture_output=True, text=True).stdout
    if 'TH Sarabun New' in have and list(FONT_DIR.glob('THSarabunNew*')):
        return FONT

    ok = True
    for weight, sources in FONT_SOURCES.items():
        dst = FONT_DIR / sources[0][0]
        if dst.exists():
            continue
        if not any(_download(url, dst) for name, url in sources if name == dst.name):
            ok = False
            break
    if ok:
        subprocess.run(['fc-cache', '-f', str(FONT_DIR)], capture_output=True)
        fam = subprocess.run(['fc-query', '--format', '%{family}', str(FONT_DIR / 'THSarabunNew.ttf')],
                             capture_output=True, text=True).stdout
        if 'TH Sarabun New' in fam:
            print('ฟอนต์: TH Sarabun New (ติดตั้งแล้ว)')
            return FONT
        ok = False

    # แผนสำรอง: Google Fonts “Sarabun”
    print('คำเตือน: ดาวน์โหลด TH Sarabun New ไม่สำเร็จ — ใช้ฟอนต์ Sarabun แทน', file=sys.stderr)
    for weight, (name, url) in SARABUN_FALLBACK.items():
        dst = FONT_DIR / name
        if not dst.exists():
            _download(url, dst)
    subprocess.run(['fc-cache', '-f', str(FONT_DIR)], capture_output=True)
    FONT = 'Sarabun'
    return FONT


# ===========================================================================
# รูปภาพ
# ===========================================================================
@dataclass
class Asset:
    name: str          # ชื่อไฟล์ใน Pictures/
    path: Path         # ไฟล์ PNG จริง
    w: int
    h: int


def figure_size(w: int, h: int) -> tuple[float, float]:
    """คืนขนาด (ซม.) โดยรักษาสัดส่วนและไม่เกินกรอบที่กำหนด"""
    portrait = h > w
    max_w, max_h = (10.0, 8.0) if portrait else (14.0, 9.5)
    nat_w, nat_h = w * PX2CM, h * PX2CM
    scale = min(max_w / nat_w, max_h / nat_h)
    return nat_w * scale, nat_h * scale


def stage_images(tmpdir: Path) -> dict[Path, Asset]:
    assets: dict[Path, Asset] = {}
    idx = 0
    for md in sorted(SRC.rglob('*.md')):
        for m in re.finditer(r'!\[[^\]]*\]\(([^)]+)\)', md.read_text(encoding='utf-8')):
            target = m.group(1)
            if target.startswith('http'):
                continue
            src = (md.parent / target).resolve()
            if src in assets or not src.exists():
                continue
            idx += 1
            name = f'img{idx:04d}.png'
            dst = tmpdir / name
            with Image.open(src) as im:
                if im.mode in ('RGBA', 'LA', 'P'):
                    im = im.convert('RGBA')
                    bg = Image.new('RGB', im.size, 'white')
                    bg.paste(im, mask=im.split()[-1])
                    im = bg
                else:
                    im = im.convert('RGB')
                im.save(dst, 'PNG', optimize=True)
                assets[src] = Asset(name, dst, im.width, im.height)
    return assets


# ===========================================================================
# Mermaid → PNG ผ่าน playwright + chromium
# ===========================================================================
RENDER_JS = r"""
const { chromium } = require('playwright');
(async () => {
  const [htmlPath, outPath] = process.argv.slice(2);
  const browser = await chromium.launch({
    executablePath: process.env.CHROME_PATH,
    args: ['--no-sandbox', '--disable-dev-shm-usage', '--font-render-hinting=none'],
  });
  const page = await browser.newPage({ viewport: { width: 1600, height: 1200 }, deviceScaleFactor: 2 });
  page.on('pageerror', err => console.error('pageerror:', err.message));
  await page.goto('file://' + htmlPath, { waitUntil: 'load' });
  await page.waitForSelector('#graph svg', { timeout: 45000 });
  await page.waitForTimeout(500);
  const el = await page.$('#graph');
  await el.screenshot({ path: outPath });
  await browser.close();
})().catch(err => { console.error(err); process.exit(1); });
"""


def find_chrome() -> Path | None:
    cands = sorted(Path.home().glob('.cache/ms-playwright/chromium-*/chrome-linux*/chrome'), reverse=True)
    return cands[0] if cands else None


def mermaid_js() -> Path | None:
    CACHE.mkdir(parents=True, exist_ok=True)
    js = CACHE / 'mermaid.min.js'
    if js.exists() and js.stat().st_size > 500_000:
        return js
    for url in ('https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js',
                'https://cdnjs.cloudflare.com/ajax/libs/mermaid/11.4.1/mermaid.min.js'):
        if _download(url, js):
            return js
    return None


def render_mermaid(tmpdir: Path, enabled: bool) -> dict[str, Asset]:
    """คืน map หมายเลขภาพ -> Asset (เฉพาะที่เรนเดอร์สำเร็จ)"""
    if not enabled:
        return {}
    chrome = find_chrome()
    js = mermaid_js()
    pw = REPO / 'frontend' / 'node_modules' / 'playwright'
    if not chrome or not js or not pw.exists():
        print('แจ้งเตือน: ไม่พบเครื่องมือเรนเดอร์ Mermaid — ใช้กล่องเส้นประ', file=sys.stderr)
        return {}

    render_js = tmpdir / 'render.js'
    render_js.write_text(RENDER_JS, encoding='utf-8')
    env = dict(os.environ, CHROME_PATH=str(chrome),
               NODE_PATH=str(REPO / 'frontend' / 'node_modules'))
    out: dict[str, Asset] = {}
    for num, rel in MERMAID_SOURCES.items():
        src = REPO / rel
        if not src.exists():
            continue
        m = re.search(r'```mermaid\n(.*?)```', src.read_text(encoding='utf-8'), re.S)
        if not m:
            continue
        code = m.group(1).strip()
        key = hashlib.sha1(code.encode()).hexdigest()[:12]
        png = CACHE / 'mermaid' / f'{key}.png'
        png.parent.mkdir(parents=True, exist_ok=True)
        if not png.exists():
            html = tmpdir / f'mermaid-{num}.html'
            html.write_text(
                '<!doctype html><html><head><meta charset="utf-8"><style>\n'
                "html,body{margin:0;background:#ffffff;font-family:'TH Sarabun New','Sarabun',sans-serif}\n"
                '#graph{display:inline-block;padding:28px;background:#ffffff}\n'
                '</style></head><body><div id="graph"><pre class="mermaid">'
                + xml_escape(code)
                + '</pre></div><script>'
                + js.read_text(encoding='utf-8')
                + '</script><script>mermaid.initialize({startOnLoad:true,theme:"default",'
                  'flowchart:{useMaxWidth:false,htmlLabels:true,curve:"basis"},'
                  'themeVariables:{fontFamily:"TH Sarabun New, Sarabun, sans-serif",fontSize:"20px"}});'
                  '</script></body></html>',
                encoding='utf-8')
            proc = subprocess.run(['node', str(render_js), str(html), str(png)],
                                  env=env, capture_output=True, text=True, cwd=str(REPO))
            if proc.returncode != 0 or not png.exists():
                print(f'แจ้งเตือน: เรนเดอร์ Mermaid ภาพที่ {num} ไม่สำเร็จ', file=sys.stderr)
                if proc.stderr.strip():
                    print('  ' + proc.stderr.strip().splitlines()[-1], file=sys.stderr)
                continue
        with Image.open(png) as im:
            out[num] = Asset(f'mermaid-{num}.png', png, im.width, im.height)
    return out


# ===========================================================================
# Parser: Markdown → block
# ===========================================================================
def parse_blocks(text: str) -> list[dict]:
    lines = text.splitlines()
    blocks: list[dict] = []
    i, n = 0, len(lines)
    while i < n:
        line = lines[i].rstrip()
        s = line.strip()
        if not s or s == '---':
            i += 1
            continue

        m = HEAD_RE.match(s)
        if m:
            blocks.append({'t': 'h', 'level': len(m.group(1)), 'text': m.group(2).strip()})
            i += 1
            continue

        m = IMG_RE.match(s)
        if m:
            cap = None
            if i + 1 < n:
                cm_ = CAPTION_RE.match(lines[i + 1].strip())
                if cm_:
                    cap = (cm_.group(1), cm_.group(2))
                    i += 1
            blocks.append({'t': 'fig', 'alt': m.group(1), 'src': m.group(2), 'cap': cap})
            i += 1
            continue

        m = PLACEHOLDER_RE.match(s)
        if m:
            cap = None
            for ahead in range(i + 1, min(i + 3, n)):
                cm_ = CAPTION_RE.match(lines[ahead].strip())
                if cm_:
                    cap = (cm_.group(1), cm_.group(2))
                    i = ahead
                    break
            blocks.append({'t': 'mermaid', 'text': m.group(1), 'num': m.group(2), 'cap': cap})
            i += 1
            continue

        m = BOX_RE.match(s)
        if m:
            blocks.append({'t': 'callout', 'label': m.group(1), 'body': m.group(2)})
            i += 1
            continue

        m = TBL_CAP_RE.match(s)
        if m:
            prev = i - 1
            while prev >= 0 and not lines[prev].strip():
                prev -= 1
            below_table = prev >= 0 and lines[prev].lstrip().startswith('|')
            j = i + 1
            while j < n and not lines[j].strip():
                j += 1
            if not below_table and j < n and lines[j].lstrip().startswith('|'):
                i = j
                rows = []
                while i < n and lines[i].lstrip().startswith('|'):
                    rows.append(lines[i].strip())
                    i += 1
                blocks.append({'t': 'table', 'cap': (m.group(1), m.group(2)), 'rows': rows})
                continue
            blocks.append({'t': 'para', 'text': s})
            i += 1
            continue

        if s.startswith('|'):
            rows = []
            while i < n and lines[i].lstrip().startswith('|'):
                rows.append(lines[i].strip())
                i += 1
            blocks.append({'t': 'table', 'cap': None, 'rows': rows})
            continue

        m = OL_RE.match(s)
        if m:
            items = []
            while i < n and OL_RE.match(lines[i].strip()):
                items.append(OL_RE.match(lines[i].strip()).group(1))
                i += 1
            blocks.append({'t': 'ol', 'items': items})
            continue

        m = UL_RE.match(s)
        if m:
            items = []
            while i < n and UL_RE.match(lines[i].strip()):
                items.append(UL_RE.match(lines[i].strip()).group(1))
                i += 1
            blocks.append({'t': 'ul', 'items': items})
            continue

        para = [s]
        i += 1
        while i < n:
            nxt = lines[i].strip()
            if (not nxt or nxt == '---' or nxt.startswith('#') or IMG_RE.match(nxt)
                    or PLACEHOLDER_RE.match(nxt) or BOX_RE.match(nxt)
                    or OL_RE.match(nxt) or UL_RE.match(nxt)
                    or nxt.startswith('|') or TBL_CAP_RE.match(nxt)
                    or CAPTION_RE.match(nxt)):
                break
            para.append(nxt)
            i += 1
        blocks.append({'t': 'para', 'text': ' '.join(para)})
    return blocks


def split_sections(blocks: list[dict]) -> list[dict]:
    sections: list[dict] = []
    cur = None
    for b in blocks:
        if b['t'] == 'h' and b['level'] == 1:
            cur = {'title': b['text'], 'blocks': []}
            sections.append(cur)
        elif cur is not None:
            cur['blocks'].append(b)
    return sections


# ===========================================================================
# ตัวสร้าง XML: ย่อหน้า / หัวข้อ / ตาราง / กล่องหมายเหตุ
# ===========================================================================
class Doc:
    def __init__(self, shared: dict | None = None) -> None:
        self.parts: list[str] = []
        self.figures: list[str] = []    # ข้อความคำบรรยายภาพ ตามลำดับเอกสาร
        self.tables: list[str] = []
        self.outline: list[tuple[int, str]] = []
        # ตัวนับและความกว้างคอลัมน์ใช้ร่วมกันทั้งเอกสาร (ชื่อตาราง/ภาพต้องไม่ซ้ำ)
        self.shared = shared if shared is not None else {'table': 0, 'frame': 0, 'pic': 0, 'widths': {}}
        self.table_widths = self.shared['widths']

    @property
    def n_table(self) -> int:
        return self.shared['table']

    @n_table.setter
    def n_table(self, v: int) -> None:
        self.shared['table'] = v

    @property
    def n_frame(self) -> int:
        return self.shared['frame']

    @n_frame.setter
    def n_frame(self, v: int) -> None:
        self.shared['frame'] = v

    @property
    def n_pic(self) -> int:
        return self.shared['pic']

    @n_pic.setter
    def n_pic(self, v: int) -> None:
        self.shared['pic'] = v

    def p(self, style: str, inner: str = '', extra: str = '') -> None:
        self.parts.append(f'<text:p text:style-name="{style}"{extra}>{inner}</text:p>')

    def h(self, level: int, style: str, text: str) -> None:
        self.outline.append((level, text))
        self.parts.append(f'<text:h text:outline-level="{level}" text:style-name="{style}">'
                          f'{e(text)}</text:h>')

    def figure(self, asset: Asset, caption: str | None) -> None:
        w, h = figure_size(asset.w, asset.h)
        self.n_frame += 1
        self.n_pic += 1
        self.parts.append(
            f'<text:p text:style-name="FigureImage">'
            f'<draw:frame draw:style-name="FrameFigure" draw:name="Image{self.n_frame}" '
            f'text:anchor-type="as-char" svg:width="{cm(w)}" svg:height="{cm(h)}" draw:z-index="0">'
            f'<draw:image xlink:href="Pictures/{asset.name}" xlink:type="simple" '
            f'xlink:show="embed" xlink:actuate="onLoad"/>'
            f'</draw:frame></text:p>')
        if caption:
            num, desc = caption
            self.figures.append(f'{num} {desc}'.strip())
            self.parts.append(f'<text:p text:style-name="FigureCaption">'
                              f'<text:span text:style-name="StrongChar">{e(num)}</text:span> {inline(desc)}'
                              f'</text:p>')

    def placeholder(self, text: str, caption: str | None) -> None:
        self.parts.append(f'<text:p text:style-name="FigurePlaceholder">{inline(text)}</text:p>')
        if caption:
            num, desc = caption
            self.figures.append(f'{num} {desc}'.strip())
            self.parts.append(f'<text:p text:style-name="FigureCaption">'
                              f'<text:span text:style-name="StrongChar">{e(num)}</text:span> {inline(desc)}'
                              f'</text:p>')

    def table(self, rows: list[str], caption: tuple[str, str] | None) -> None:
        if caption:
            num, desc = caption
            self.tables.append(f'{num} {desc}'.strip())
            self.parts.append(f'<text:p text:style-name="TableCaption">'
                              f'<text:span text:style-name="StrongChar">{e(num)}</text:span> {inline(desc)}'
                              f'</text:p>')
        header = [c.strip() for c in rows[0].strip().strip('|').split('|')]
        body = [[c.strip() for c in r.strip().strip('|').split('|')] for r in rows[2:]]
        ncol = max([len(header)] + [len(r) for r in body] or [1]) or 1

        # ความกว้างคอลัมน์
        if ncol == 2:
            weights = [38.0, 62.0]
        else:
            longest = [0.0] * ncol
            for r in [header] + body:
                for k in range(min(len(r), ncol)):
                    longest[k] = max(longest[k], len(r[k]))
            total = sum(longest) or 1
            weights = [max(18.0, 100.0 * v / total) for v in longest]
        scale = 100.0 / sum(weights)
        widths = [w * scale for w in weights]

        self.n_table += 1
        name = f'Table{self.n_table}'
        width_cm = [w * TEXT_W / 100.0 for w in widths]
        self.table_widths[name] = width_cm
        out = [f'<table:table table:name="{name}" table:style-name="TableMain">']
        for k in range(ncol):
            out.append(f'<table:table-column table:style-name="{name}.Col{k}" '
                       'table:number-columns-repeated="1"/>')
        out.append('<table:table-header-rows><table:table-row table:style-name="RowKeep">')
        for k in range(ncol):
            txt = header[k] if k < len(header) else ''
            out.append(f'<table:table-cell table:style-name="CellHead" office:value-type="string">'
                       f'<text:p text:style-name="TableHeadText">{inline(txt)}</text:p></table:table-cell>')
        out.append('</table:table-row></table:table-header-rows>')
        for row in body:
            out.append('<table:table-row table:style-name="RowKeep">')
            for k in range(ncol):
                txt = row[k] if k < len(row) else ''
                out.append(f'<table:table-cell table:style-name="CellBody" office:value-type="string">'
                           f'<text:p text:style-name="TableText">{inline(txt)}</text:p></table:table-cell>')
            out.append('</table:table-row>')
        out.append('</table:table>')
        self.parts.append(''.join(out))

    def callout(self, kind: str, label: str, body: str) -> None:
        """กล่องหมายเหตุแบบเอกสารราชการ: ย่อหน้าธรรมดา พื้นขาว ไม่มีแถบสี"""
        self.parts.append(
            '<text:p text:style-name="CalloutPlain">'
            '<text:span text:style-name="StrongChar">%s:</text:span> %s'
            '</text:p>' % (e(label), inline(body)))

    def ol(self, items: list[str]) -> None:
        self.parts.append('<text:list text:style-name="LNumber">')
        for it in items:
            self.parts.append(f'<text:list-item><text:p text:style-name="ListParagraph">{inline(it)}</text:p></text:list-item>')
        self.parts.append('</text:list>')

    def ul(self, items: list[str]) -> None:
        self.parts.append('<text:list text:style-name="LBullet">')
        for it in items:
            self.parts.append(f'<text:list-item><text:p text:style-name="ListParagraph">{inline(it)}</text:p></text:list-item>')
        self.parts.append('</text:list>')

    def blocks(self, blocks: list[dict], md_dir: Path, assets: dict[Path, Asset],
               mermaid: dict[str, Asset]) -> None:
        for b in blocks:
            t = b['t']
            if t == 'para':
                text = b['text']
                m = BOLD_ONLY_RE.match(text.strip())
                if m and m.group(1).strip() in STEP_LABELS:
                    self.p('StepLabel', e(m.group(1).strip()))
                else:
                    self.p('BodyText', inline(text))
            elif t == 'fig':
                src = (md_dir / b['src']).resolve()
                asset = assets.get(src)
                if asset:
                    self.figure(asset, b['cap'])
                elif b['cap']:
                    self.placeholder(f'[แทรก{b["cap"][0]}]', b['cap'])
            elif t == 'mermaid':
                asset = mermaid.get(b['num'])
                if asset:
                    self.figure(asset, b['cap'])
                else:
                    self.placeholder(b['text'], b['cap'])
            elif t == 'table':
                self.table(b['rows'], b['cap'])
            elif t == 'callout':
                kind = 'warn' if b['label'] in ('ข้อควรระวังสำคัญ', 'ข้อสังเกต') else 'tip'
                self.callout(kind, b['label'], b['body'])
            elif t == 'ol':
                self.ol(b['items'])
            elif t == 'ul':
                self.ul(b['items'])
            elif t == 'h':
                # ระดับหัวข้อถูกแมปโดยผู้เรียก (ตามบริบทบท/ส่วนหน้า)
                self.h(b['level'], f'Heading{min(b["level"], 4)}', b['text'])


# ===========================================================================
# styles.xml
# ===========================================================================
def page_layouts() -> str:
    out = []
    for name, numfmt, hdr in (
        ('PLCover', '1', False),
        ('PLFrontmatter', 'ก, ข, ค, ...', True),
        ('PLPartDivider', '1', False),
        ('PLBody', '1', True),
    ):
        s = (f'<style:page-layout style:name="{name}">'
             f'<style:page-layout-properties style:num-format="{numfmt}" '
             f'fo:page-width="{cm(PAGE_W)}" fo:page-height="{cm(PAGE_H)}" '
             f'fo:margin-top="{cm(M_TOP)}" fo:margin-bottom="{cm(M_BOTTOM)}" '
             f'fo:margin-left="{cm(M_LEFT)}" fo:margin-right="{cm(M_RIGHT)}" '
             f'style:print-orientation="portrait" style:writing-mode="lr-tb"/>')
        if hdr:
            s += ('<style:header-style><style:header-footer-properties fo:min-height="0.5cm" '
                  'fo:margin-bottom="0.3cm"/></style:header-style>')
        s += '</style:page-layout>'
        out.append(s)
    return ''.join(out)


def master_pages() -> str:
    def hdr(style):
        return (f'<style:header><text:p text:style-name="{style}">'
                '<text:page-number text:select-page="current"/></text:p></style:header>')

    return (
        '<style:master-page style:name="PageCover" style:page-layout-name="PLCover"/>'
        '<style:master-page style:name="PageFrontmatter" style:page-layout-name="PLFrontmatter">'
        + hdr('HeaderRight') + '</style:master-page>'
        '<style:master-page style:name="PagePartDivider" style:page-layout-name="PLPartDivider"/>'
        '<style:master-page style:name="PageBody" style:page-layout-name="PLBody">'
        + hdr('HeaderRight') + '</style:master-page>'
    )


def paragraph_styles() -> str:
    S = []
    S.append('<style:default-style style:family="paragraph">'
             f'<style:paragraph-properties fo:line-height="100%" fo:text-align="justify" '
             'style:justify-single-word="false"/>'
             f'<style:text-properties {tprops(16)}/>'
             '</style:default-style>')
    S.append(pstyle('Standard', text=tprops(16)))
    S.append(pstyle('BodyText', para=(
        'fo:text-align="justify" fo:text-indent="1.25cm" fo:margin-bottom="0.15cm" '
        'fo:line-height="100%" style:justify-single-word="false" style:auto-text-indent="false"'), text=tprops(16)))
    S.append(pstyle('BodyTextNoIndent', parent='BodyText',
                    para='fo:text-indent="0cm" style:auto-text-indent="false"', text=tprops(16)))
    S.append(pstyle('ListParagraph', para=(
        'fo:text-align="left" fo:margin-left="0cm" fo:margin-bottom="0.08cm" '
        'fo:line-height="100%" fo:text-indent="0cm" style:auto-text-indent="false"'), text=tprops(16)))
    S.append(pstyle('StepLabel', para=(
        'fo:keep-with-next="always" fo:margin-top="0.25cm" fo:margin-bottom="0.08cm" '
        'fo:text-align="left" fo:text-indent="0cm" style:auto-text-indent="false"'), text=tprops(16, bold=True)))
    S.append(pstyle('Signature', para=(
        'fo:text-align="center" fo:margin-top="0.15cm" fo:margin-bottom="0cm" '
        'fo:text-indent="0cm" style:auto-text-indent="false"'), text=tprops(16, bold=True)))
    S.append(pstyle('PrefaceText', parent='BodyText', para=(
        'fo:text-align="justify" fo:text-indent="1.25cm" fo:margin-bottom="0.05cm" '
        'fo:line-height="90%" style:auto-text-indent="false"'), text=tprops(16)))

    # Heading 1
    h1_text = tprops(18, bold=True)
    S.append(pstyle('Heading1', parent='Standard', outline=1, para=(
        'fo:break-before="page" fo:keep-with-next="always" fo:margin-top="0cm" '
        'fo:margin-bottom="0.35cm" fo:text-align="left"'), text=h1_text))
    S.append(pstyle('Heading1Front', parent='Heading1', master='PageFrontmatter',
                    outline=1, para=(
                        'fo:break-before="page" fo:keep-with-next="always" fo:margin-top="0cm" '
                        'fo:margin-bottom="0.35cm" fo:text-align="center"'), text=h1_text))
    S.append(pstyle('Heading1FrontStart', parent='Heading1Front', master='PageFrontmatter',
                    outline=1, para=(
                        'fo:break-before="page" style:page-number="1" fo:keep-with-next="always" '
                        'fo:margin-top="0cm" fo:margin-bottom="0.35cm" fo:text-align="center"'), text=h1_text))
    S.append(pstyle('Heading1Part', parent='Heading1',
                    outline=1, para=(
                        'fo:break-before="auto" fo:keep-with-next="always" fo:margin-top="0cm" '
                        'fo:margin-bottom="0.4cm" fo:text-align="center"'),
                    text=tprops(22, bold=True)))
    S.append(pstyle('PartSpacer', parent='Heading1', master='PagePartDivider',
                    para=('fo:break-before="page" fo:margin-top="7.5cm" fo:margin-bottom="0cm" '
                          'fo:line-height="100%"'), text=tprops(16)))
    S.append(pstyle('PartSpacerFirst', parent='PartSpacer', master='PagePartDivider',
                    para=('fo:break-before="page" style:page-number="1" fo:margin-top="7.5cm" '
                          'fo:margin-bottom="0cm" fo:line-height="100%"'), text=tprops(16)))
    S.append(pstyle('PartSubtitle', parent='Standard',
                    para=('fo:break-before="auto" fo:margin-top="0.2cm" fo:margin-bottom="0cm" '
                          'fo:text-align="center" fo:text-indent="0cm" style:auto-text-indent="false"'),
                    text=tprops(16)))
    S.append(pstyle('Heading1Body', parent='Heading1', master='PageBody', outline=1,
                    para=('fo:break-before="page" fo:keep-with-next="always" fo:margin-top="0cm" '
                          'fo:margin-bottom="0.35cm" fo:text-align="left"'), text=h1_text))

    # Heading 2–4
    S.append(pstyle('Heading2', parent='Standard', master='PageBody', outline=2, para=(
        'fo:break-before="page" fo:keep-with-next="always" fo:margin-top="0cm" '
        'fo:margin-bottom="0.35cm" fo:text-align="left"'), text=tprops(18, bold=True)))
    S.append(pstyle('Heading3', parent='Standard', outline=3, para=(
        'fo:keep-with-next="always" fo:margin-top="0.35cm" fo:margin-bottom="0.15cm" '
        'fo:text-align="left"'), text=tprops(16, bold=True)))
    S.append(pstyle('Heading4', parent='Standard', outline=4, para=(
        'fo:keep-with-next="always" fo:margin-top="0.25cm" fo:margin-bottom="0.10cm" '
        'fo:text-align="left"'), text=tprops(16, bold=True)))

    # รูปและคำบรรยาย
    S.append(pstyle('FigureImage', para=(
        'fo:text-align="center" fo:keep-with-next="always" fo:margin-top="0.25cm" '
        'fo:margin-bottom="0.1cm" fo:text-indent="0cm" style:auto-text-indent="false"'), text=tprops(16)))
    S.append(pstyle('FigureCaption', para=(
        'fo:text-align="center" fo:margin-bottom="0.35cm" fo:line-height="100%" '
        'fo:keep-together="always" fo:text-indent="0cm" style:auto-text-indent="false"'), text=tprops(16)))
    S.append(pstyle('FigurePlaceholder', para=(
        'fo:text-align="center" fo:keep-with-next="always" fo:margin-top="0.25cm" '
        f'fo:margin-bottom="0.1cm" fo:padding="0.3cm" fo:border="0.6pt dashed #B9A98E" '
        'fo:background-color="#FAF6EE" fo:text-indent="0cm" style:auto-text-indent="false"'),
        text=tprops(14, color='#6B5A3E')))
    S.append(pstyle('TableCaption', para=(
        'fo:text-align="left" fo:keep-with-next="always" fo:margin-top="0.2cm" '
        'fo:margin-bottom="0.15cm" fo:text-indent="0cm" style:auto-text-indent="false"'), text=tprops(16)))
    S.append(pstyle('CalloutPlain', para=(
        'fo:text-align="left" fo:margin-top="0.2cm" fo:margin-bottom="0.2cm" '
        'fo:margin-left="1.25cm" fo:keep-together="always" fo:line-height="100%" '
        'fo:text-indent="0cm" style:auto-text-indent="false"'), text=tprops(16)))

    # ตาราง
    S.append(pstyle('TableText', parent='Standard', para=(
        'fo:text-align="left" fo:line-height="105%" fo:margin="0cm" '
        'fo:text-indent="0cm" style:auto-text-indent="false"'), text=tprops(14)))
    S.append(pstyle('TableHeadText', parent='TableText',
                    text=tprops(14, bold=True)))

    # ปก
    # หมายเหตุ: LO ถือว่า style:master-page-name บนสไตล์ย่อหน้า = สั่งขึ้นหน้าใหม่
    # จึงกำหนด master เฉพาะย่อหน้าแรกของแต่ละหน้า (ที่มี fo:break-before) เท่านั้น
    S.append(pstyle('CoverLogo', master='PageCover',
                    para='fo:text-align="center" fo:margin-top="1.6cm" fo:margin-bottom="0.6cm"',
                    text=tprops(16)))
    S.append(pstyle('CoverLogo2', parent='CoverLogo', master='PageCover',
                    para=('fo:break-before="page" fo:text-align="center" fo:margin-top="1.6cm" '
                          'fo:margin-bottom="0.6cm"'), text=tprops(16)))
    S.append(pstyle('CoverBase', parent='Standard',
                    para=('fo:text-align="center" fo:text-indent="0cm" '
                          'style:auto-text-indent="false"'), text=tprops(16)))
    S.append(pstyle('CoverTitle', parent='CoverBase',
                    para='fo:margin-bottom="0.35cm"', text=tprops(32, bold=True)))
    S.append(pstyle('CoverSubtitle', parent='CoverBase',
                    para='fo:margin-bottom="0.6cm"', text=tprops(22)))
    S.append(pstyle('CoverBy', parent='CoverBase',
                    para='fo:margin-top="1.6cm" fo:margin-bottom="0.1cm"',
                    text=tprops(22, bold=True)))
    S.append(pstyle('CoverName', parent='CoverBase',
                    para='fo:margin-bottom="0.7cm"', text=tprops(22, bold=True)))
    S.append(pstyle('CoverText', parent='CoverBase',
                    para='fo:margin-bottom="0.15cm"', text=tprops(18)))
    S.append(pstyle('CoverFooter', parent='CoverBase',
                    para='fo:margin-top="0.8cm" fo:margin-bottom="0cm"',
                    text=tprops(18, bold=True)))
    S.append(pstyle('CoverBlank', parent='CoverBase', master='PageCover',
                    para='fo:break-before="page"', text=tprops(16)))
    S.append(pstyle('BackBlank', parent='CoverBase', master='PageCover',
                    para='fo:break-before="page"', text=tprops(16)))

    # หัวเรื่องส่วนหน้า (ไม่มี outline level → ไม่เข้าสารบัญ)
    S.append(pstyle('FrontTitle', parent='CoverBase', master='PageCover',
                    para=('fo:break-before="page" fo:margin-top="0cm" fo:margin-bottom="0.6cm"'),
                    text=tprops(18, bold=True)))
    S.append(pstyle('FrontHeading', parent='CoverBase', para='fo:break-before="auto"'))

    # สารบัญ
    S.append(pstyle('ContentsHeading', parent='Standard', para=(
        'fo:text-align="center" fo:margin-bottom="0.4cm" fo:text-indent="0cm" '
        'style:auto-text-indent="false"'), text=tprops(20, bold=True)))
    for lvl, indent in ((1, 0.0), (2, 0.6), (3, 1.2), (4, 1.8)):
        S.append(pstyle(f'Contents{lvl}', parent='Standard',
                        para=(f'fo:margin-left="{cm(indent)}" fo:margin-bottom="0.05cm" '
                              'fo:text-align="left" fo:text-indent="0cm" '
                              'style:auto-text-indent="false"'),
                        children=tab_stops(), text=tprops(15)))
    S.append(pstyle('FigureIndexEntry', parent='Standard',
                    para=('fo:margin-bottom="0.05cm" fo:text-align="left" fo:text-indent="0cm" '
                          'style:auto-text-indent="false"'),
                    children=tab_stops(), text=tprops(15)))
    S.append(pstyle('TableIndexEntry', parent='FigureIndexEntry'))

    # หัวกระดาษ
    S.append(pstyle('HeaderRight', para='fo:text-align="right" fo:margin="0cm"', text=tprops(16)))
    return ''.join(S)


def text_styles() -> str:
    return (
        f'<style:style style:name="StrongChar" style:family="text">'
        f'<style:text-properties {tprops(16, bold=True)}/></style:style>'
        f'<style:style style:name="CodeChar" style:family="text">'
        f'<style:text-properties {tprops(14, font=MONO, bg="#EDEDED")}/></style:style>'
        f'<style:style style:name="IndexLink" style:family="text">'
        f'<style:text-properties fo:color="#1A1A1A"/></style:style>'
    )


def list_styles() -> str:
    align = ('<style:list-level-properties text:list-level-position-and-space-mode="label-alignment">'
             '<style:list-level-label-alignment text:label-followed-by="listtab" '
             'fo:text-indent="-0.6cm" fo:margin-left="1.9cm"/>'
             '</style:list-level-properties>')
    return (
        '<text:list-style style:name="LNumber">'
        '<text:list-level-style-number text:level="1" style:num-format="1" style:num-suffix=".">'
        + align + '</text:list-level-style-number></text:list-style>'
        '<text:list-style style:name="LBullet">'
        '<text:list-level-style-bullet text:level="1" text:bullet-char="•">'
        + align + '</text:list-level-style-bullet></text:list-style>'
    )


NS_DECL = (
    'xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
    'xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0" '
    'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" '
    'xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0" '
    'xmlns:draw="urn:oasis:names:tc:opendocument:xmlns:drawing:1.0" '
    'xmlns:fo="urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0" '
    'xmlns:xlink="http://www.w3.org/1999/xlink" '
    'xmlns:dc="http://purl.org/dc/elements/1.1/" '
    'xmlns:meta="urn:oasis:names:tc:opendocument:xmlns:meta:1.0" '
    'xmlns:number="urn:oasis:names:tc:opendocument:xmlns:datastyle:1.0" '
    'xmlns:svg="urn:oasis:names:tc:opendocument:xmlns:svg-compatible:1.0" '
    'xmlns:config="urn:oasis:names:tc:opendocument:xmlns:config:1.0" '
    'xmlns:of="urn:oasis:names:tc:opendocument:xmlns:of:1.2" '
    'xmlns:ooow="http://openoffice.org/2004/writer" '
    'xmlns:oooc="http://openoffice.org/2004/calc" '
    'xmlns:officeooo="http://openoffice.org/2009/office" '
    'xmlns:loext="urn:org:documentfoundation:names:experimental:office:xmlns:loext:1.0"'
)

def font_faces() -> str:
    return (
        f'<style:font-face style:name="{FONT}" svg:font-family="&apos;{FONT}&apos;" '
        'style:font-pitch="variable"/>'
        f'<style:font-face style:name="{MONO}" svg:font-family="&apos;{MONO}&apos;" '
        'style:font-family-generic="modern" style:font-pitch="fixed"/>'
    )


def build_styles_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<office:document-styles {NS_DECL} office:version="1.3">'
        f'<office:font-face-decls>{font_faces()}</office:font-face-decls>'
        f'<office:styles>{paragraph_styles()}{text_styles()}{list_styles()}'
        '<style:style style:name="TableMain" style:family="table">'
        f'<style:table-properties style:width="{cm(TEXT_W)}" table:align="margins" '
        'style:writing-mode="lr-tb"/></style:style>'
        '</office:styles>'
        f'<office:automatic-styles>{page_layouts()}</office:automatic-styles>'
        f'<office:master-styles>{master_pages()}</office:master-styles>'
        '</office:document-styles>'
    )


# ===========================================================================
# content.xml
# ===========================================================================
def automatic_styles(doc: Doc) -> str:
    s = []
    # คอลัมน์ตาราง: ความกว้างคำนวณจริงต่อตาราง
    for table_name, widths in doc.table_widths.items():
        for k, w in enumerate(widths):
            s.append(f'<style:style style:name="{table_name}.Col{k}" style:family="table-column">'
                     f'<style:table-column-properties style:column-width="{cm(w)}"/></style:style>')
    s.append('<style:style style:name="RowKeep" style:family="table-row">'
             '<style:table-row-properties fo:keep-together="always"/></style:style>')
    cell_border = f'fo:border="0.5pt solid {COLOUR_RULE}"'
    s.append(f'<style:style style:name="CellHead" style:family="table-cell">'
             f'<style:table-cell-properties {cell_border} fo:background-color="{COLOUR_HEAD_BG}" '
             'fo:padding="0.12cm 0.16cm" style:vertical-align="middle"/></style:style>')
    s.append(f'<style:style style:name="CellBody" style:family="table-cell">'
             f'<style:table-cell-properties {cell_border} '
             'fo:padding="0.12cm 0.16cm" style:vertical-align="top"/></style:style>')
    s.append('<style:style style:name="FrameFigure" style:family="graphic">'
             '<style:graphic-properties style:vertical-pos="top" style:vertical-rel="baseline" '
             'style:wrap="none" style:run-through="foreground"/></style:style>')
    s.append('<style:style style:name="Sect1" style:family="section">'
             '<style:section-properties style:writing-mode="lr-tb"/></style:style>')
    return ''.join(s)


def index_entry_template(kind: str, level: int) -> str:
    return (f'<text:{kind}-entry-template text:outline-level="{level}" '
            f'text:style-name="Contents{level}">'
            '<text:index-entry-link-start text:style-name="IndexLink"/>'
            '<text:index-entry-text/>'
            '<text:index-entry-tab-stop style:type="right" style:leader-char="."/>'
            '<text:index-entry-page-number/>'
            '<text:index-entry-link-end/>'
            f'</text:{kind}-entry-template>')


def build_toc(outline: list[tuple[int, str]]) -> str:
    templates = ''.join(index_entry_template('table-of-content', lvl) for lvl in (1, 2, 3, 4))
    entries = []
    for level, text in outline:
        if level > 4:
            continue
        entries.append(
            f'<text:p text:style-name="Contents{level}">{e(text)}'
            '<text:tab/><text:span text:style-name="IndexLink">?</text:span></text:p>')
    return (
        '<text:table-of-content text:style-name="Sect1" text:name="Table of Contents1">'
        '<text:table-of-content-source text:outline-level="4">'
        '<text:index-title-template text:style-name="ContentsHeading"/>'
        f'{templates}</text:table-of-content-source>'
        '<text:index-body>' + ''.join(entries) + '</text:index-body>'
        '</text:table-of-content>'
    )


def build_lof(captions: list[str]) -> str:
    entries = ''.join(
        f'<text:p text:style-name="FigureIndexEntry">{e(c)}<text:tab/>?</text:p>' for c in captions)
    return (
        '<text:illustration-index text:style-name="Sect1" text:name="Table of Figures1">'
        '<text:illustration-index-source text:index-scope="document">'
        '<text:index-title-template text:style-name="ContentsHeading"/>'
        '<text:index-source-style text:style-name="FigureCaption"/>'
        '<text:illustration-index-entry-template text:style-name="FigureIndexEntry">'
        '<text:index-entry-link-start text:style-name="IndexLink"/>'
        '<text:index-entry-text/>'
        '<text:index-entry-tab-stop style:type="right" style:leader-char="."/>'
        '<text:index-entry-page-number/>'
        '<text:index-entry-link-end/>'
        '</text:illustration-index-entry-template>'
        '</text:illustration-index-source>'
        '<text:index-body>' + entries + '</text:index-body>'
        '</text:illustration-index>'
    )


def build_lot(captions: list[str]) -> str:
    entries = ''.join(
        f'<text:p text:style-name="TableIndexEntry">{e(c)}<text:tab/>?</text:p>' for c in captions)
    return (
        '<text:table-index text:style-name="Sect1" text:name="Index of Tables1">'
        '<text:table-index-source text:index-scope="document">'
        '<text:index-title-template text:style-name="ContentsHeading"/>'
        '<text:index-source-style text:style-name="TableCaption"/>'
        '<text:table-index-entry-template text:style-name="TableIndexEntry">'
        '<text:index-entry-link-start text:style-name="IndexLink"/>'
        '<text:index-entry-text/>'
        '<text:index-entry-tab-stop style:type="right" style:leader-char="."/>'
        '<text:index-entry-page-number/>'
        '<text:index-entry-link-end/>'
        '</text:table-index-entry-template>'
        '</text:table-index-source>'
        '<text:index-body>' + entries + '</text:index-body>'
        '</text:table-index>'
    )


# ===========================================================================
# ส่วนหน้า: ปก / เอกสารควบคุม / คำนำ
# ===========================================================================
def render_cover(doc: Doc, section: dict, assets: dict[Path, Asset], inner: bool) -> None:
    blocks = section['blocks']
    logo_style = 'CoverLogo2' if inner else 'CoverLogo'
    title = section['title']

    logo = next((b for b in blocks if b['t'] == 'fig'), None)
    paras = [b for b in blocks if b['t'] == 'para']

    if logo:
        asset = assets.get((SRC / logo['src']).resolve())
        if asset:
            w = 3.81
            h = w * asset.h / asset.w
            doc.n_frame += 1
            doc.p(logo_style,
                  f'<draw:frame draw:style-name="FrameFigure" draw:name="Image{doc.n_frame}" '
                  f'text:anchor-type="as-char" svg:width="{cm(w)}" svg:height="{cm(h)}" draw:z-index="0">'
                  f'<draw:image xlink:href="Pictures/{asset.name}" xlink:type="simple" '
                  f'xlink:show="embed" xlink:actuate="onLoad"/></draw:frame>')
    doc.p('CoverTitle' if not inner else 'CoverTitle', e(title))

    if paras:
        doc.p('CoverSubtitle', inline(paras[0]['text']))
        rest = paras[1:]
    else:
        rest = []

    by_done = False
    for blk in rest:
        raw = blk['text'].strip()
        m = BOLD_ONLY_RE.match(raw)
        text = m.group(1).strip() if m else raw
        if text.startswith('จัดทำโดย'):
            doc.p('CoverBy', e('จัดทำโดย'))
            name = text.replace('จัดทำโดย', '', 1).strip()
            if name:
                doc.p('CoverName', e(name))
            by_done = True
            continue
        if not by_done:
            doc.p('CoverBy', inline(text))
            by_done = True
            continue
        if 'คู่มือฉบับนี้เป็นส่วนหนึ่ง' in text:
            doc.p('CoverFooter', inline(text))
        else:
            doc.p('CoverText', inline(text))


def render_doc_control(doc: Doc, section: dict) -> None:
    doc.p('FrontTitle', e(section['title']))
    for b in section['blocks']:
        if b['t'] == 'para':
            doc.p('BodyTextNoIndent', inline(b['text']))
        elif b['t'] == 'table':
            doc.table(b['rows'], None)


def render_preface(doc: Doc, section: dict) -> None:
    doc.h(1, 'Heading1FrontStart', section['title'])
    for b in section['blocks']:
        if b['t'] == 'para':
            raw = b['text'].strip()
            m = BOLD_ONLY_RE.match(raw)
            if m and len(m.group(1)) < 80:
                doc.p('Signature', f'<text:span text:style-name="StrongChar">{e(m.group(1))}</text:span>')
            else:
                doc.p('PrefaceText', inline(raw))
        elif b['t'] == 'table':
            doc.table(b['rows'], None)


# ===========================================================================
# สร้างเอกสารทั้งหมด
# ===========================================================================
def build(tmpdir: Path, use_mermaid: bool) -> tuple[Doc, dict[Path, Asset]]:
    assets = stage_images(tmpdir)
    mermaid = render_mermaid(tmpdir, use_mermaid)
    for a in mermaid.values():
        assets[a.path] = a

    fm_text = (SRC / '00-frontmatter.md').read_text(encoding='utf-8')
    sections = split_sections(parse_blocks(fm_text))
    if len(sections) < 4:
        raise SystemExit(f'ส่วนหน้าไม่ครบ 4 ตอน (พบ {len(sections)})')

    shared: dict = {'table': 0, 'frame': 0, 'pic': 0, 'widths': {}}
    doc = Doc(shared)

    # 1–3: ปกนอก, ปกรองหน้าเปล่า, ปกใน
    render_cover(doc, sections[0], assets, inner=False)
    doc.p('CoverBlank', '')
    render_cover(doc, sections[1], assets, inner=True)

    # เอกสารควบคุมคู่มือ (ไม่มีเลขหน้า ไม่เข้า outline)
    if len(sections) >= 4 and 'เอกสารควบคุม' in sections[2]['title']:
        render_doc_control(doc, sections[2])
        preface = sections[3]
    else:
        preface = sections[2]

    # คำนำ (เริ่มนับ ก)
    render_preface(doc, preface)

    # เนื้อหาบท (สร้างก่อนเพื่อเก็บรายการภาพ/ตาราง/หัวข้อ)
    chapter_xml: list[str] = []
    part_xml: list[str] = []
    for bi, (slug, vol, title, sub) in enumerate(BOOKS):
        p = Doc(shared)
        p.p('PartSpacerFirst' if bi == 0 else 'PartSpacer', '')
        p.h(1, 'Heading1Part', f'{vol}: {title}')
        p.p('PartSubtitle', e(sub))
        part_xml.append(''.join(p.parts))

        for md in sorted((SRC / slug).glob('ch*.md')):
            blocks = parse_blocks(md.read_text(encoding='utf-8'))
            c = Doc(shared)
            first_h1 = True
            for b in blocks:
                if b['t'] == 'h' and b['level'] == 1:
                    if first_h1:
                        c.h(2, 'Heading2', b['text'])
                        first_h1 = False
                    else:
                        c.h(1, 'Heading3', b['text'])
                elif b['t'] == 'h' and b['level'] == 2:
                    c.h(3, 'Heading3', b['text'])
                elif b['t'] == 'h' and b['level'] == 3:
                    c.h(4, 'Heading4', b['text'])
                else:
                    c.blocks([b], md.parent, assets, mermaid)
            chapter_xml.append(''.join(c.parts))
            doc.figures += c.figures
            doc.tables += c.tables
            doc.outline += c.outline

    # บรรณานุกรม
    bib = Doc(shared)
    bib_blocks = parse_blocks((SRC / '99-bibliography.md').read_text(encoding='utf-8'))
    first = True
    for b in bib_blocks:
        if b['t'] == 'h' and b['level'] == 1:
            bib.h(1, 'Heading1Body', b['text'])
        elif b['t'] == 'h' and b['level'] == 2:
            bib.h(3, 'Heading3', b['text'])
        elif b['t'] == 'h' and b['level'] == 3:
            bib.h(4, 'Heading4', b['text'])
        else:
            bib.blocks([b], SRC, assets, mermaid)
    doc.figures += bib.figures
    doc.tables += bib.tables
    doc.outline += bib.outline

    # สารบัญ: หัวข้อส่วนหน้า + เนื้อหา + บรรณานุกรม
    front_outline = [(1, 'คำนำ'), (1, 'สารบัญ'), (1, 'สารบัญภาพ'), (1, 'สารบัญตาราง')]
    toc = build_toc(front_outline + doc.outline)

    doc.h(1, 'Heading1Front', 'สารบัญ')
    doc.parts.append(toc)
    doc.h(1, 'Heading1Front', 'สารบัญภาพ')
    doc.parts.append(build_lof(doc.figures))
    doc.h(1, 'Heading1Front', 'สารบัญตาราง')
    doc.parts.append(build_lot(doc.tables))

    for part, chapters in zip(part_xml, _chunk(chapter_xml)):
        doc.parts.append(part)
        doc.parts.extend(chapters)

    doc.parts.append(''.join(bib.parts))

    # ปกรองหลัง + ปกหลัง
    doc.p('BackBlank', '')
    doc.p('BackBlank', '')
    return doc, assets


def _chunk(items: list[str]) -> list[list[str]]:
    sizes = [10, 10, 7]
    out, i = [], 0
    for s in sizes:
        out.append(items[i:i + s])
        i += s
    return out


def build_content_xml(doc: Doc) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<office:document-content {NS_DECL} office:version="1.3">'
        '<office:scripts/>'
        f'<office:font-face-decls>{font_faces()}</office:font-face-decls>'
        f'<office:automatic-styles>{automatic_styles(doc)}</office:automatic-styles>'
        '<office:body><office:text>'
        '<text:sequence-decls>'
        '<text:sequence-decl text:display-outline-level="0" text:name="Illustration"/>'
        '<text:sequence-decl text:display-outline-level="0" text:name="Table"/>'
        '</text:sequence-decls>'
        + ''.join(doc.parts) +
        '</office:text></office:body>'
        '</office:document-content>'
    )


def build_meta_xml(doc: Doc) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<office:document-meta {NS_DECL} office:version="1.3">'
        '<office:meta>'
        '<dc:title>คู่มือการใช้งานระบบ PIRIvoice</dc:title>'
        '<dc:subject>แพลตฟอร์มรับฟังความคิดเห็นและบริหารจัดการงานสภานักเรียน</dc:subject>'
        '<dc:creator>นายพัฒนพล สุธรรม</dc:creator>'
        '<meta:generator>PIRIvoice ODT builder</meta:generator>'
        '<meta:initial-creator>นายพัฒนพล สุธรรม</meta:initial-creator>'
        f'<meta:document-statistic meta:table-count="{doc.n_table}" meta:image-count="{doc.n_pic}" '
        'meta:object-count="0"/>'
        '</office:meta>'
        '</office:document-meta>'
    )


def build_settings_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<office:document-settings {NS_DECL} office:version="1.3">'
        '<office:settings>'
        '<config:config-item-set config:name="ooo:view-settings">'
        '<config:config-item config:name="ViewAreaTop" config:type="long">0</config:config-item>'
        '<config:config-item config:name="ViewAreaLeft" config:type="long">0</config:config-item>'
        '<config:config-item config:name="ViewAreaWidth" config:type="long">20000</config:config-item>'
        '<config:config-item config:name="ViewAreaHeight" config:type="long">20000</config:config-item>'
        '<config:config-item config:name="ShowRedlineChanges" config:type="boolean">false</config:config-item>'
        '<config:config-item config:name="InBrowseMode" config:type="boolean">false</config:config-item>'
        '</config:config-item-set>'
        '<config:config-item-set config:name="ooo:configuration-settings">'
        '<config:config-item config:name="FieldAutoUpdate" config:type="boolean">true</config:config-item>'
        '<config:config-item config:name="UpdateFromTemplate" config:type="boolean">true</config:config-item>'
        '<config:config-item config:name="LinkUpdateMode" config:type="short">1</config:config-item>'
        '<config:config-item config:name="TabsRelativeToIndent" config:type="boolean">true</config:config-item>'
        '<config:config-item config:name="CharacterCompressionType" config:type="short">0</config:config-item>'
        '<config:config-item config:name="PrintPaperFromSetup" config:type="boolean">false</config:config-item>'
        '</config:config-item-set>'
        '</office:settings>'
        '</office:document-settings>'
    )


def build_manifest(assets: dict[Path, Asset]) -> str:
    entries = [
        '<manifest:file-entry manifest:full-path="/" manifest:version="1.3" '
        'manifest:media-type="application/vnd.oasis.opendocument.text"/>',
        '<manifest:file-entry manifest:full-path="content.xml" manifest:media-type="text/xml"/>',
        '<manifest:file-entry manifest:full-path="styles.xml" manifest:media-type="text/xml"/>',
        '<manifest:file-entry manifest:full-path="meta.xml" manifest:media-type="text/xml"/>',
        '<manifest:file-entry manifest:full-path="settings.xml" manifest:media-type="text/xml"/>',
    ]
    for a in sorted(assets.values(), key=lambda x: x.name):
        entries.append(f'<manifest:file-entry manifest:full-path="Pictures/{a.name}" '
                       'manifest:media-type="image/png"/>')
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<manifest:manifest xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0" '
        'manifest:version="1.3">' + ''.join(entries) + '</manifest:manifest>'
    )


# ===========================================================================
# ZIP + ตรวจสอบ
# ===========================================================================
def write_odt(doc: Doc, assets: dict[Path, Asset]) -> None:
    from lxml import etree

    parts = {
        'content.xml': build_content_xml(doc),
        'styles.xml': build_styles_xml(),
        'meta.xml': build_meta_xml(doc),
        'settings.xml': build_settings_xml(),
        'META-INF/manifest.xml': build_manifest(assets),
    }
    # ตรวจ XML ทุกไฟล์ก่อนบรรจุ
    for name, xml in parts.items():
        try:
            etree.fromstring(xml.encode('utf-8'))
        except etree.XMLSyntaxError as exc:
            raise SystemExit(f'XML ไม่ถูกต้องใน {name}: {exc}')

    OUT_ODT.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(OUT_ODT, 'w') as z:
        zi = zipfile.ZipInfo('mimetype')
        zi.compress_type = zipfile.ZIP_STORED
        z.writestr(zi, 'application/vnd.oasis.opendocument.text')
        for name, xml in parts.items():
            z.writestr(name, xml.encode('utf-8'), compress_type=zipfile.ZIP_DEFLATED)
        seen = set()
        for a in assets.values():
            if a.name in seen:
                continue
            seen.add(a.name)
            z.write(a.path, f'Pictures/{a.name}', compress_type=zipfile.ZIP_STORED)


def verify(doc: Doc, assets: dict[Path, Asset]) -> dict:
    from lxml import etree

    info = {}
    with zipfile.ZipFile(OUT_ODT) as z:
        names = z.namelist()
        info['entries'] = len(names)
        info['first_entry'] = names[0]
        info['mimetype_stored'] = z.getinfo('mimetype').compress_type == zipfile.ZIP_STORED
        content = z.read('content.xml')
        styles = z.read('styles.xml')
        manifest = z.read('META-INF/manifest.xml').decode('utf-8')
        root = etree.fromstring(content)
        etree.fromstring(styles)
        ns = {'text': 'urn:oasis:names:tc:opendocument:xmlns:text:1.0',
              'draw': 'urn:oasis:names:tc:opendocument:xmlns:drawing:1.0',
              'xlink': 'http://www.w3.org/1999/xlink'}
        info['images'] = len(root.xpath('//draw:image', namespaces=ns))
        pics = {n for n in names if n.startswith('Pictures/')}
        info['pictures'] = len(pics)
        info['manifest_pictures'] = manifest.count('Pictures/')
        hrefs = {h.replace('Pictures/', 'Pictures/') for h in
                 root.xpath('//draw:image/@xlink:href', namespaces=ns)}
        info['missing_pictures'] = sorted(h for h in hrefs if h not in pics)
        info['fig_captions'] = len(root.xpath('//text:p[@text:style-name="FigureCaption"]', namespaces=ns))
        info['tbl_captions'] = len(root.xpath('//text:p[@text:style-name="TableCaption"]', namespaces=ns))
        info['headings'] = {
            lvl: len(root.xpath(f'//text:h[@text:outline-level="{lvl}"]', namespaces=ns))
            for lvl in (1, 2, 3, 4)
        }
        info['steplabel_in_outline'] = len(root.xpath(
            '//text:h[@text:style-name="StepLabel"]', namespaces=ns))
        info['size_mb'] = OUT_ODT.stat().st_size / 1048576
    return info


def finalize_with_libreoffice() -> None:
    script = REPO / 'reports' / 'odt_update_indexes.py'
    if not script.exists():
        print('แจ้งเตือน: ไม่พบ odt_update_indexes.py — ข้ามการอัปเดตสารบัญ', file=sys.stderr)
        return
    probe = subprocess.run(['/usr/bin/python3', '-c', 'import uno'], capture_output=True)
    if probe.returncode != 0:
        print('แจ้งเตือน: ไม่มี python3-uno — เปิดไฟล์ใน LibreOffice แล้วกด '
              'Tools > Update > Update All เพื่ออัปเดตสารบัญ', file=sys.stderr)
        return
    print('อัปเดตสารบัญและสร้าง PDF ด้วย LibreOffice ...')
    proc = subprocess.run(['/usr/bin/python3', str(script), str(OUT_ODT), str(OUT_PDF)])
    if proc.returncode != 0:
        print('แจ้งเตือน: อัปเดตสารบัญไม่สำเร็จ — เปิดไฟล์แล้วกด Update All', file=sys.stderr)


def main() -> None:
    ap = argparse.ArgumentParser(description='สร้างคู่มือ PIRIvoice เป็น .odt')
    ap.add_argument('--skip-libreoffice', action='store_true')
    ap.add_argument('--skip-mermaid', action='store_true')
    ap.add_argument('--keep-temp', action='store_true')
    args = ap.parse_args()

    ensure_fonts()
    tmpdir = Path(tempfile.mkdtemp(prefix='pirivoice-odt-'))
    try:
        doc, assets = build(tmpdir, use_mermaid=not args.skip_mermaid)
        write_odt(doc, assets)
        info = verify(doc, assets)
        print(f'ODT: {OUT_ODT}')
        print(f'  ขนาด {info["size_mb"]:.2f} MB · entry {info["entries"]} · mimetype แรก={info["first_entry"]}')
        print(f'  รูปฝัง {info["images"]} ครั้ง / ไฟล์ {info["pictures"]} · manifest {info["manifest_pictures"]}')
        print(f'  คำบรรยายภาพ {info["fig_captions"]} · ตาราง {info["tbl_captions"]} · หัวข้อ {info["headings"]}')
        if info['missing_pictures']:
            print('  ⚠ รูปที่อ้างแต่ไม่มี:', info['missing_pictures'][:5])
        if info['steplabel_in_outline']:
            print('  ⚠ พบ StepLabel ใน outline:', info['steplabel_in_outline'])
        if not args.skip_libreoffice:
            finalize_with_libreoffice()
    finally:
        if args.keep_temp:
            print(f'ไฟล์ชั่วคราว: {tmpdir}')
        else:
            shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == '__main__':
    main()
