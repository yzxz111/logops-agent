import assert from 'node:assert/strict'
import { mkdirSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium } from 'playwright-core'

const __dirname = dirname(fileURLToPath(import.meta.url))
const screenshotDir = resolve(__dirname, '../../docs/screenshots')
mkdirSync(screenshotDir, { recursive: true })

const baseUrl = process.env.COCKPIT_URL || 'http://127.0.0.1:5173'
const executablePath =
  process.env.PLAYWRIGHT_BROWSER_PATH ||
  'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe'

const browser = await chromium.launch({
  executablePath,
  headless: true,
})

const context = await browser.newContext({ viewport: { width: 1440, height: 900 } })
const page = await context.newPage()

const pageErrors = []
const apiFailures = []
page.on('pageerror', (err) => pageErrors.push(err.message))
page.on('response', (resp) => {
  if (resp.status() >= 500) {
    apiFailures.push(`${resp.status()} ${resp.url()}`)
  }
})

try {
  await page.goto(baseUrl, { waitUntil: 'networkidle' })
  await page.getByTestId('health-badge').waitFor({ state: 'visible' })
  await page.waitForFunction(() => {
    const el = document.querySelector('[data-testid="health-badge"]')
    return el && el.textContent && el.textContent.includes('在线')
  })

  // 1. 经典故障排障流式推演
  await page.getByTestId('preset-gateway-504').click()
  await page.waitForFunction(
    () => {
      const st = document.querySelector('[data-testid="status-text"]')?.textContent || ''
      return st.includes('诊断完成')
    },
    { timeout: 25000 },
  )
  const reportText = await page.getByTestId('streaming-report').textContent()
  assert.ok(reportText && reportText.includes('KB-001'), '报告应包含 KB-001 根因')
  await page.screenshot({ path: resolve(screenshotDir, '01_cockpit_diagnosis.png'), fullPage: false })
  console.log('PASS 01_cockpit_diagnosis')

  // 2. 点击 Citation 打开右侧源码/手册溯源高亮抽屉
  await page.getByTestId('citation-card-0').click()
  await page.getByTestId('citation-drawer').waitFor({ state: 'visible' })
  await page.waitForFunction(() => document.querySelectorAll('[data-highlighted="true"]').length > 0)
  await page.screenshot({ path: resolve(screenshotDir, '02_citation_drawer_highlight.png'), fullPage: false })
  await page.getByTestId('close-drawer-btn').click()
  await page.getByTestId('citation-drawer').waitFor({ state: 'hidden' })
  console.log('PASS 02_citation_drawer_highlight')

  // 3. 高危操作 HITL 中断拦截与弹窗审批
  await page.getByTestId('preset-hitl-flushall').click()
  await page.getByTestId('hitl-modal').waitFor({ state: 'visible', timeout: 20000 })
  const modalText = await page.getByTestId('hitl-modal').textContent()
  assert.ok(modalText && modalText.includes('redis_flush'), '弹窗应包含 redis_flush 高危审计项')
  await page.screenshot({ path: resolve(screenshotDir, '03_hitl_interrupt_modal.png'), fullPage: false })

  await page.getByTestId('hitl-reject-btn').click()
  await page.getByTestId('hitl-modal').waitFor({ state: 'hidden', timeout: 15000 })
  const postHitlReport = await page.getByTestId('streaming-report').textContent()
  assert.ok(postHitlReport && postHitlReport.includes('高危指令安全审计'), '恢复后报告应含高危安全审计')
  console.log('PASS 03_hitl_interrupt_and_resume')

  // 4. 切换到 40 条评测与 RAG 对比看板
  await page.getByTestId('tab-eval').click()
  await page.getByTestId('eval-dashboard').waitFor({ state: 'visible' })
  await page.waitForFunction(() => {
    const el = document.querySelector('[data-testid="eval-dashboard"]')
    return el && el.textContent && el.textContent.includes('40 条') && el.textContent.includes('CASE-40')
  })
  await page.screenshot({ path: resolve(screenshotDir, '04_eval_dashboard_40cases.png'), fullPage: false })
  console.log('PASS 04_eval_dashboard_40cases')

  assert.equal(pageErrors.length, 0, `Page errors: ${pageErrors.join('; ')}`)
  assert.equal(apiFailures.length, 0, `API 5xx failures: ${apiFailures.join('; ')}`)
  console.log('ALL E2E CHECKS PASSED')
} finally {
  await browser.close()
}
