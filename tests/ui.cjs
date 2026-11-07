const { chromium }=require('playwright');
const {spawn}=require('node:child_process');
const {mkdtempSync,rmSync}=require('node:fs');
const {tmpdir}=require('node:os');
const {join}=require('node:path');
const assert=require('node:assert/strict');
const temp=mkdtempSync(join(tmpdir(),'tripsci-ui-'));
const children=[];
function server(args){
 const p=spawn('python3',args,{stdio:['ignore','pipe','ignore']});children.push(p);
 return new Promise((resolve,reject)=>{p.stdout.once('data',x=>resolve(String(x).trim()));p.once('error',reject);p.once('exit',c=>reject(Error('Server exited: '+c)))});
}
(async()=>{
 let browser;
 try{
  const api=await server(['backend/app.py','--state',temp,'--port','0']);
  const web=await server(['frontend/serve.py','--port','0','--backend-port',new URL(api).port]);
  browser=await chromium.launch();
  const page=await browser.newPage(), errors=[];
  page.on('pageerror',e=>errors.push(e.message));
  await page.goto(web);
  await page.getByRole('button',{name:'使用示例'}).click();
  await page.getByLabel('项目名称').fill('UI 测试项目');
  await page.getByRole('button',{name:'保存项目'}).click();
  await page.getByRole('heading',{name:'UI 测试项目'}).waitFor();
  await page.getByRole('button',{name:'新聊天',exact:true}).click();
  await page.getByRole('textbox',{name:'消息'}).fill('讨论低频 CTR');
  await page.getByRole('button',{name:'发送消息'}).click();
  await page.getByRole('button',{name:'创建研究计划'}).click();
  await page.getByRole('button',{name:'创建并打开'}).click();
  await page.getByRole('button',{name:'关联项目',exact:true}).click();
  await page.getByRole('button',{name:'关联',exact:true}).click();
  await page.getByRole('button',{name:'确认实验计划'}).click();
  await page.getByLabel('实验预算（1–10）').fill('1');
  await page.getByRole('button',{name:'启动模拟研究'}).click();
  await page.getByRole('button',{name:'保留候选'}).click({timeout:15000});
  await page.getByText('结论：保留候选').waitFor();
  await page.reload();
  await page.getByRole('heading',{name:'UI 测试项目'}).waitFor();
  assert.deepEqual(errors,[]);
  console.log('PASS Chromium: project, chat, draft, attach, training, decision and reload');
 }finally{
  if(browser)await browser.close();
  for(const p of children)p.kill();
  await Promise.all(children.map(p=>p.exitCode!==null||p.signalCode!==null?null:new Promise(r=>p.once('exit',r))));
  rmSync(temp,{recursive:true,force:true});
 }
})().catch(e=>{console.error(e.message);process.exitCode=1});
