/* Read-only validation of the actual published wind-speed exploration. */
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const {chromium} = require(process.env.OTW2_PLAYWRIGHT_MODULE || 'playwright');

(async () => {
  const base=process.env.OTW2_DASHBOARD_URL || 'http://127.0.0.1:9999';
  const out=process.argv[2];
  if (!out || fs.existsSync(out)) throw new Error('Supply a new screenshot directory');
  fs.mkdirSync(out,{recursive:true});
  const browser=await chromium.launch({headless:true}), errors=[], checks=[];
  try {
    const page=await browser.newPage({viewport:{width:1440,height:1000}});
    page.on('pageerror',e=>errors.push(e.message));
    const response=await page.request.get(base+'/api/tian-ma-qu');
    const data=(await response.json()).wind_speed;
    assert.equal(data.coarse_case_count,8);
    assert.equal(data.all_saved_evidence_valid,true);
    assert.equal(data.engineering_ultimate_wind_speed_established,false);
    checks.push('API exposes completed evidence without claiming engineering collapse');
    await page.goto(base+'/#tianmaqu',{waitUntil:'domcontentloaded'});
    await page.locator('#tmqSpeedPanel').waitFor({state:'visible',timeout:60000});
    assert.match(await page.locator('#tmqSpeedStatus').innerText(),new RegExp(`${data.cases.length} 次计算`));
    await page.locator('#tmqSpeedPanel').scrollIntoViewIfNeeded();
    await page.locator('#tmqSpeedImage').evaluate(img=>img.decode());
    await page.locator('#tmqSpeedPanel').screenshot({path:path.join(out,'homepage_wind_speed.png')});
    checks.push('Homepage shows the actual calculation count and wind-speed plot');
    await page.goto(base+'/tmq/wind_speed_results/index.html',{waitUntil:'networkidle'});
    assert.equal(await page.locator('table').first().locator('tbody tr').count(),data.cases.length);
    assert.equal(await page.locator('img').count(),2);
    for (const img of await page.locator('img').all()) await img.evaluate(i=>i.decode());
    assert.match(await page.locator('body').innerText(),/不收敛不等于结构倒塌/);
    assert.match(await page.locator('body').innerText(),/停止位置复核/);
    assert.match(await page.locator('body').innerText(),/末段\/初段/);
    await page.screenshot({path:path.join(out,'wind_speed_desktop.png'),fullPage:true});
    checks.push('Report has every actual case, two plots, sensitivity checks and stopping-state diagnostics');
    await page.setViewportSize({width:390,height:844});
    await page.reload({waitUntil:'networkidle'});
    assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
    await page.screenshot({path:path.join(out,'wind_speed_mobile.png'),fullPage:true});
    checks.push('Mobile report has no horizontal viewport overflow');
    assert.deepEqual(errors,[]);checks.push('No browser page errors');
    const result={passed:true,case_count:data.cases.length,checks,errors};
    fs.writeFileSync(path.join(out,'browser_result.json'),JSON.stringify(result,null,2)+'\n');
    process.stdout.write(JSON.stringify(result)+'\n');
  } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
