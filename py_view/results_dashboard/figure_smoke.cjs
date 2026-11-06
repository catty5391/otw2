// Browser check for the local scientific figure gallery; no external CDN.
const {chromium}=require(process.env.OTW2_PLAYWRIGHT_MODULE||'playwright');
const fs=require('node:fs');const path=require('node:path');
(async()=>{
 const out=process.env.OTW2_FIGURE_BROWSER_OUTPUT||'artifacts/figure_refactor_20261106/browser';fs.mkdirSync(out,{recursive:true});
 const browser=await chromium.launch({headless:true,args:['--no-sandbox']});
 try{
  const page=await browser.newPage({viewport:{width:1440,height:1000}});const errors=[];page.on('pageerror',e=>errors.push(String(e)));
  await page.goto((process.env.OTW2_BASE_URL||'http://127.0.0.1:9999')+'/scientific-figures/',{waitUntil:'domcontentloaded',timeout:30000});
  const images=await page.evaluate(async()=>{const result=[];for(const i of document.images){i.loading='eager';try{await i.decode();}catch(e){throw Error(i.getAttribute('src')+': '+e.message);}result.push({url:i.getAttribute('src'),width:i.naturalWidth,height:i.naturalHeight});}return result;});
  if(images.length!==37||images.some(i=>i.width<=0))throw Error('Expected 37 decoded figures');
  const desktopOverflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1);
  await page.screenshot({path:path.join(out,'desktop.png'),timeout:15000});
  await page.setViewportSize({width:390,height:844});
  const mobileOverflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1);
  await page.screenshot({path:path.join(out,'mobile.png'),timeout:15000});
  if(desktopOverflow||mobileOverflow||errors.length)throw Error(JSON.stringify({desktopOverflow,mobileOverflow,errors}));
  const result={passed:true,figures:images.length,desktopOverflow,mobileOverflow,errors};
  fs.writeFileSync(path.join(out,'summary.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result));
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
