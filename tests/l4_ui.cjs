const fs = require('fs');
const http = require('http');
const assert = require('assert');
const {chromium} = require('playwright');
const root=process.cwd();
const fixture=JSON.parse(fs.readFileSync('l4-ui-fixture.json','utf8'));
const server=http.createServer((req,res)=>{
  const path=req.url.split('?')[0];
  if(path==='/data/l4_current.json'){res.setHeader('Content-Type','application/json');return res.end(JSON.stringify(fixture));}
  if(path==='/data/l4_daily.csv')return res.end('snapshot_date,project_id,test_count,completed_tests\n2026-10-13,67,3,1\n');
  if(path==='/'){
    let html=fs.readFileSync(root+'/index.html','utf8').replace(/<script[^>]*src="https[^>]*><\/script>/g,'');
    html=html.replace(/<script>\s*"use strict";[\s\S]*?<\/script>/,'<script>function showPage(name){document.querySelectorAll(".page").forEach(p=>p.classList.toggle("on",p.id==="page-"+name));} document.addEventListener("DOMContentLoaded",()=>document.querySelectorAll(".page-nav button").forEach(b=>b.onclick=()=>showPage(b.dataset.page)));</script>');
    return res.end(html);
  }
  if(['/l4.css','/l4.js'].includes(path)){res.setHeader('Content-Type',path.endsWith('js')?'application/javascript':'text/css');return res.end(fs.readFileSync(root+path));}
  res.statusCode=404;res.end();
});
(async()=>{
  await new Promise(r=>server.listen(0,'127.0.0.1',r));
  const browser=await chromium.launch({headless:true});
  const page=await browser.newPage({viewport:{width:1280,height:1000}});
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto('http://127.0.0.1:'+server.address().port+'/#l4-overview');
  await page.waitForSelector('#l4Kpis .kpi');
  assert((await page.locator('#l4Kpis').innerText()).includes('33.3%'));
  await page.click('[data-page="l4-equipment"]');
  assert.equal(await page.locator('#l4EquipmentRows tr').count(),100);
  await page.click('[data-l4-next="equipment"]');
  assert.equal(await page.locator('#l4EquipmentRows tr').count(),3);
  await page.click('[data-l4-prev="equipment"]');
  await page.locator('#page-l4-equipment [data-l4-field="status"]').selectOption('No tests linked');
  assert.equal(await page.locator('#l4EquipmentRows tr').count(),100);
  await page.locator('#page-l4-equipment [data-l4-reset]').click();
  await page.locator('#l4EquipmentRows [data-l4-equipment="0"]').click();
  assert.equal(await page.locator('#l4TestRows tr').count(),1);
  await page.locator('#l4TestRows [data-l4-test="0"]').click();
  assert((await page.locator('#l4AttemptBody').innerText()).includes('<img src=x onerror=alert(1)>'));
  assert.equal(await page.locator('#l4AttemptBody img').count(),0);
  await page.locator('#l4ClearEquipment').click();
  assert.equal(await page.locator('#l4TestRows tr').count(),3);
  await page.locator('#page-l4-tests [data-l4-field="status"]').selectOption('Retest required');
  assert.equal(await page.locator('#l4TestRows tr').count(),1);
  const downloadPromise=page.waitForEvent('download');
  await page.locator('#page-l4-tests [data-l4-export]').click();
  const download=await downloadPromise;
  assert(download.suggestedFilename().includes('L4-tests'));
  await page.locator('#page-l4-tests [data-l4-reset]').click();
  await page.click('[data-page="l4-overview"]');
  await page.screenshot({path:'l4-desktop.png',fullPage:true});
  await page.setViewportSize({width:390,height:900});
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth));
  await page.screenshot({path:'l4-mobile.png',fullPage:true});
  await page.evaluate(()=>document.documentElement.dataset.theme='dark');
  await page.screenshot({path:'l4-dark.png',fullPage:true});
  assert.deepEqual(errors,[]);
  await browser.close();server.close();
  console.log('Browser checks passed: overview totals, pagination, missing scope, drill-down, attempts, escaping, filters, CSV export, mobile layout, dark theme.');
})().catch(e=>{console.error(e);server.close();process.exit(1);});
