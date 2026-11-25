import { chromium } from 'playwright';
import assert from 'node:assert/strict';
import { mkdir } from 'node:fs/promises';
const output=process.env.AIR_WATER_TEST_OUTPUT;
assert.ok(output,'Set AIR_WATER_TEST_OUTPUT to an explicit artifact directory');
await mkdir(output,{recursive:true});
const browser=await chromium.launch({executablePath:process.env.BROWSER_EXECUTABLE,headless:true});
try {
 const page=await browser.newPage({viewport:{width:1440,height:1100}});
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto(process.env.PLATFORM_URL || 'http://127.0.0.1:18765');
 const panel=page.getByTestId('provisional-risk');
 await panel.getByText('NODE01_AIR_WATER_20261122_REVIEW',{exact:false}).waitFor();
 const text=await page.getByTestId('air-water-values').innerText();
 assert.match(text,/AIN0 100\.00%/);assert.match(text,/AIN1 100\.00%/);assert.match(text,/AIN2 100\.00%/);
 assert.equal(await page.getByTestId('air-water-trends').locator('svg').count(),3);
 assert.match(await panel.innerText(),/非体积含水率/);
 assert.match(await panel.innerText(),/MOCK/);
 await panel.screenshot({path:output+'/three-channel-panel.png'});
 assert.deepEqual(errors,[]);
 console.log('PASS: MOCK three-channel values, version, units, three trends and no page errors');
} finally {await browser.close();}
