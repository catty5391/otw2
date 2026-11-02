/* Real-data publication check. Does not calculate or change scientific results. */
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const {chromium} = require(process.env.OTW2_PLAYWRIGHT_MODULE || 'playwright');

(async () => {
  const base = process.env.OTW2_DASHBOARD_URL || 'http://127.0.0.1:9999';
  const out = process.argv[2];
  if (!out || fs.existsSync(out)) throw new Error('Supply a new output directory');
  fs.mkdirSync(out,{recursive:true});
  const browser = await chromium.launch({headless:true,args:['--disable-gpu']});
  const checks = [], errors = [], resources = [];
  const screenshots = process.env.OTW2_RAIN_SCREENSHOTS !== '0';
  const toTop = async page => {
    await page.evaluate(()=>{document.documentElement.style.scrollBehavior='auto';window.scrollTo({top:0,left:0,behavior:'instant'});});
    await page.waitForFunction(()=>window.scrollY===0);
  };
  try {
    const page = await browser.newPage({viewport:{width:1440,height:1000}});
    page.on('pageerror',error=>errors.push(error.message));
    const response = await page.request.get(base+'/rain-loading/results/summary.json');
    assert.equal(response.status(),200);
    const summary = await response.json();
    assert.ok(summary.figures?.length,'Actual figures must be present');
    assert.ok(summary.verification?.checks?.length,'Actual verification evidence must be present');
    const directModule = process.env.OTW2_RAIN_DIRECT === '1';
    if (directModule) await page.goto(base+'/rain-loading/');
    else {
      await page.goto(base+'/');
      await page.getByRole('link',{name:/雨谱与风雨荷载.*雨滴粒径/}).first().click();
    }
    await page.waitForFunction(()=>document.body.dataset.ready==='true');
    assert.ok((await page.locator('#rainStatus').innerText()).length>3);
    assert.equal(await page.locator('#rainFigures img').count(),summary.figures.length);
    assert.equal(await page.locator('#rainChecks tbody tr').count(),summary.verification.checks.length);
    const tableText = await page.locator('#rainTables').innerText();
    assert.ok(!tableText.includes('11.635517478768588'),'Long floating-point tails should be rounded only in display');
    assert.match(tableText,/塔身/);assert.match(tableText,/导线/);
    if (summary.date) assert.equal(await page.locator('#rainDate').innerText(),summary.generated_at||summary.date);
    for (const image of await page.locator('#rainFigures img').all()) {
      await image.scrollIntoViewIfNeeded();
      await image.evaluate(img=>img.decode());
      assert.ok(await image.evaluate(img=>img.naturalWidth>100 && img.naturalHeight>100));
    }
    assert.equal(await page.locator('body').getAttribute('data-figure-error'),null);
    checks.push((directModule ? 'Direct module entry' : 'Homepage entry')+', actual summary, all declared figures and check rows render');
    const urls = await page.locator('.rain-study a[href]').evaluateAll(elements=>[...new Set(elements.map(a=>a.href).filter(href=>href.includes('/rain-loading/')&&!href.includes('#')))]);
    for (const url of urls) {
      const result = await page.request.get(url);assert.equal(result.status(),200,url);
      const mime=result.headers()['content-type']||'';
      if (url.endsWith('.md')||url.endsWith('.csv')||url.endsWith('.json')) assert.match(mime,/charset=utf-8/,url);
      if (url.endsWith('.md')) assert.ok(!(await result.text()).includes('\uFFFD'),'Report must not contain replacement characters');
      resources.push({url:url.replace(base,''),status:result.status(),content_type:mime});
    }
    checks.push('All displayed rain report/data/figure links return 200; text declares UTF-8');
    await toTop(page);
    assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
    if (screenshots) {
      await page.screenshot({path:path.join(out,'desktop.png')});
      await page.screenshot({path:path.join(out,'desktop_full.png'),fullPage:true});
    }
    await page.setViewportSize({width:390,height:844});
    await page.reload();await page.waitForFunction(()=>document.body.dataset.ready==='true');
    for (const image of await page.locator('#rainFigures img').all()) {
      await image.scrollIntoViewIfNeeded();await image.evaluate(img=>img.decode());
    }
    assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
    await toTop(page);
    if (screenshots) {
      await page.screenshot({path:path.join(out,'mobile.png')});
      await page.screenshot({path:path.join(out,'mobile_full.png'),fullPage:true});
    }
    await page.locator('#menuButton').click();
    assert.equal(await page.locator('#menuButton').getAttribute('aria-expanded'),'true');
    await page.locator('#siteSidebar .nav-link').filter({hasText:'雨谱与风雨荷载'}).click();
    await page.waitForFunction(()=>document.body.dataset.ready==='true');
    checks.push('Desktop and 390px mobile have no viewport overflow; mobile navigation works');
    // Isolated browser fixture checks that absent data is not rendered as success.
    const missing = await browser.newPage({viewport:{width:390,height:844}});
    await missing.route('**/rain-loading/results/summary.json',route=>route.fulfill({status:404,body:'not ready'}));
    await missing.goto(base+'/rain-loading/');
    await missing.waitForFunction(()=>document.body.dataset.ready==='unavailable');
    assert.equal(await missing.locator('#rainFigures img').count(),0);
    assert.match(await missing.locator('#rainPending').innerText(),/真实计算产物/);
    if (screenshots) await missing.screenshot({path:path.join(out,'missing_data.png'),fullPage:true});
    await missing.close();checks.push('Missing summary shows an unavailable state with no fabricated plots');
    assert.deepEqual(errors,[]);checks.push('No browser JavaScript errors');
    const result={passed:true,base,checks,resources,screenshots,figure_count:summary.figures.length,
      verification_count:summary.verification.checks.length,errors};
    fs.writeFileSync(path.join(out,'browser_result.json'),JSON.stringify(result,null,2)+'\n');
    process.stdout.write(JSON.stringify(result)+'\n');
  } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
