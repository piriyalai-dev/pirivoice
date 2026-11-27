/**
 * แคปหน้าจอคู่มือ PIRIvoice จาก staging จริง (390×844 @2x, มือถือ Android, th-TH)
 *
 *   node capture.mjs --all                 # แคปทุกเป้าหมายใน targets.json
 *   node capture.mjs user/home             # แคปเฉพาะเป้าหมายเดียว
 *   node capture.mjs --all --only user/    # แคปเฉพาะกลุ่มที่ชื่อขึ้นต้นด้วย user/
 *
 * ต้องมี: /tmp/e2e_credentials.json (สร้างโดย backend/scripts/e2e_seed.py)
 *         และ playwright ใน frontend/node_modules
 *
 * เป้าหมายแต่ละรายการใน targets.json:
 *   { file, user, path, height?, wait?, anon?, scrollToText?, scrollAdjust?, click?,
 *     replace?, setToken?, marks?, selector? }
 *   - replace: [[จาก, เป็น]] แทนข้อความบนหน้า (โดเมนทดสอบ/ชื่อจริง/อีโมจิ)
 *   - click:   CSS/text selector ที่กดก่อนแคป (เช่น "text=ถัดไป")
 *   - marks:   [{ text|sel|selText, n?, box?, radius?, at? }] วงกลม/กรอบสีแดงกำกับ
 *              text = เลือก element ที่ข้อความตรงเป๊ะ · selText = [tag, ข้อความบางส่วน]
 *
 * ผลลัพธ์: PNG ลงโฟลเดอร์ out/ แล้วใช้ convert_webp.py แปลงเป็น WebP ก่อนวางใน docs/
 */
import { chromium } from '../../frontend/node_modules/playwright/index.mjs'
import fs from 'node:fs'
import path from 'node:path'

const API = 'https://prsc-api-test.pirivoice.com'
const BASE = 'https://prsc-test.pirivoice.com'
const UA =
  'Mozilla/5.0 (Linux; Android 14; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) ' +
  'Chrome/124.0.0.0 Mobile Safari/537.36'
const HERE = path.dirname(new URL(import.meta.url).pathname)
const TARGETS = JSON.parse(fs.readFileSync(path.join(HERE, 'targets.json'), 'utf8'))
const OUT = process.env.OUT_DIR || path.join(HERE, 'out')
const CREDS = JSON.parse(fs.readFileSync('/tmp/e2e_credentials.json', 'utf8'))

const args = process.argv.slice(2)
const only = args.find((a) => a.startsWith('--only='))?.slice(7) || null
const single = args.find((a) => !a.startsWith('--')) || null

async function capture(browser, t) {
  const context = await browser.newContext({
    viewport: { width: 390, height: t.height || 844 },
    deviceScaleFactor: 2,
    userAgent: UA,
    locale: 'th-TH',
    timezoneId: 'Asia/Bangkok',
    extraHTTPHeaders: { 'Accept-Language': 'th-TH,th;q=0.9' },
  })
  const page = await context.newPage()
  page.on('pageerror', (e) => console.error(`  [${t.file}] pageerror:`, e.message))

  if (!t.anon) {
    const c = CREDS[t.user || 'e2estu']
    const res = await page.request.post(`${API}/api/auth/login`, {
      data: { username: c.username, password: c.password },
    })
    if (!res.ok()) throw new Error('login failed ' + res.status())
    const body = await res.json()
    await context.addInitScript(
      ([tok, uid]) => {
        localStorage.setItem('access_token', tok)
        localStorage.setItem('user_id_str', String(uid))
      },
      [body.access_token, body.user.id],
    )
  }

  await page.goto(BASE + t.path, { waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(t.wait || 2800)

  if (t.replace?.length) {
    await page.evaluate((pairs) => {
      const walk = (node) => {
        if (node.nodeType === 3) {
          let v = node.nodeValue
          for (const [f, r] of pairs) v = v.split(f).join(r)
          if (v !== node.nodeValue) node.nodeValue = v
        } else if (node.nodeType === 1 && !['SCRIPT', 'STYLE'].includes(node.tagName)) {
          for (const ch of node.childNodes) walk(ch)
        }
      }
      walk(document.body)
      document.querySelectorAll('input,textarea').forEach((el) => {
        let v = el.value
        for (const [f, r] of pairs) v = v.split(f).join(r)
        if (v !== el.value) {
          el.value = v
          el.dispatchEvent(new Event('input', { bubbles: true }))
        }
      })
    }, t.replace)
  }

  if (t.setToken) {
    await page.evaluate((tok) => {
      const el = document.querySelector('[data-testid="checkin-token"]')
      if (el) el.textContent = tok
    }, t.setToken)
  }

  for (const sel of t.click || []) {
    try {
      const [q, mode] = sel.endsWith('|last') ? [sel.slice(0, -5), 'last'] : [sel, 'first']
      const loc = page.locator(q)
      await (mode === 'last' ? loc.last() : loc.first()).click({ timeout: 5000 })
      await page.waitForTimeout(900)
    } catch (e) {
      console.error(`  [${t.file}] click failed:`, sel)
    }
  }

  let scroll_found = true
  if (t.scrollToText) {
    scroll_found = await page.evaluate((txt) => {
      const all = Array.from(document.querySelectorAll('h1,h2,h3,h4,p,div,span'))
      const el =
        all.find((e) => e.textContent?.trim() === txt) ||
        all.find((e) => e.children.length === 0 && e.textContent?.includes(txt))
      if (!el) return false
      el.scrollIntoView({ block: 'start' })
      return true
    }, t.scrollToText)
    if (!scroll_found) console.error(`  [${t.file}] ไม่พบจุดเลื่อน: ${t.scrollToText}`)
    await page.waitForTimeout(700)
    if (t.scrollAdjust) {
      await page.evaluate((dy) => window.scrollBy(0, dy), t.scrollAdjust)
      await page.waitForTimeout(500)
    }
  }

  let missing_marks = []
  if (t.marks?.length) {
    const missing = await page.evaluate((marks) => {
      const layer = document.createElement('div')
      layer.style.cssText = 'position:absolute;inset:0;pointer-events:none;z-index:99999'
      document.body.appendChild(layer)
      const RED = '#e11d48'
      const miss = []
      for (const m of marks) {
        let el = m.sel ? document.querySelector(m.sel) : null
        if (!el && m.selText) {
          const [tag, txt] = m.selText
          // เลือก element ที่ "ลึกที่สุด" — ไม่มีลูกชายที่ข้อความตรงกัน (กันวงกลมคร่อม wrapper)
          const cands = Array.from(document.querySelectorAll(tag)).filter((e) => {
            if (!e.textContent?.includes(txt)) return false
            return !Array.from(e.children).some((c) => c.textContent?.includes(txt))
          })
          cands.sort((a, b) => a.textContent.length - b.textContent.length)
          el = cands[0] || null
        }
        if (!el && m.text) {
          const cands = Array.from(document.querySelectorAll('h1,h2,h3,h4,p,span,div,button'))
          el = cands.find((e) => e.textContent?.trim() === m.text) || null
          if (!el) {
            // แผนสำรอง: จับแบบ "มีข้อความนี้อยู่" แล้วเลือก element ที่เล็กที่สุด
            const near = cands
              .filter((e) => e.textContent?.includes(m.text))
              .sort((a, b) => a.textContent.length - b.textContent.length)
            el = near[0] || null
          }
        }
        if (!el) {
          miss.push(m.text || m.sel || JSON.stringify(m.selText))
          continue
        }
        const r = el.getBoundingClientRect()
        const sx = window.scrollX
        const sy = window.scrollY
        if (m.box) {
          const box = document.createElement('div')
          box.style.cssText =
            `position:absolute;left:${r.left + sx - 4}px;top:${r.top + sy - 4}px;` +
            `width:${r.width + 8}px;height:${r.height + 8}px;border:2.5px solid ${RED};` +
            `border-radius:${m.radius ?? 14}px`
          layer.appendChild(box)
        }
        if (m.n) {
          const d = 28
          const cx = m.at === 'left' ? r.left + sx - d / 2 : r.right + sx - d / 2
          const cy = r.top + sy - d / 2
          const c = document.createElement('div')
          c.textContent = String(m.n)
          c.style.cssText =
            `position:absolute;left:${cx}px;top:${cy}px;width:${d}px;height:${d}px;` +
            `border-radius:50%;background:${RED};color:#fff;font:700 17px/28px sans-serif;` +
            'text-align:center;box-shadow:0 0 0 3px rgba(225,29,72,.22)'
          layer.appendChild(c)
        }
      }
      return miss
    }, t.marks)
    missing_marks = missing
    if (missing.length) console.error(`  [${t.file}] mark ไม่พบ: ${missing.join(' · ')}`)
  }

  const status = { file: t.file, missing: missing_marks, scroll: scroll_found, ok: missing_marks.length === 0 && scroll_found }
  statuses.push(status)

  fs.mkdirSync(path.dirname(path.join(OUT, t.file)), { recursive: true })
  const outPng = path.join(OUT, t.file.replace(/\.webp$/, '.png'))
  if (t.selector) {
    const el = await page.$(t.selector)
    if (!el) throw new Error('selector not found: ' + t.selector)
    await el.screenshot({ path: outPng })
  } else {
    await page.screenshot({ path: outPng })
  }
  await context.close()
  console.log('  ✓', t.file)
}

const statuses = []
const list = TARGETS.filter((t) => (!single || t.file === single || t.file === single + '.webp' || t.file.endsWith(single)) && (!only || t.file.startsWith(only)))
if (!list.length) {
  console.error('ไม่พบเป้าหมาย', { single, only })
  process.exit(1)
}
const browser = await chromium.launch({
  executablePath: process.env.CHROME_PATH,
  args: ['--no-sandbox', '--disable-dev-shm-usage', '--lang=th-TH'],
})
try {
  for (const t of list) {
    try {
      await capture(browser, t)
    } catch (e) {
      console.error(`  ✗ ${t.file}: ${e.message}`)
    }
  }
} finally {
  await browser.close()
}
fs.mkdirSync(OUT, { recursive: true })
fs.writeFileSync(path.join(OUT, '_status.json'), JSON.stringify(statuses, null, 1))
console.log('เสร็จ', list.length, 'เป้าหมาย →', OUT)
