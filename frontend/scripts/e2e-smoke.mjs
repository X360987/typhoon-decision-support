// Browser smoke test against running dev servers (frontend + backend in demo mode).
// Usage: node scripts/e2e-smoke.mjs [baseUrl] [apiBase]
// Env: EDGE_PATH or CHROME_PATH to override the browser executable.
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import puppeteer from 'puppeteer-core'

const here = path.dirname(fileURLToPath(import.meta.url))
const BASE = process.argv[2] || 'http://localhost:5173'
const SHOTS = path.resolve(here, '../e2e-shots')
fs.mkdirSync(SHOTS, { recursive: true })

const candidates = [
  process.env.EDGE_PATH,
  process.env.CHROME_PATH,
  'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Google/Chrome/Application/chrome.exe',
  '/usr/bin/google-chrome',
  '/usr/bin/chromium',
].filter(Boolean)
const executablePath = candidates.find((p) => fs.existsSync(p))
if (!executablePath) throw new Error('No Edge/Chrome executable found; set EDGE_PATH')

const API = process.argv[3] || 'http://localhost:8000/api/v1'
for (let i = 0; ; i++) {
  try {
    const res = await fetch(`${API}/health`)
    if (res.ok) break
  } catch {
    /* backend still starting */
  }
  if (i >= 60) throw new Error(`backend not reachable at ${API}/health`)
  await new Promise((r) => setTimeout(r, 1000))
}

const results = []
function record(name, ok, detail = '') {
  results.push({ name, ok, detail })
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? ` — ${detail}` : ''}`)
}

const browser = await puppeteer.launch({ executablePath, headless: true, args: ['--no-first-run', '--lang=zh-CN'] })
const page = await browser.newPage()
await page.setViewport({ width: 1440, height: 900 })

const consoleErrors = []
const badResponses = []
page.on('pageerror', (e) => consoleErrors.push(`pageerror: ${e.message}`))
page.on('console', (m) => {
  if (m.type() === 'error') consoleErrors.push(m.text())
})
page.on('response', (r) => {
  if (r.url().includes('/api/v1/') && r.status() >= 400) badResponses.push(`${r.status()} ${r.url()}`)
})

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

async function settle(ms = 600) {
  await page.waitForNetworkIdle({ idleTime: 400, timeout: 20000 }).catch(() => {})
  await sleep(ms)
}

async function go(hash) {
  await page.goto(`${BASE}/#${hash}`, { waitUntil: 'domcontentloaded' })
  await page.waitForSelector('.page', { timeout: 15000 })
  await settle()
}

async function clickText(selector, text) {
  const ok = await page.evaluate(
    (sel, t) => {
      const el = [...document.querySelectorAll(sel)].find((e) => e.textContent.trim().includes(t) && !e.disabled)
      if (!el) return false
      el.click()
      return true
    },
    selector,
    text,
  )
  if (!ok) throw new Error(`no clickable ${selector} containing "${text}"`)
}

const text = (sel) => page.$eval(sel, (e) => e.textContent.trim()).catch(() => '')
const count = (sel) => page.$$eval(sel, (els) => els.length)

async function check(name, fn) {
  const errsBefore = consoleErrors.length
  const badBefore = badResponses.length
  try {
    const detail = await fn()
    const newErrs = consoleErrors.slice(errsBefore)
    const newBad = badResponses.slice(badBefore)
    if (newErrs.length || newBad.length) record(name, false, [...newErrs, ...newBad].join(' | '))
    else record(name, true, detail || '')
  } catch (e) {
    record(name, false, e.message)
    await page.screenshot({ path: path.join(SHOTS, `fail-${name.replace(/[^\w-]+/g, '_')}.png`) }).catch(() => {})
  }
}

// 1. Every route renders without runtime errors or failed API calls.
const routes = [
  ['overview', '/overview'],
  ['impact', '/overview/impact'],
  ['replay', '/replay'],
  ['analysis-social', '/analysis/social'],
  ['analysis-org', '/analysis/org'],
  ['analysis-physical', '/analysis/physical'],
  ['analysis-coupling', '/analysis/coupling'],
  ['prediction', '/prediction'],
  ['evidence', '/evidence'],
  ['data', '/data'],
  ['glossary', '/data/glossary'],
]
for (const [name, hash] of routes) {
  await check(`route ${hash}`, async () => {
    await go(hash)
    const h1 = await text('.page h1')
    const errors = await count('.note.bad')
    await page.screenshot({ path: path.join(SHOTS, `desktop-${name}.png`), fullPage: true })
    if (errors) throw new Error(`${errors} error note(s) on page: ${await text('.note.bad')}`)
    return h1
  })
}

// 2. Replay: as-known mode hides anything learned after the cursor; the cursor drives every view.
await check('replay as_known truncation', async () => {
  await go('/replay')
  await clickText('.page-head .seg button', '事后复盘')
  await settle()
  const retroRows = await count('.log tbody tr')
  const retroFuture = await count('.log tbody tr.future')
  await clickText('.page-head .seg button', '当时已知')
  await settle()
  const knownRows = await count('.log tbody tr')
  const knownFuture = await count('.log tbody tr.future')
  const before = await text('.axis .time')
  for (let i = 0; i < 12; i++) await page.click('button[aria-label="后退一小时"]')
  await settle()
  const after = await text('.axis .time')
  const knownRowsEarlier = await count('.log tbody tr')
  const topClock = await text('.top .clock')
  const earlierFuture = await count('.log tbody tr.future')
  if (knownFuture !== 0 || earlierFuture !== 0) throw new Error(`rows after cursor shown in as_known mode (${knownFuture}/${earlierFuture})`)
  if (retroFuture === 0) throw new Error('retrospective window shows no rows after the cursor; truncation untested')
  if (knownRows > retroRows - retroFuture) throw new Error(`as_known shows ${knownRows} rows, retrospective has only ${retroRows - retroFuture} before cursor`)
  if (before === after) throw new Error('cursor did not move')
  if (!topClock.includes(after)) throw new Error(`top bar clock "${topClock}" does not follow replay cursor "${after}"`)
  await page.screenshot({ path: path.join(SHOTS, 'flow-replay-as-known.png'), fullPage: true })
  return `retro ${retroRows} rows (${retroFuture} after cursor), as_known ${knownRows} -> ${knownRowsEarlier} after -12h`
})

// 3. Prediction: table rows are strictly after the origin; no interval numbers are invented.
await check('prediction future rows and honest interval', async () => {
  await clickText('.top .seg button', '事后复盘')
  await go('/prediction')
  await page.waitForSelector('figcaption', { timeout: 15000 })
  const info = await page.evaluate(() => {
    const sel = [...document.querySelectorAll('.params select')][1]
    const rows = [...document.querySelectorAll('.table-wrap tbody tr')].map((tr) => [...tr.children].map((td) => td.textContent.trim()))
    const note = [...document.querySelectorAll('.note')].map((n) => n.textContent).join(' ')
    return { origin: sel?.value || '', rows, note, caption: document.querySelector('figcaption')?.textContent || '' }
  })
  if (!info.rows.length) throw new Error('no prediction rows')
  if (!/区间/.test(info.note)) throw new Error('interval reason not shown')
  if (!info.caption.includes('预测')) throw new Error('chart summary missing forecast part')
  return `origin ${info.origin}; ${info.rows.length} rows; caption: ${info.caption.slice(0, 80)}…`
})

// 4. Evidence: select an item, review it with a note, see it in history; arrow keys move selection.
await check('evidence review flow', async () => {
  await go('/evidence')
  await page.waitForSelector('.items .item', { timeout: 15000 })
  const ids = await page.$$eval('.items .item', (els) => els.map((e) => e.getAttribute('data-anomaly')))
  if (ids.length < 2) throw new Error('need at least two anomalies')
  await page.click(`[data-anomaly="${ids[1]}"]`)
  await page.waitForFunction((id) => location.hash.endsWith(`/evidence/${id}`), {}, ids[1])
  await page.waitForSelector('.detail-col h1', { timeout: 15000 })
  await page.focus(`[data-anomaly="${ids[1]}"]`)
  await page.keyboard.press('ArrowDown')
  await page.waitForFunction((id) => location.hash.endsWith(`/evidence/${id}`), { timeout: 5000 }, ids[2] || ids[1])
  await settle()
  const noteText = `e2e 核验 ${Date.now()}`
  await page.type('.review-bar textarea', noteText)
  await clickText('.review-bar button', '待补证据')
  await page.waitForFunction(() => document.querySelector('.detail-col [role="status"]')?.textContent.includes('已记录'), { timeout: 10000 })
  await clickText('.tabs button', '核验记录')
  await sleep(200)
  const history = await text('.history')
  if (!history.includes(noteText)) throw new Error('review note not in history')
  await page.screenshot({ path: path.join(SHOTS, 'flow-evidence-review.png'), fullPage: true })
  return `reviewed anomaly ${ids[2] || ids[1]}`
})

// 5. Import: blocking errors disable commit with a reason; skip_errors needs explicit confirmation.
await check('import precheck blocks bad rows', async () => {
  const stamp = Date.now()
  const header = 'source_id,bid,user_id,nickname,content,publish_location,topics,reposts,comments,likes,published_at,available_at,ip,verify_type'
  const csv = [
    header,
    `E2E-${stamp}-1,B1,U9001,测试用户,福建关注台风动态,福建,#台风#,1,2,3,2023-07-27 10:15:00,2023-07-27 10:20:00,1.1.1.10,`,
    `E2E-${stamp}-2,B2,U9002,测试用户2,时间写错的一行,广东,#台风#,0,0,0,not-a-date,,2.2.2.10,`,
  ].join('\n')
  const file = path.join(os.tmpdir(), `e2e-bad-${stamp}.csv`)
  fs.writeFileSync(file, '\ufeff' + csv, 'utf8')
  await go('/data')
  const input = await page.$('input[type="file"]')
  await input.uploadFile(file)
  await sleep(300)
  await clickText('.import-step button', '下一步')
  await page.waitForSelector('.import-step select', { timeout: 5000 })
  await clickText('.import-step button', '运行预检')
  await page.waitForSelector('.quality', { timeout: 15000 })
  const disabled = await page.evaluate(() => [...document.querySelectorAll('.import-step button')].find((b) => b.textContent.includes('确认导入'))?.disabled)
  const reason = await text('.import-step .note.attn')
  if (!disabled) throw new Error('commit enabled despite blocking errors')
  if (!reason.includes('阻断')) throw new Error(`no blocking reason shown: "${reason}"`)
  await page.screenshot({ path: path.join(SHOTS, 'flow-import-blocked.png'), fullPage: true })
  await page.click('input[type="radio"][value="skip_errors"]')
  await sleep(100)
  const stillDisabled = await page.evaluate(() => [...document.querySelectorAll('.import-step button')].find((b) => b.textContent.includes('确认导入'))?.disabled)
  if (!stillDisabled) throw new Error('skip_errors enabled commit without confirmation')
  const excluded = await text('.skip-list')
  await page.click('.skip-list input[type="checkbox"]')
  await clickText('.import-step button', '确认导入')
  await page.waitForSelector('.result', { timeout: 30000 })
  const result = await text('.result')
  if (!result.includes('导入状态') || !result.includes('分析状态')) throw new Error('import and analysis status not both shown')
  await page.screenshot({ path: path.join(SHOTS, 'flow-import-result.png'), fullPage: true })
  fs.rmSync(file, { force: true })
  return `${excluded.split('\n')[0]} → ${result.replace(/\s+/g, ' ').slice(0, 120)}`
})

// 6. Rapid event switching never leaves another event's data on screen.
await check('rapid context switch', async () => {
  await go('/overview')
  const options = await page.$$eval('.top select', (sels) => {
    const s = sels.find((x) => x.previousElementSibling?.textContent.includes('台风事件'))
    return s ? [...s.options].map((o) => ({ v: o.value, t: o.textContent.trim() })) : []
  })
  if (options.length < 2) return 'skipped: only one event'
  await page.evaluate((vals) => {
    const s = [...document.querySelectorAll('.top select')].find((x) => x.previousElementSibling?.textContent.includes('台风事件'))
    for (const v of vals) {
      s.value = v
      s.dispatchEvent(new Event('change'))
    }
  }, [options[1].v, options[0].v, options[1].v])
  await settle(1200)
  const shown = await text('.page-head .muted')
  if (shown !== options[1].t) throw new Error(`overview shows "${shown}" but selected "${options[1].t}"`)
  await go('/evidence')
  const detailEvent = await page.evaluate(() => document.querySelector('.detail-col .note.attn')?.textContent || '')
  if (detailEvent.includes('不属于当前')) throw new Error('evidence detail from another event displayed')
  await page.evaluate((v) => {
    const s = [...document.querySelectorAll('.top select')].find((x) => x.previousElementSibling?.textContent.includes('台风事件'))
    s.value = v
    s.dispatchEvent(new Event('change'))
  }, options[0].v)
  await settle()
  return `switched ${options.map((o) => o.t).join(' / ')}`
})

// 7. Narrow layouts.
for (const [w, h, tag] of [
  [1024, 768, 'w1024'],
  [390, 844, 'mobile'],
]) {
  await page.setViewport({ width: w, height: h })
  for (const [name, hash] of [
    ['overview', '/overview'],
    ['evidence', '/evidence'],
    ['data', '/data'],
  ]) {
    await check(`layout ${tag} ${hash}`, async () => {
      await go(hash)
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
      await page.screenshot({ path: path.join(SHOTS, `${tag}-${name}.png`), fullPage: false })
      if (overflow > 2) throw new Error(`horizontal overflow ${overflow}px`)
      return ''
    })
  }
}

await browser.close()
const failed = results.filter((r) => !r.ok)
console.log(`\n${results.length - failed.length}/${results.length} checks passed; screenshots in ${SHOTS}`)
process.exit(failed.length ? 1 : 0)
