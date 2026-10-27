// Browser check for real mode with an empty database: pages stay empty, nothing seeds, writes need the key.
// Start the backend with DATA_MODE=real, an API_KEY and an empty migrated database before running.
// Usage: node scripts/e2e-real-empty.mjs [baseUrl] [apiBase]
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import puppeteer from 'puppeteer-core'

const here = path.dirname(fileURLToPath(import.meta.url))
const BASE = process.argv[2] || 'http://localhost:5173'
const API = process.argv[3] || 'http://localhost:8000/api/v1'
const SHOTS = path.resolve(here, '../e2e-shots')
fs.mkdirSync(SHOTS, { recursive: true })
const executablePath = [
  process.env.EDGE_PATH,
  'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Google/Chrome/Application/chrome.exe',
  '/usr/bin/google-chrome',
].find((p) => p && fs.existsSync(p))

let failed = 0
const ok = (name, cond, detail = '') => {
  if (!cond) failed += 1
  console.log(`${cond ? 'PASS' : 'FAIL'}  ${name}${detail ? ` — ${detail}` : ''}`)
}

const health = await (await fetch(`${API}/health`)).json()
ok('backend in real mode', health.data_mode === 'real' && health.seed_allowed === false, JSON.stringify(health))

const browser = await puppeteer.launch({ executablePath, headless: true })
const page = await browser.newPage()
await page.setViewport({ width: 1440, height: 900 })
const requests = []
page.on('request', (r) => requests.push(`${r.method()} ${r.url()}`))

for (const [name, hash] of [
  ['overview', '/overview'],
  ['evidence', '/evidence'],
  ['data', '/data'],
]) {
  await page.goto(`${BASE}/#${hash}`, { waitUntil: 'networkidle0' })
  await new Promise((r) => setTimeout(r, 500))
  const text = await page.evaluate(() => document.body.innerText)
  await page.screenshot({ path: path.join(SHOTS, `real-empty-${name}.png`), fullPage: true })
  if (name === 'data') {
    ok('data page offers no seed button in real mode', !text.includes('生成 / 重置模拟数据'))
    ok('data page explains how to start', text.includes('请先在下方登记事件'))
  } else {
    ok(`${hash} shows real-mode empty state`, text.includes('不会用演示数据填充'), text.slice(0, 80).replace(/\s+/g, ' '))
  }
  ok(`${hash} shows no simulated content`, !text.includes('模拟台风'))
}

// Writing without the key is refused and leaves the database empty.
await page.goto(`${BASE}/#/data`, { waitUntil: 'networkidle0' })
const form = await page.$$('form.block')
const eventForm = form[1]
const inputs = await eventForm.$$('input')
await inputs[1].type('REAL-TEST')
await inputs[2].type('真实事件测试')
await page.evaluate(() => {
  const set = (el, v) => {
    el.value = v
    el.dispatchEvent(new Event('input', { bubbles: true }))
  }
  const dt = document.querySelectorAll('form.block')[1].querySelectorAll('input[type="datetime-local"]')
  set(dt[0], '2024-07-01T00:00')
  set(dt[1], '2024-07-03T00:00')
})
await (await eventForm.$('button[type="submit"]')).click()
await new Promise((r) => setTimeout(r, 800))
const refusal = await page.evaluate(() => document.querySelector('.note.bad')?.textContent || '')
ok('event registration without API key is refused', /401|403|密钥|API|key/i.test(refusal), refusal)
const ds = await (await fetch(`${API}/datasets`)).json()
ok('database still empty after refused write', ds.items.length === 0, JSON.stringify(ds))
ok('no seed request was sent', !requests.some((r) => r.includes('/admin/seed')))

// With the key saved for this tab, the same registration succeeds and pages show an event without data.
const key = process.env.E2E_API_KEY || 'e2e-real-key'
const credInputs = await form[0].$$('input')
await credInputs[0].type(key)
await credInputs[1].type('e2e-operator')
await (await form[0].$('button[type="submit"]')).click()
await (await eventForm.$('button[type="submit"]')).click()
await new Promise((r) => setTimeout(r, 1200))
const okMsg = await page.evaluate(() => document.querySelector('.note.info[role="status"]')?.textContent || '')
ok('event registration with API key succeeds', okMsg.includes('事件已登记'), okMsg)
const leaked = await page.evaluate(() => [...document.scripts].some((s) => s.textContent.includes('e2e-real-key')))
ok('API key is not embedded in page scripts', !leaked)
await page.goto(`${BASE}/#/overview`, { waitUntil: 'networkidle0' })
await new Promise((r) => setTimeout(r, 800))
const overview = await page.evaluate(() => document.body.innerText)
await page.screenshot({ path: path.join(SHOTS, 'real-event-no-data-overview.png'), fullPage: true })
ok('overview shows the registered real event', overview.includes('真实事件测试'))
ok('overview shows no simulated content after registration', !overview.includes('模拟台风'))

await browser.close()
console.log(failed ? `\n${failed} check(s) failed` : '\nall real-mode checks passed')
process.exit(failed ? 1 : 0)
