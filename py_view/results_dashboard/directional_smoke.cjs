/* Read-only browser check against the running result service. */
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const { chromium } = require(process.env.OTW2_PLAYWRIGHT_MODULE || 'playwright');

(async () => {
  const base = process.env.OTW2_DASHBOARD_URL || 'http://127.0.0.1:9999';
  const out = process.argv[2];
  if (!out || fs.existsSync(out)) throw new Error('Supply a NEW screenshot directory');
  fs.mkdirSync(out, {recursive:true});
  const browser = await chromium.launch({headless:true});
  const errors = [], checks = [];
  try {
    const page = await browser.newPage({viewport:{width:1440,height:1000}});
    page.on('pageerror', e=>errors.push(e.message));
    await page.goto(base+'/#tianmaqu', {waitUntil:'domcontentloaded'});
    await page.locator('#tmqWindPanel').waitFor({state:'visible',timeout:60000});
    assert.match(await page.locator('#tmqWindStatus').innerText(),/8\/8/);
    await page.locator('#tmqWindPanel').scrollIntoViewIfNeeded();
    await page.locator('#tmqWindImage').evaluate(img=>img.decode());
    checks.push('Homepage wind panel reports actual 8/8 and loads its plot');
    await page.locator('#tmqWindPanel').screenshot({path:path.join(out,'homepage_wind.png')});
    await page.goto(base+'/tmq/directional_results_v2/index.html',{waitUntil:'networkidle'});
    assert.equal(await page.locator('tbody tr').count(),8);
    assert.equal(await page.locator('tbody tr').filter({hasText:'通过'}).count(),8);
    assert.equal(await page.locator('img').count(),2);
    for (const image of await page.locator('img').all()) await image.evaluate(img=>img.decode());
    assert.match(await page.locator('body').innerText(),/不是极限推覆/);
    checks.push('Standalone report has 8 verified cases, two actual figures and limits');
    await page.screenshot({path:path.join(out,'report_desktop.png'),fullPage:true});
    const data=await page.request.get(base+'/api/tian-ma-qu');
    const body=await data.json();
    assert.equal(body.directional_wind.passed,true);
    assert.equal(body.directional_wind.validated_for_design,false);
    checks.push('API publishes verification without claiming engineering calibration');
    await page.setViewportSize({width:390,height:844});
    await page.reload({waitUntil:'networkidle'});
    assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
    await page.screenshot({path:path.join(out,'report_mobile.png'),fullPage:true});
    checks.push('Mobile page has no horizontal viewport overflow');
    assert.deepEqual(errors,[]);
    checks.push('No browser page errors');
    const result={passed:true,checks,errors};
    fs.writeFileSync(path.join(out,'browser_result.json'),JSON.stringify(result,null,2)+'\n');
    process.stdout.write(JSON.stringify(result)+'\n');
  } finally { await browser.close(); }
})().catch(e=>{console.error(e);process.exitCode=1;});
