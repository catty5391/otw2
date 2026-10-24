// Actual browser verification of the published B1 diagnosis and preserved old viewers.
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const { chromium } = require(process.env.OTW2_PLAYWRIGHT_MODULE || 'playwright');
const output = path.resolve(process.argv[2] || '');
if (!process.argv[2] || fs.existsSync(output)) throw Error('Provide a new browser output directory');
const base = process.env.OTW2_BASE_URL || 'http://127.0.0.1:9999';
const route = '/tmq/followup_results/B1_20261024';

async function main() {
  fs.mkdirSync(output, { recursive: true });
  const browser = await chromium.launch({ headless: true, timeout: 45000,
    args: ['--no-sandbox', '--disable-dev-shm-usage', '--no-proxy-server'] });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, deviceScaleFactor: 1 });
  page.setDefaultTimeout(30000);
  const errors = [], failedRequests = [], checks = [];
  page.on('pageerror', e => errors.push(String(e)));
  page.on('console', m => { if (m.type() === 'error' && !m.location().url.includes('favicon')) errors.push(m.text()); });
  page.on('requestfailed', r => failedRequests.push({ url: r.url(), failure: r.failure() }));
  let failure = null;
  try {
    const response = await page.request.get(base + '/api/tian-ma-qu');
    assert(response.ok());
    const api = await response.json();
    assert.equal(api.b1_diagnostics.new_FE_runs, 0);
    assert.equal(api.b1_diagnostics.initial_state_matches, 13);
    assert.equal(api.b1_diagnostics.physical_validation, 'unvalidated');
    checks.push('API preserves B1 scope and initial-state evidence');

    await page.goto(base + '/#tianmaqu', { waitUntil: 'networkidle' });
    await page.locator('#tmqB1Panel').waitFor({ state: 'visible' });
    assert((await page.locator('#tmqB1Status').innerText()).includes('13/13'));
    assert.equal(await page.locator('#tmqB1Report').getAttribute('href'), route + '/index.html');
    await page.locator('#tmqB1Panel').scrollIntoViewIfNeeded();
    await page.screenshot({ path: path.join(output, 'homepage.png') });
    checks.push('homepage displays B1 and its report link');

    await page.goto(base + route + '/index.html', { waitUntil: 'networkidle' });
    await page.waitForFunction(() => document.querySelector('#responseStatus').textContent.includes('项观察量'));
    assert.equal(await page.locator('#responseTable tbody tr').count(), 5);
    assert((await page.locator('#responseTable').innerText()).includes('未通过'));
    await page.screenshot({ path: path.join(output, 'diagnostics_desktop.png'), fullPage: true });
    checks.push('default 80-segment 45-degree control outputs render failures');

    await page.locator('#groupFilter').selectOption('attachment');
    const text = await page.locator('#responseTable').innerText();
    assert(text.includes('14.309%'));
    await page.locator('#failedOnly').check();
    assert((await page.locator('#responseTable tbody tr').count()) > 0);
    assert.equal(await page.locator('#responseTable td.pass').count(), 0);
    await page.locator('#projection').scrollIntoViewIfNeeded();
    await page.screenshot({ path: path.join(output, 'attachment_failures.png') });
    checks.push('attachment primary-direction 14.309% error visible; failed-only filter works');

    await page.locator('#failedOnly').uncheck();
    await page.locator('#angleFilter').selectOption('90');
    assert((await page.locator('#responseTable').innerText()).includes('0.151%'));
    await page.locator('#caseFilter').selectOption('bare_checked');
    await page.locator('#groupFilter').selectOption('control');
    assert.equal(await page.locator('#responseTable tbody tr').count(), 5);
    checks.push('direction and model filters select distinct result rows');

    const images = await page.locator('img').evaluateAll(nodes => nodes.map(n => ({ src: n.getAttribute('src'), ok: n.complete && n.naturalWidth > 0 })));
    assert(images.every(i => i.ok));
    checks.push('all scientific figures load with nonzero dimensions');
    const csv = await page.request.get(base + route + '/wind_projection/static_observations.csv');
    assert(csv.ok()); assert((await csv.text()).includes('absolute_error_m'));
    const report = await page.request.get(base + route + '/REPORT.md');
    assert(report.ok()); assert((await report.text()).includes('14.3093%'));
    checks.push('raw CSV and detailed report downloads work');

    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(base + route + '/index.html', { waitUntil: 'networkidle' });
    await page.waitForFunction(() => document.querySelector('#responseStatus').textContent.includes('项观察量'));
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
    await page.screenshot({ path: path.join(output, 'diagnostics_mobile.png'), fullPage: true });
    checks.push('390px mobile layout fits viewport');

    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.goto(base + route + '/modal_view/index.html', { waitUntil: 'networkidle' });
    await page.waitForFunction(() => document.querySelector('#modeInfo').textContent.includes('Hz'));
    assert.equal(await page.locator('#caseSelect').inputValue(), 'coupled_80_checked');
    await page.locator('[data-shape="1"]').click();
    assert((await page.locator('#modeInfo').innerText()).includes('第90阶'));
    await page.locator('#caseSelect').selectOption('coupled_20_checked');
    await page.waitForFunction(() => document.querySelector('#modeInfo').textContent.includes('Hz'));
    await page.locator('[data-shape="1"]').click();
    assert((await page.locator('#modeInfo').innerText()).includes('第114阶'));
    await page.locator('#systemCanvas').scrollIntoViewIfNeeded();
    await page.screenshot({ path: path.join(output, 'manifest_viewer.png') });
    checks.push('manifest viewer switches models and matches X shape by saved identity');

    for (const url of ['/tmq/modal_results/index.html', '/tmq/wind_speed_results/index.html']) {
      await page.goto(base + url, { waitUntil: 'networkidle' });
      assert((await page.locator('h1').innerText()).length > 5);
    }
    checks.push('old modal and wind-speed pages remain usable');
    assert.deepEqual(errors, []);
    assert.deepEqual(failedRequests, []);
  } catch (e) { failure = String(e.stack || e); }
  finally {
    fs.writeFileSync(path.join(output, 'browser_result.json'), JSON.stringify({
      passed: !failure, base, checks, check_count: checks.length, errors, failedRequests, failure,
      new_FE_runs: 0, browser: 'Chromium/Playwright', checked_at_utc: new Date().toISOString(),
    }, null, 2));
    await browser.close();
  }
  if (failure) throw Error(failure);
  console.log(JSON.stringify({ passed: true, checks: checks.length, output }));
}
main().catch(e => { console.error(e); process.exitCode = 1; });
