#!/usr/bin/env python3
"""อัปเดตสารบัญ/สารบัญภาพ/สารบัญตารางในไฟล์ .odt ด้วย LibreOffice (UNO) แล้ว export PDF

การใช้งาน
  /usr/bin/python3 reports/odt_update_indexes.py <ไฟล์.odt> [ไฟล์.pdf]

ทำอะไร
  1. เปิด LibreOffice แบบ headless ด้วย user profile ชั่วคราว
  2. เปิดเอกสาร, refresh เลขหน้า/ฟิลด์, เรียก update() ให้ดัชนีทุกตัว
  3. บันทึกกลับเป็น .odt (สไตล์ที่ LibreOffice normalize แล้ว)
  4. export เป็น PDF ด้วย filter writer_pdf_Export

ต้องมีแพ็กเกจ python3-uno (apt install python3-uno)
"""
from __future__ import annotations

import os
import random
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import uno
from com.sun.star.beans import PropertyValue


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


def _prop(name: str, value):
    p = PropertyValue()
    p.Name = name
    p.Value = value
    return p


def _start_soffice(port: int, profile: Path) -> subprocess.Popen:
    return subprocess.Popen([
        'soffice', '--headless', '--invisible', '--norestore', '--nologo',
        '--nodefault', '--nofirststartwizard',
        f'-env:UserInstallation={profile.as_uri()}',
        f'--accept=socket,host=127.0.0.1,port={port};urp;StarOffice.ComponentContext',
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _connect(port: int, timeout: float = 90.0):
    local = uno.getComponentContext()
    resolver = local.ServiceManager.createInstanceWithContext(
        'com.sun.star.bridge.UnoUrlResolver', local)
    url = (f'uno:socket,host=127.0.0.1,port={port};urp;'
           'StarOffice.ComponentContext')
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            return resolver.resolve(url)
        except Exception:
            time.sleep(0.5)
    raise RuntimeError('เชื่อมต่อ LibreOffice ไม่สำเร็จ')


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    odt = Path(sys.argv[1]).resolve()
    pdf = Path(sys.argv[2]).resolve() if len(sys.argv) > 2 else odt.with_suffix('.pdf')
    if not odt.exists():
        print(f'ไม่พบไฟล์ {odt}', file=sys.stderr)
        return 2

    # ล้าง lock file ค้างจากรอบก่อน (LibreOffice จะเปิดเอกสารไม่ได้ถ้ามี lock)
    for lock in odt.parent.glob(f'.~lock.{odt.name}#'):
        lock.unlink(missing_ok=True)

    port = _free_port()
    profile = Path(tempfile.mkdtemp(prefix='pirivoice-lo-'))
    proc = _start_soffice(port, profile)
    try:
        ctx = _connect(port)
        desktop = ctx.ServiceManager.createInstanceWithContext(
            'com.sun.star.frame.Desktop', ctx)
        doc = desktop.loadComponentFromURL(
            uno.systemPathToFileUrl(str(odt)), '_blank', 0,
            (_prop('Hidden', True), _prop('ReadOnly', False)))
        if doc is None:
            print('เปิดเอกสารไม่สำเร็จ', file=sys.stderr)
            return 1

        def update_all(tag: str) -> None:
            doc.refresh()
            indexes = doc.getDocumentIndexes()
            n = indexes.getCount()
            names = []
            for i in range(n):
                idx = indexes.getByIndex(i)
                try:
                    names.append(idx.getPropertyValue('Name'))
                except Exception:
                    names.append(f'index{i}')
                idx.update()
            print(f'{tag}: อัปเดต {n} ดัชนี ({", ".join(names)})')

        update_all('รอบที่ 1')
        # รอบที่สอง: จำนวนหน้าอาจขยับหลังดัชนีถูกเติมข้อความ
        update_all('รอบที่ 2')

        print(f'จำนวนหน้า: {doc.getCurrentController().PageCount}')
        doc.store()
        doc.storeToURL(uno.systemPathToFileUrl(str(pdf)), (
            _prop('FilterName', 'writer_pdf_Export'),
            _prop('Overwrite', True),
        ))
        doc.close(True)
        print(f'บันทึก: {odt}')
        print(f'PDF: {pdf} ({pdf.stat().st_size / 1048576:.2f} MB)')
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f'ผิดพลาด: {exc}', file=sys.stderr)
        return 1
    finally:
        try:
            proc.terminate()
            proc.wait(timeout=20)
        except Exception:
            proc.kill()


def index_name(i: int) -> str:
    return f'index{i}'


if __name__ == '__main__':
    sys.exit(main())
