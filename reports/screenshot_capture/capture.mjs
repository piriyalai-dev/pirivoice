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
    viewport: { width: t.width || 390, height: t.height || 844 },
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

  const doScroll = async () => {
    const found = await page.evaluate(
      ([txt, dy]) => {
        const all = Array.from(
          document.querySelectorAll('h1,h2,h3,h4,p,div,span,label,li,a,summary,button'),
        )
        const el =
          all.find((e) => e.textContent?.trim() === txt) ||
          all.find((e) => e.children.length === 0 && e.textContent?.includes(txt))
        if (!el) return false
        el.scrollIntoView({ block: 'start' })
        if (dy) {
          // ⚠️ หน้าแอปเลื่อนใน <main> ไม่ใช่ window ⇒ ต้องปรับตัวที่เลื่อนได้จริง
          let sc = el.parentElement
          while (sc && sc !== document.body) {
            const oy = getComputedStyle(sc).overflowY
            if ((oy === 'auto' || oy === 'scroll') && sc.scrollHeight > sc.clientHeight) break
            sc = sc.parentElement
          }
          if (sc && sc !== document.body) sc.scrollBy(0, dy)
          else window.scrollBy(0, dy)
        }
        return true
      },
      [t.scrollToText, t.scrollAdjust || 0],
    )
    if (!found) console.error(`  [${t.file}] ไม่พบจุดเลื่อน: ${t.scrollToText}`)
    await page.waitForTimeout(700)
    return found
  }

  // `scrollFirst` — เลื่อนหน้าก่อนกด (เช่น หลบเนื้อหาที่จะอยู่หลังกล่อง Swal)
  let scroll_found = true
  if (t.scrollFirst && t.scrollToText) scroll_found = await doScroll()

  for (const sel of t.click || []) {
    try {
      if (sel.startsWith('js:')) {
        // คลิกด้วย JS โดยหาจากข้อความ (ข้ามข้อจำกัด visibility)
        const ok = await page.evaluate((txt) => {
          const els = Array.from(document.querySelectorAll('button,a,[role=button]'))
            .filter((e) => e.textContent?.trim().includes(txt))
          if (!els.length) return false
          els[0].click()
          return true
        }, sel.slice(3))
        if (!ok) console.error(`  [${t.file}] js click not found:`, sel)
        await page.waitForTimeout(900)
        continue
      }
      const [q, mode] = sel.endsWith('|last') ? [sel.slice(0, -5), 'last'] : [sel, 'first']
      const loc = page.locator(q)
      await (mode === 'last' ? loc.last() : loc.first()).click({ timeout: 5000 })
      await page.waitForTimeout(900)
    } catch (e) {
      console.error(`  [${t.file}] click failed:`, sel)
    }
  }

  // กรอก/เลือกไฟล์ "หลัง" คลิก — ฟอร์มที่เปิดด้วยคลิกต้องอยู่ใน DOM ก่อนถึงจะกรอกได้
  for (const [sel, text] of t.type || []) {
    try {
      await page.locator(sel).first().fill(text, { timeout: 5000 })
      await page.waitForTimeout(300)
    } catch (e) {
      console.error(`  [${t.file}] type failed:`, sel)
    }
  }

  for (const [sel, file] of t.setFiles || []) {
    try {
      await page.locator(sel).first().setInputFiles(file, { timeout: 5000 })
      await page.waitForTimeout(500)
    } catch (e) {
      console.error(`  [${t.file}] setFiles failed:`, sel, e.message)
    }
  }

  // `clickAfter` — คลิกหลังกรอกฟอร์ม (เช่น กด "ถัดไป" ที่ต้องมีข้อความก่อนปุ่มจะกดได้)
  for (const sel of t.clickAfter || []) {
    try {
      const [q, mode] = sel.endsWith('|last') ? [sel.slice(0, -5), 'last'] : [sel, 'first']
      const loc = page.locator(q)
      await (mode === 'last' ? loc.last() : loc.first()).click({ timeout: 5000 })
      await page.waitForTimeout(900)
    } catch (e) {
      console.error(`  [${t.file}] clickAfter failed:`, sel)
    }
  }

  if (!t.scrollFirst && t.scrollToText) scroll_found = await doScroll()

  let missing_marks = []
  if (t.marks?.length) {
    const missing = await page.evaluate((marks) => {
      const layer = document.createElement('div')
      layer.style.cssText = 'position:absolute;inset:0;pointer-events:none;z-index:99999'
      document.body.appendChild(layer)
      const RED = '#e11d48'
      const miss = []
      const pos = []
      for (const m of marks) {
        // `within` — จำกัดการค้นหาไว้ในกล่อง/แผ่นที่เปิดอยู่ (กันชนกับของที่ซ่อนอยู่ข้างหลัง)
        const root = (m.within && document.querySelector(m.within)) || document
        // ⚠️ ต้องเลือก element ที่ "มองเห็น" — หน้าแอปมีสำเนาซ่อนอยู่ (drawer/tooltip)
        //    ที่ rect เป็น 0×0 ⇒ mark จะไปเกาะของที่มองไม่เห็นแทนของจริง
        const vis = (e) => {
          const q = e.getBoundingClientRect()
          return q.width > 1 && q.height > 1
        }
        // `selAll` — ล้อมทุก element ที่ตรง (กรอบเดียวคลุมพื้นที่รวม) เช่น ช่องคู่/ปุ่มชุดเดียว
        const all = m.selAll ? Array.from(root.querySelectorAll(m.selAll)).filter(vis) : []
        const selList = m.sel ? Array.from(root.querySelectorAll(m.sel)) : []
        let el = all[0] || selList.find(vis) || selList[0] || null
        if (!el && m.selN) {
          // เลือกตามแท็ก + ลำดับ (เช่น select ตัวที่ 2 ของหน้า)
          const [tag, idx] = m.selN
          el = root.querySelectorAll(tag)[idx] || null
        }
        if (!el && m.selText) {
          const [tag, txt] = m.selText
          // เลือก element ที่ "ลึกที่สุด" — แต่เฉพาะแท็กครอบแบบ div/span
          // (ปุ่ม/ลิงก์มักมี <span> ข้อความอยู่ข้างใน — ห้ามตัดทิ้ง ไม่งั้นหาไม่เจอ)
          const wrapperLike = tag === 'div' || tag === 'span' || tag === '*'
          const cands = Array.from(root.querySelectorAll(tag)).filter((e) => {
            if (!e.textContent?.includes(txt) || !vis(e)) return false
            if (!wrapperLike) return true
            return !Array.from(e.children).some((c) => c.textContent?.includes(txt))
          })
          cands.sort((a, b) => a.textContent.length - b.textContent.length)
          el = cands[0] || null
        }
        if (!el && m.text) {
          const cands = Array.from(root.querySelectorAll('h1,h2,h3,h4,p,span,div,button')).filter(
            vis,
          )
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
          miss.push(m.text || m.sel || m.selAll || JSON.stringify(m.selText))
          continue
        }
        // กรอบครอบพื้นที่รวมของทุก element (selAll) — ใช้กรณีล้อม "ช่องคู่" หรือ "ปุ่มชุด"
        const rects = (all.length ? all : [el]).map((e) => e.getBoundingClientRect())
        const r = all.length
          ? {
              left: Math.min(...rects.map((x) => x.left)),
              top: Math.min(...rects.map((x) => x.top)),
              right: Math.max(...rects.map((x) => x.right)),
              bottom: Math.max(...rects.map((x) => x.bottom)),
              get width() {
                return this.right - this.left
              },
              get height() {
                return this.bottom - this.top
              },
            }
          : rects[0]
        const sx = window.scrollX
        const sy = window.scrollY
        pos.push({
          n: m.n,
          text: (el.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 24),
          rect: [Math.round(r.left), Math.round(r.top), Math.round(r.right), Math.round(r.bottom)],
        })
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
          // `at`: left = มุมซ้าย · outside-left/outside-right = อยู่นอก element เต็มตัว
          //       (ใช้กับข้อความล้วน เพื่อไม่ให้วงกลมทับตัวอักษร)
          const cx =
            m.at === 'left'
              ? r.left + sx - d / 2
              : m.at === 'outside-left'
                ? r.left + sx - d
                : m.at === 'outside-right'
                  ? r.right + sx
                  : m.at === 'inside-right'
                    ? r.right + sx - d
                    : m.at === 'inside-left'
                      ? r.left + sx
                      : r.right + sx - d / 2
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
      return { miss, pos }
    }, t.marks)
    missing_marks = missing.miss
    if (process.env.DEBUG_MARKS) console.log('  marks:', JSON.stringify(missing.pos))
    if (missing_marks.length) console.error(`  [${t.file}] mark ไม่พบ: ${missing_marks.join(' · ')}`)
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
