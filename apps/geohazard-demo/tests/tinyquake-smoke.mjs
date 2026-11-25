import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { mkdtemp, rm, mkdir } from "node:fs/promises";
import { tmpdir } from "node:os";
import { resolve } from "node:path";
import { setTimeout as delay } from "node:timers/promises";
import { chromium } from "playwright";
const repo=resolve("../.."), data=await mkdtemp(resolve(tmpdir(),"tinyquake-ui-"));
const python=process.env.PLATFORM_PYTHON || resolve(repo,"platform_backend/.venv/bin/python");
const base="http://127.0.0.1:8027";
const code=`from geohazard_platform.main import create_app
from geohazard_platform.settings import Settings
import uvicorn
uvicorn.run(create_app(Settings(allowed_origins=("${base}",))),host="127.0.0.1",port=8027,log_level="error")`;
const backend=spawn(python,["-c",code],{cwd:repo,env:{...process.env,PYTHONPATH:resolve(repo,"platform_backend/src"),GEOHAZARD_DATA_DIR:data,GEOHAZARD_DEMO:"1",GEOHAZARD_API_TOKEN:""},stdio:["ignore","pipe","pipe"]});
let log="",browser; backend.stdout.on("data",x=>log+=x);backend.stderr.on("data",x=>log+=x);
try {
  let ready=false;
  for(let i=0;i<100;i++){if(backend.exitCode!=null)throw new Error(log);try{if((await fetch(`${base}/api/v1/health`)).ok){ready=true;break;}}catch{}await delay(100);}
  assert.ok(ready,log);
  browser=await chromium.launch({executablePath:process.env.BROWSER_EXECUTABLE||(process.platform==="darwin"?"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome":undefined),headless:true,args:["--enable-unsafe-swiftshader"]});
  const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[];
  page.on("pageerror",e=>errors.push(e.message));
  await page.goto(base);
  await page.getByTestId("backend-status").filter({hasText:"后端已连接"}).waitFor();
  await page.getByRole("button",{name:"TinyQuake 实验",exact:true}).click();
  await page.getByText("尚未收到 TinyQuake 结果",{exact:true}).waitFor();
  console.log("PASS new experimental page has a truthful empty state");
  const payload={schema:"zhifang.tinyquake.result.v1",site_id:"TQ-LAB",device_id:"MOCK-TQ-UI",sensor_id:"reference",boot_id:1,seq:1,model_sha256:"0e1eb00a920ae3daaec7cf142ef8a54373fe1b93b472350e7048b8ae0c1ff1f1",input_source:"REFERENCE",sample_rate_hz:40,sample_count:80,probabilities:[.99934906,.000650934,.000000006],inference_us:12000,quality_valid:true,quality_reason:"reference_vector",reference_index:3,window_start_uptime_ms:null,window_end_uptime_ms:null,frame_id:null,calibration_version:null,preprocessing_id:"tinyquake.reference.preprocessed.v1"};
  assert.equal((await page.request.post(`${base}/api/v1/tinyquake/test`,{data:{payload}})).status(),201);
  await page.getByRole("button",{name:"刷新结果",exact:true}).click();
  await page.getByText("参考波形 · 非实采",{exact:true}).waitFor();
  assert.ok((await page.locator(".tq-probabilities").innerText()).includes("99.93%"));
  assert.ok((await page.locator(".tinyquake-panel").innerText()).includes("不参与正式风险评分"));
  assert.ok((await page.locator(".tq-summary").innerText()).includes("12.000"));
  assert.equal(await page.locator("#platform-device").count(),0);
  console.log("PASS saved reference results show P/S/noise, timing and source separation");
  await page.getByRole("button",{name:"配置与接入",exact:true}).click();
  await page.getByRole("button",{name:"新增连接器",exact:true}).click();
  await page.getByLabel("名称",{exact:true}).fill("UI TinyQuake");
  await page.getByLabel("消息格式",{exact:true}).selectOption("tinyquake_v1");
  assert.equal(await page.getByLabel("数据来源",{exact:true}).inputValue(),"MOCK");
  assert.equal(await page.getByLabel("订阅 Topic",{exact:true}).inputValue(),"zhifang/experimental/tinyquake/v1/{SITE}/+/+/result");
  const response=page.waitForResponse(r=>r.url().endsWith("/connectors")&&r.request().method()==="POST");
  await page.getByRole("button",{name:"保存连接器",exact:true}).click();
  assert.equal((await response).status(),201);
  await page.getByText("TinyQuake · TEST_ONLY",{exact:true}).waitFor();
  console.log("PASS connector format persists the experimental whitelist");
  await page.getByRole("button",{name:"TinyQuake 实验",exact:true}).click();
  await page.setViewportSize({width:390,height:844});
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth+1));
  await mkdir("test-results/tinyquake",{recursive:true});
  await page.mouse.move(385,5); await delay(250);
  await page.screenshot({path:"test-results/tinyquake/mobile.png",fullPage:true});
  await page.setViewportSize({width:1440,height:1000});
  await page.mouse.move(1400,5); await delay(250);
  await page.screenshot({path:"test-results/tinyquake/desktop.png",fullPage:true});
  console.log("PASS mobile/desktop layout stays within viewport");
  await page.clock.install();
  await page.clock.runFor(31000);
  await page.getByText("数据已过期",{exact:true}).waitFor();
  assert.ok(!(await page.locator(".tq-probabilities").innerText()).includes("99.93%"));
  await page.clock.setSystemTime(new Date());
  console.log("PASS old arrivals cannot remain live when the browser clock advances");
  await page.route("**/api/v1/**",route=>route.abort());
  await page.getByRole("button",{name:"刷新后端数据",exact:true}).click();
  await page.getByTestId("backend-status").filter({hasText:"后端失联"}).waitFor();
  await page.getByText("后端数据不可用",{exact:true}).waitFor();
  assert.equal(await page.locator(".tq-probabilities").count(),0);
  assert.deepEqual(errors,[]);
  console.log("PASS backend loss clears model scores without inventing data");
} finally {
  await browser?.close();backend.kill("SIGTERM");
  await new Promise(done=>{if(backend.exitCode!=null)done();else{backend.once("exit",done);setTimeout(()=>{backend.kill("SIGKILL");done();},3000).unref();}});
  await rm(data,{recursive:true,force:true});
}
