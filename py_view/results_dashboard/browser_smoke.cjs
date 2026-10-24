// Run with an isolated Playwright install; no project dependency is required.
// OTW2_PLAYWRIGHT_MODULE=/tmp/<install>/node_modules/playwright node <this-file> <new-output-dir>
const fs = require('node:fs');
const path = require('node:path');
const net = require('node:net');
const { spawn } = require('node:child_process');
const assert = require('node:assert/strict');

const project = path.resolve(__dirname, '../..');
const output = path.resolve(process.argv[2] || '');
if (!process.argv[2] || fs.existsSync(output)) throw new Error('Pass a new, non-existing output directory');
const { chromium } = require(process.env.OTW2_PLAYWRIGHT_MODULE || 'playwright');

async function freePort() {
  const socket = net.createServer();
  await new Promise(resolve => socket.listen(0, '127.0.0.1', resolve));
  const port = socket.address().port;
  await new Promise(resolve => socket.close(resolve));
  return port;
}

async function main() {
  fs.mkdirSync(output, { recursive: true });
  const port = await freePort();
  const service = spawn(path.join(project, '.venv/bin/python'), ['-u', '-m', 'py_view.results_dashboard', '--host', '127.0.0.1', '--port', String(port)], { cwd: project });
  let serviceLog = '';
  service.stdout.on('data', value => serviceLog += value);
  service.stderr.on('data', value => serviceLog += value);
  const base = `http://127.0.0.1:${port}`;
  let browser;
  let page;
  const errors = [];
  const failures = [];
  let downloadedReportVerified = false;
  const checks = [];
  try {
    for (let attempt = 0; attempt < 100; attempt++) {
      try { if ((await fetch(base + '/health')).ok) break; } catch (_) {}
      if (attempt === 99) throw new Error('Temporary dashboard did not become healthy');
      await new Promise(resolve => setTimeout(resolve, 100));
    }
    browser = await chromium.launch({ headless: true, timeout: 45000,
      args: ['--no-sandbox', '--disable-dev-shm-usage', '--no-proxy-server', '--disable-gpu', '--disable-software-rasterizer'] });
    page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, deviceScaleFactor: 1 });
    page.setDefaultTimeout(30000);
    page.on('pageerror', error => errors.push(String(error)));
    page.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });
    page.on('requestfailed', request => failures.push({ url: request.url(), reason: request.failure() }));
    await page.goto(base, { waitUntil: 'networkidle', timeout: 60000 });
    await page.waitForFunction(() => document.querySelector('#diagnosticMemberInfo').textContent.includes('原杆 #877'), null, { timeout: 60000 });
    assert.equal(await page.locator('#diagnosticCases .quality-case').count(), 3);
    const evidence = await page.locator('#diagnosticCases').innerText();
    assert(evidence.includes('590 步') && evidence.includes('越界') && evidence.includes('step 499'));
    assert.equal(await page.locator('#speedup').innerText(), '待评估');
    checks.push('three historical cases, first domain event, independent quality, no unfair speed ratio');
    for (const caseId of ['baseline', 'elastic_877_878', 'fine_sparse']) {
      await page.locator('#diagnosticCase').selectOption(caseId);
      await page.waitForFunction(() => !document.querySelector('#diagnosticMemberInfo').textContent.includes('读取历史'));
      assert((await page.locator('#diagnosticMemberInfo').innerText()).includes('原杆 #877'));
      checks.push(`case switch ${caseId}`);
    }
    await page.locator('#diagnosticMember').selectOption('878');
    await page.waitForFunction(() => document.querySelector('#diagnosticMemberInfo').textContent.includes('原杆 #878'));
    assert((await page.locator('#diagnosticReference').innerText()).includes('四段参考首段'));
    for (const id of ['diagnosticCurveChart', 'diagnosticMemberChart', 'diagnosticStrainChart']) {
      assert(await page.locator('#' + id).evaluate(canvas => canvas.width > 0 && canvas.height > 0 && canvas.toDataURL().length > 1000));
    }
    checks.push('878 selection, scoped reference checkpoint, three rendered diagnostic canvases');
    await page.locator('#cyclic').scrollIntoViewIfNeeded();
    await page.screenshot({ path: path.join(output, 'desktop_cyclic.png') });
    await page.locator('#diagnosticCases').scrollIntoViewIfNeeded();
    await page.screenshot({ path: path.join(output, 'desktop_diagnostics.png') });
    await page.locator('#diagnosticMemberChart').scrollIntoViewIfNeeded();
    await page.screenshot({ path: path.join(output, 'desktop_member_charts.png') });
    const [download] = await Promise.all([
      page.waitForEvent('download'), page.locator('a[href="/download?key=convergence-report"]').first().click(),
    ]);
    await download.saveAs(path.join(output, 'downloaded_convergence_report.md'));
    assert(fs.statSync(path.join(output, 'downloaded_convergence_report.md')).size > 100);
    downloadedReportVerified = true;
    checks.push('actual report download');
    await page.locator('#forces').scrollIntoViewIfNeeded();
    await page.locator('#forceLoad').click();
    await page.waitForFunction(() => document.querySelector('#forceLoading').classList.contains('hidden'));
    assert((await page.locator('#forceMemberCount').innerText()).includes('1,528'));
    await page.locator('#forceComponent').selectOption('my');
    await page.locator('#forceLoad').click();
    await page.waitForFunction(() => document.querySelector('#forceLoading').classList.contains('hidden'));
    assert((await page.locator('#forceMemberCount').innerText()).includes('1,528'));
    checks.push('old complete six-component dataset force view renders 1528 members');
    await page.setViewportSize({ width: 390, height: 844 });
    await page.locator('#diagnosticCases').scrollIntoViewIfNeeded();
    await page.waitForTimeout(400);
    await page.screenshot({ path: path.join(output, 'mobile_diagnostics.png') });
    const layout = await page.evaluate(() => ({ width: window.innerWidth, scrollWidth: document.documentElement.scrollWidth,
      offenders: [...document.querySelectorAll('body *')].filter(element => element.getBoundingClientRect().right > window.innerWidth + 2).slice(0,15).map(element => ({ tag:element.tagName,id:element.id,className:element.className,right:element.getBoundingClientRect().right })) }));
    assert(layout.scrollWidth <= layout.width + 2, JSON.stringify(layout));
    checks.push('390px responsive view has no horizontal page overflow');
    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.locator('a.nav-link[href="#tianmaqu"]').click();
    await page.waitForFunction(() => document.querySelectorAll('#tmqCases tr').length === 3);
    await page.locator('#tmqHysteresis').scrollIntoViewIfNeeded();
    await page.waitForFunction(() => document.querySelector('#tmqHysteresis').naturalWidth > 0);
    assert((await page.locator('#tmqMetrics').innerText()).includes('10,200 / 10,200'));
    assert((await page.locator('#tmqCases').innerText()).includes('534.16'));
    assert((await page.locator('#tianmaqu').innerText()).includes('已接入独立全塔试验'));
    await page.screenshot({ path: path.join(output, 'desktop_tmq.png') });
    checks.push('TMQ navigation, three real result rows, full hysteresis image, explicit validation boundary');
    const [viewer] = await Promise.all([page.waitForEvent('popup'), page.locator('#tmqReplay').click()]);
    viewer.on('pageerror', error => errors.push(String(error)));
    viewer.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });
    await viewer.waitForLoadState('load');
    await viewer.waitForFunction(() => document.querySelector('#status').textContent.includes('3400/3400'));
    assert.equal(await viewer.locator('#case option').count(), 3);
    await viewer.locator('#case').selectOption('2');
    await viewer.locator('#step').evaluate(slider => { slider.value = '100'; slider.dispatchEvent(new Event('input', { bubbles: true })); });
    assert((await viewer.locator('#status').innerText()).includes('100/3400'));
    await viewer.locator('#full').click();
    assert((await viewer.locator('#status').innerText()).includes('3400/3400'));
    assert(await viewer.locator('#plot').evaluate(canvas => canvas.toDataURL().length > 1000));
    await viewer.screenshot({ path: path.join(output, 'tmq_replay.png') });
    await viewer.close();
    checks.push('TMQ standalone page, three cases, time-order slider and full-curve reset');
    await page.locator('#tmqTowerPanel').scrollIntoViewIfNeeded();
    await page.waitForFunction(() => document.querySelector('#tmqTowerImage').naturalWidth > 0);
    assert((await page.locator('#tmqTowerStatus').innerText()).includes('1528 根杆件'));
    await page.screenshot({ path: path.join(output, 'desktop_tmq_tower.png') });
    const [towerViewer] = await Promise.all([page.waitForEvent('popup'), page.locator('#tmqTowerReplay').click()]);
    towerViewer.on('pageerror', error => errors.push(String(error)));
    await towerViewer.waitForLoadState('load');
    assert((await towerViewer.locator('body').innerText()).includes('实际结果'));
    await towerViewer.locator('#frame').evaluate(slider => { slider.value = '100'; slider.dispatchEvent(new Event('input', { bubbles: true })); });
    assert((await towerViewer.locator('#state').innerText()).includes('接受步 100'));
    assert(await towerViewer.locator('#curve').evaluate(canvas => canvas.toDataURL().length > 1000));
    await towerViewer.screenshot({ path: path.join(output, 'tmq_tower_replay.png') });
    await towerViewer.close();
    checks.push('TMQ full-tower published evidence, loaded figure, actual time-order replay');
    await page.locator('#tmqWeaknessPanel').scrollIntoViewIfNeeded();
    await page.waitForFunction(() => document.querySelector('#tmqWeaknessImage').naturalWidth > 0);
    assert((await page.locator('#tmqWeaknessStatus').innerText()).includes('9–13.2 m'));
    const [weaknessViewer] = await Promise.all([page.waitForEvent('popup'), page.locator('#tmqWeaknessReplay').click()]);
    weaknessViewer.on('pageerror', error => errors.push(String(error)));
    await weaknessViewer.waitForLoadState('load');
    assert((await weaknessViewer.locator('#findings').innerText()).includes('暂不认定唯一控制节间'));
    assert.equal(await weaknessViewer.locator('#member option').count(), 1528);
    assert((await weaknessViewer.locator('#coverage').innerText()).includes('409个接受步'));
    await weaknessViewer.locator('#run').selectOption('extended');
    await weaknessViewer.locator('#member').selectOption('877');
    await weaknessViewer.locator('#projection').selectOption('xy');
    assert((await weaknessViewer.locator('#coverage').innerText()).includes('264个接受步'));
    assert((await weaknessViewer.locator('#memberInfo').innerText()).includes('未记录进入压屈软化'));
    assert((await weaknessViewer.locator('#memberInfo').innerText()).includes('0.999920'));
    await weaknessViewer.locator('#member').selectOption('825');
    assert((await weaknessViewer.locator('#memberInfo').innerText()).includes('首次记录 step 104'));
    assert(await weaknessViewer.locator('#map').evaluate(c => c.toDataURL().length > 1000));
    assert(await weaknessViewer.locator('#memberCurve').evaluate(c => c.toDataURL().length > 1000));
    await weaknessViewer.screenshot({ path: path.join(output, 'weakness_desktop.png') });
    await weaknessViewer.setViewportSize({ width: 390, height: 844 });
    await weaknessViewer.locator('#findings').scrollIntoViewIfNeeded();
    await weaknessViewer.screenshot({ path: path.join(output, 'weakness_mobile.png') });
    assert(await weaknessViewer.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 2));
    await weaknessViewer.close();
    checks.push('weakness report, both rotation definitions, 1528 selectable members, partial-run/near-threshold distinction, maps, local curve and mobile layout');
    await page.setViewportSize({ width: 390, height: 844 });
    await page.locator('#tmqHysteresis').scrollIntoViewIfNeeded();
    await page.waitForTimeout(400);
    await page.screenshot({ path: path.join(output, 'mobile_tmq.png') });
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 2));
    checks.push('TMQ 390px responsive view has no horizontal page overflow');
    // Chromium hands attachment navigations to the download manager using
    // ERR_ABORTED. Exempt only this exact URL after verifying the saved file;
    // preserve the event separately and reject every other failed request.
    const expectedDownloadAborts = failures.filter(item => downloadedReportVerified
      && item.url === base + '/download?key=convergence-report' && item.reason?.errorText === 'net::ERR_ABORTED');
    const unexpectedFailures = failures.filter(item => !expectedDownloadAborts.includes(item));
    assert.equal(errors.length, 0, JSON.stringify(errors));
    assert.equal(unexpectedFailures.length, 0, JSON.stringify(unexpectedFailures));
    fs.writeFileSync(path.join(output, 'browser_result.json'), JSON.stringify({ status: 'passed', browser: 'Chromium headless', playwright: require(path.join(process.env.OTW2_PLAYWRIGHT_MODULE, 'package.json')).version, port, checks, errors, failed_requests: unexpectedFailures, expected_download_navigation_aborts: expectedDownloadAborts }, null, 2));
    console.log(JSON.stringify({ status: 'passed', port, checks, output }, null, 2));
  } catch (error) {
    if (page && !page.isClosed()) await page.screenshot({ path: path.join(output, 'failure.png') }).catch(() => {});
    if (page && !page.isClosed()) fs.writeFileSync(path.join(output, 'failure.html'), await page.content().catch(() => ''));
    fs.writeFileSync(path.join(output, 'browser_result.json'), JSON.stringify({ status: 'failed', error: String(error), checks, errors, failed_requests: failures }, null, 2));
    throw error;
  } finally {
    if (browser) await browser.close();
    service.kill('SIGTERM');
    fs.writeFileSync(path.join(output, 'server.log'), serviceLog);
  }
}
main().catch(error => { console.error(error); process.exitCode = 1; });
