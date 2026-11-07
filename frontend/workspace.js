'use strict';
const $=q=>document.querySelector(q), E=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const modeNames={local:'本机执行',hybrid:'本机 Agent · 远端训练',remote:'远端执行'};
const statusNames={ready:'待调度',waiting:'训练中',paused:'已暂停',completed:'待评审'};
const modes={local:[],hybrid:[['training_host','远端训练连接'],['delivery','代码交付方式']],remote:[['agent_host','远端 Agent 连接'],['remote_dir','远端工作目录']]};
let S=null,page='项目',id='',project='',busy=false,timer,refreshing=false,epoch=0;
const drafts={};
const all=k=>S?.[k]||[], get=(k,i)=>all(k).find(x=>x.id===i), task=p=>get('task',p?.task);
const current=()=>get('workspace',project)||all('workspace')[0];
const state=p=>p.decision?'已完成':statusNames[task(p)?.status]||'草稿';
const label=(text)=>'<span class="pill">'+E(text)+'</span>';
const mark='<img class="trip-mark" src="/TripSci-icon.png" width="32" height="32" alt="">';
const btn=(name,act,primary=false,key='')=>'<button type="button" '+(primary?'class="primary" ':'')+'data-act="'+E(act)+'" data-key="'+E(key)+'">'+E(name)+'</button>';
const pick=(name,options,selected='')=>'<select class="control" name="'+E(name)+'" aria-label="'+E(name)+'">'+options.map(([v,t])=>'<option value="'+E(v)+'" '+(selected===v?'selected':'')+'>'+E(t)+'</option>').join('')+'</select>';
const input=(name,title,value='',type='text')=>'<label>'+E(title)+'<input name="'+name+'" type="'+type+'" required value="'+E(value)+'" '+(type==='number'?'step="any"':'')+'></label>';
const area=(name,title,value='')=>'<label>'+E(title)+'<textarea name="'+name+'" required>'+E(value)+'</textarea></label>';
const head=(name,actions='')=>'<header class="head"><strong>'+E(name)+'</strong><div class="flex">'+actions+'</div></header>';
const body=x=>'<div class="body"><div class="stack">'+x+'</div></div>';
const title=(a,b)=>'<h1>'+E(a)+'</h1><p class="lede">'+E(b)+'</p>';
const card=x=>'<section class="card">'+x+'</section>';
const kv=(k,v)=>'<div class="flex spread"><small>'+E(k)+'</small><span>'+E(v)+'</span></div>';
function notice(x){const n=$('#notice');n.textContent=x;n.hidden=false;clearTimeout(timer);timer=setTimeout(()=>n.hidden=true,3800)}
async function api(path,data){
 const res=await fetch(path,data?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)}:{cache:'no-store'});
 const result=await res.json();if(!res.ok)throw Error(result.error||'请求失败');return result;
}
async function load(){
 if(refreshing||busy)return;refreshing=true;const requestEpoch=epoch;
 try{const next=await api('/v1/state');if(requestEpoch!==epoch)return;const changed=JSON.stringify(next)!==JSON.stringify(S);S=next;if(changed){if(!$('#send textarea')?.matches(':focus')&&!$('#modal').open)render();else if(page==='研究计划'&&id&&$('.rail'))updateRail()}}
 catch(e){if(!S)$('#main').innerHTML='<div class="loading">无法连接研究服务。'+btn('重试','retry')+'</div>'}
 finally{refreshing=false}
}
async function act(payload,done=()=>{}){
 if(busy)return;busy=true;epoch++;
 const err=$('#modal .submit-error');if(err)err.textContent='';
 try{const row=await api('/v1/action',payload);S=await api('/v1/state');done(row);render()}
 catch(e){if(err&&$('#modal').open)err.textContent=e.message;else notice(e.message)}
 finally{busy=false}
}
function nav(p,key=''){page=p;id=key;render()}
function sidebar(){
 const navs=[['新聊天','聊天'],['研究计划','研究计划'],['项目','项目'],['智能体','智能体'],['工具','工具'],['设置','设置']];
 return '<div class="brand">'+mark+'TripSci</div><nav aria-label="工作区">'+navs.map(([t,p])=>'<div class="navrow"><button type="button" class="quiet" data-act="nav" data-key="'+p+'" '+(page===p?'aria-current="page"':'')+'>'+t+'</button></div>').join('')+'</nav>'+
 (all('thread').length?'<h4>最近聊天</h4>'+all('thread').slice(-8).reverse().map(t=>'<button type="button" class="quiet recent" data-act="chat" data-key="'+E(t.id)+'">'+E(t.title)+'</button>').join(''):'')+'<footer>本地工作区</footer>';
}
function transcript(items){
 return items.map(m=>'<div class="msg '+(m.role==='user'?'user':m.role==='event'?'event':'agent')+'">'+(m.role==='agent'?'<span class="avatar">'+mark+'</span>':'')+'<div class="content"><p>'+E(m.text)+'</p></div></div>').join('');
}
function composer(hint){
 const key=page+id;
 return '<div class="compose"><form id="send"><textarea name="text" aria-label="消息" maxlength="4000" placeholder="'+E(hint)+'" required>'+E(drafts[key])+'</textarea><div class="compose-footer"><small>TripSci</small><button class="primary send" aria-label="发送消息">↑</button></div></form></div>';
}
function chat(){
 const t=get('thread',id);
 if(!t)return '<div class="chat-home"><div class="chat-start">'+mark+'<h1>今天想聊什么？</h1>'+composer('自由讨论研究方向、进展或 Skills…')+'</div></div>';
 return head(t.title,btn('创建研究计划','newPlan'))+'<div class="dialogue chat-thread"><div class="conversation"><div class="inner">'+transcript(t.messages)+'</div></div>'+composer('继续聊天…')+'</div>';
}
function planRow(p){return '<button type="button" class="listrow" data-act="plan" data-key="'+E(p.id)+'"><span class="mono">'+E(p.id.slice(0,7))+'</span><strong>'+E(p.title)+'</strong><small class="projectCol">'+E(get('workspace',p.workspace)?.name||'未关联项目')+'</small>'+label(state(p))+'</button>'}
function metrics(r){return Object.entries(r||{}).map(([k,v])=>E(({macro_f1:'Macro F1',accuracy:'准确率',low_freq_auc:'低频 AUC',overall_auc:'整体 AUC'})[k]||k)+' '+E(v)).join(' · ')}
function experiment(e){return '<details><summary>第 '+e.round+' 轮 · '+(e.guardrail_passed===false?'护栏未通过':e.accepted?'保留为候选':'未采用')+'</summary><p>'+metrics(e.result)+'</p><p class="mono">Job '+E(e.id)+(e.k?'<br>k='+E(e.k)+' · '+(e.scale?'已缩放':'未缩放'):'')+'<br>数据 '+E(e.dataset)+'<br>代码 '+E(e.revision)+'<br>报告 '+E(e.report)+'</p></details>'}
function rail(p){
 const t=task(p), env=t?.environment||get('workspace',p.workspace), job=t&&get('job',t.pending_job);
 const ex=t?all('experiment').filter(e=>e.task===t.id):[];
 let out='<div class="flex spread"><h2>研究计划状态</h2>'+label(state(p))+'</div><section>'+kv('项目',env?.name||'未关联项目')+kv('执行模式',env?modeNames[env.mode]+(env.adapter==='iris'?' · 真实数据':' · 模拟'):'待确认')+kv('基线',t?.baseline||env?.baseline||'待确认')+(env?kv('数据版本',env.dataset)+kv(env.adapter==='iris'?'准确率下限':'整体 AUC 下限',env.floor)+kv('项目配置版本','v'+env.version):'')+'</section>';
 if(!t)return out+'<section><h3>准备实验</h3><p>讨论可以先开始。启动前确认项目和实验契约。</p>'+btn(env?'更换项目':'关联项目','attach')+(env?btn('确认实验计划','start',true):btn('新建项目','projectForPlan',true))+'</section>';
 out+='<section>'+kv('执行者',t.agent.name+' · v'+t.agent.version)+kv('预算',t.round+' / '+t.max_experiments)+'<details><summary>配置快照</summary><p>'+E(env.repo)+'<br>'+E(env.train)+' · '+E(env.evaluate)+'</p><p>'+E(t.agent.instructions)+'</p></details></section>';
 out+='<section><h3>正在运行</h3>'+(job?'<div class="runbox"><strong>第 '+t.round+' 轮 · '+(job.result?'结果已返回，待分析':job.k?'本机评测':'模拟训练')+'</strong><p class="mono">'+E(job.id)+'</p><p>'+ (job.k?'k='+E(job.k):'平滑强度 '+E(job.strength))+'</p></div>':'<small>当前没有训练 Job。</small>')+
 (t.status==='completed'?'': '<div class="flex">'+btn(t.status==='paused'?'恢复':'暂停后续调度',t.status==='paused'?'resume':'pause')+btn('给 Worker 反馈','feedback')+'</div>')+'</section>';
 out+='<section><h3>接下来</h3><p>'+(t.status==='completed'?'实验已结束。':'Worker 根据结果和反馈选择下一轮。')+'</p>'+all('inbox').filter(x=>x.task===t.id&&!['pause','resume'].includes(x.message)).map(x=>'<p>'+label(x.consumed?(x.disposition||'已读取'):'已送达')+' '+E(x.message)+'</p>').join('')+'</section>';
 return out+'<section><h3>已完成实验</h3>'+(ex.map(experiment).join('')||'<p class="muted">还没有结果。</p>')+(p.decision?'<p>结论：'+E(p.decision)+'</p>'+(p.holdout?'<p>'+(p.holdout.candidate?'保留测试集：'+metrics(p.holdout.candidate)+'<br>':'')+'测试基线：'+metrics(p.holdout.baseline)+'</p>':''):t.status==='completed'?'<div class="flex">'+(t.best.revision?btn('保留候选','decision',true,'保留候选'):'')+btn('不采用','decision',false,'不采用')+'</div>':'')+'</section>';
}
function updateRail(){const p=get('plan',id), old=$('.rail');if(!p||!old)return;const y=old.scrollTop, expanded=Array.from(old.querySelectorAll('details'),d=>d.open);old.innerHTML=rail(p);old.querySelectorAll('details').forEach((d,i)=>d.open=!!expanded[i]);old.scrollTop=y}
function plans(){
 const p=get('plan',id);
 if(!p)return head('研究计划',btn('＋ 新建计划','newPlan',true))+body(title('研究计划','先记录值得验证的问题，启动实验前再关联项目。')+(all('plan').map(planRow).join('')||card('<h3>还没有研究计划</h3>'+btn('创建第一项研究','newPlan',true))));
 return head(p.title,btn('返回研究计划','nav',false,'研究计划'))+'<div class="issue"><div class="dialogue"><div class="conversation"><div class="inner">'+title(p.title,p.direction)+transcript(p.messages)+'</div></div>'+composer('讨论实验计划或询问进展…')+'</div><aside class="rail" aria-label="研究计划状态">'+rail(p)+'</aside></div>';
}
function projects(){
 const p=current(), a=btn('＋ 新建项目','newProject',true)+btn('导入 Iris 任务','iris');
 if(!p)return head('项目')+body('<section class="guide"><div class="guide-copy"><span class="guide-tag">项目</span>'+title('从第一个研究项目开始','配置代码、训练与评测入口。实验开始后，结果会自动回到项目看板。')+a+'</div><div class="guide-options"><h2>从模板开始</h2>'+card('<h3>CTR 排序研究</h3><p>预填模拟仓库、数据和评测设置。</p>'+btn('使用示例','sample'))+card('<h3>Iris 鸢尾花分类</h3><p>使用公开真实数据，自动创建项目和研究草稿。</p>'+btn('导入 Iris 任务','iris',true))+'</div></section>');
 const ps=all('plan').filter(x=>x.workspace===p.id), keys=new Set(ps.map(x=>x.task));
 const ex=all('experiment').filter(x=>keys.has(x.task));
 return head('项目',a)+body(title(p.name,'项目看板 · 配置 v'+p.version)+pick('项目',all('workspace').map(w=>[w.id,w.name]),p.id)+
 '<div class="split">'+card('<h3>项目配置</h3>'+kv('模式',modeNames[p.mode])+kv('默认基线',p.baseline)+kv('数据',p.dataset)+kv('护栏',p.floor)+(p.adapter==='iris'?'<p>固定协议 · 本机真实评测</p>':btn('编辑配置','editProject')))+
 card('<h3>研究计划</h3>'+(ps.map(planRow).join('')||'<p>还没有研究计划。</p>')+btn('从此项目新建计划','newPlan',true))+'</div>'+
 card('<h3>近期实验</h3>'+(ex.slice(-10).reverse().map(experiment).join('')||'<p>等待第一条评测记录。</p>')));
}
function runtimeList(){return all('runtimes').map(r=>'<p>'+E(r.name)+' '+label(r.installed?(r.executable?'可执行':'已检测 · 未接执行'):'未安装')+'</p>').join('')}
function tools(){return head('工具',btn('＋ 添加工具','newTool',true)+btn('＋ 新建 Skill','newSkill'))+body(title('工具','把研究用的链接、命令参考和 Skills 放在一起。命令仅保存供查看。')+
 card('<h3>常用工作流</h3>'+btn('导入 Iris 任务','iris',true))+
 card('<h3>工具库</h3>'+(all('tool').map(t=>'<p><strong>'+E(t.name)+'</strong> '+(t.kind==='link'?'<a target="_blank" rel="noopener noreferrer" href="'+E(t.target)+'">打开链接</a>':'<code>'+E(t.target)+'</code>')+'</p>').join('')||'<p>还没有工具。可以添加文档链接或常用命令。</p>'))+
 card('<h3>Skills</h3>'+(all('skill').map(x=>'<details><summary>'+E(x.name)+'</summary><pre>'+E(x.markdown)+'</pre></details>').join('')||'<p>还没有自定义 Skill。创建后可绑定到智能体。</p>')))}
function agents(){const a=get('agent',id);return head('智能体',btn('＋ 新建智能体','newAgent',true))+body(a?title(a.name,'配置 v'+a.version)+card(kv('运行时',a.runtime)+kv('Skills',a.skills.map(k=>get('skill',k)?.name||k).join(' · '))+'<p>'+E(a.instructions)+'</p>'+(a.instructions_path?'<p class="mono">'+E(a.instructions_path)+'</p>':'')+btn('编辑配置','editAgent')+btn('返回列表','nav',false,'智能体')):title('智能体','配置研究角色、Markdown 指令和 Skills。')+card('<h3>本机运行时</h3>'+runtimeList())+all('agent').map(x=>card('<strong>'+E(x.name)+'</strong><p>配置 v'+x.version+'</p>'+btn('查看详情','agent',false,x.id))).join(''))}
function settings(){return head('设置')+body(title('设置','本地工作区的模拟运行配置。')+card('<form class="fields" data-form="settings">'+input('delay','每轮模拟训练秒数',S.settings.delay,'number')+input('slots','训练并发上限',S.settings.slots||2,'number')+'<button class="primary">保存设置</button></form>'))}
function render(){
 $('#side').innerHTML=sidebar();if(!S){$('#main').innerHTML='<div class="loading">正在连接研究服务…</div>';return}
 const old=$('.conversation'), scroll=old?.scrollTop, visible=old&&old.scrollHeight-old.clientHeight-scroll<40;
 $('#main').innerHTML=({聊天:chat,研究计划:plans,项目:projects,智能体:agents,工具:tools,设置:settings})[page]();
 const c=$('.conversation');if(c)c.scrollTop=visible||scroll==null?c.scrollHeight:scroll;
}
function modal(title,kind,fields,submit){
 const m=$('#modal');m.innerHTML='<h2>'+E(title)+'</h2><form class="fields" data-form="'+kind+'">'+fields+'<p class="submit-error" role="alert"></p><div class="flex">'+btn('取消','close')+'<button class="primary">'+E(submit)+'</button></div></form>';if(!m.open)m.showModal();
}
const sample={name:'CTR 排序研究',repo:'synthetic/ctr',baseline:'v1',dataset:'synthetic-v1',train:'train.py',evaluate:'evaluate.py',floor:.715,mode:'local'};
function projectForm(p={},attach=false){
 const fields=[['name','项目名称'],['repo','代码地址'],['baseline','默认基线'],['dataset','数据版本'],['train','训练入口'],['evaluate','评测入口']];
 modal(p.id?'编辑项目配置':'初始化研究项目','workspace','<p class="muted">三种配置均使用本机模拟训练。不会连接填写的仓库或远端。</p>'+
 fields.map(([k,t])=>input(k,t,p[k])).join('')+input('floor','整体 AUC 下限',p.floor??.715,'number')+
 '<label>执行模式'+pick('mode',Object.entries(modeNames),p.mode||'local')+'</label><div id="modeFields"></div>'+
 '<input type="hidden" name="id" value="'+E(p.id)+'"><input type="hidden" name="attach" value="'+(attach?'yes':'')+'">'+btn('检查配置','check'),'保存项目');
 modeFields(p.mode||'local',p);
}
function modeFields(mode,p={}){$('#modeFields').innerHTML=modes[mode].map(([k,t])=>input(k,t,p[k])).join('')}
function planForm(){
 const thread=page==='聊天'?get('thread',id):null;
 modal('新建研究计划','plan',input('title','标题',thread?.title)+area('direction','大致方向',thread?.messages.filter(m=>m.role==='user').map(m=>m.text).join('\n'))+
 '<label>所属项目'+pick('workspace',[['','暂不关联'],...all('workspace').map(w=>[w.id,w.name])],page==='项目'?current()?.id:'')+'</label><input type="hidden" name="source" value="'+E(thread?.id)+'">','创建并打开');
}
function agentForm(a={},runtime=a.runtime||'local-process'){modal(a.id?'编辑智能体':'配置智能体','agent','<p>运行时：'+E(all('runtimes').find(x=>x.id===runtime)?.name||runtime)+'</p><input type="hidden" name="runtime" value="'+E(runtime)+'">'+input('name','名称',a.name)+area('instructions','Markdown 指令',a.instructions||'比较实验结果，遵守护栏。')+'<label><input type="checkbox" name="wide" '+(a.skills?.includes('wide-search')?'checked':'')+'> 启用 wide-search</label>'+all('skill').map(x=>'<label><input type="checkbox" name="skill" value="'+E(x.id)+'" '+(a.skills?.includes(x.id)?'checked':'')+'> '+E(x.name)+'</label>').join('')+'<input type="hidden" name="id" value="'+E(a.id)+'">','保存配置')}
const payload=f=>Object.fromEntries(new FormData(f));
const close=()=>$('#modal').close();
document.addEventListener('click',e=>{
 const b=e.target.closest('[data-act]');if(!b)return;const {act:a,key:k}=b.dataset;
 if(a==='retry')return load();
 if(a==='nav')return nav(k);
 if(a==='chat')return nav('聊天',k);
 if(a==='plan')return nav('研究计划',k);
 if(a==='agent')return nav('智能体',k);
 if(a==='close')return close();
 if(a==='newProject'||a==='projectForPlan')return projectForm({},a==='projectForPlan');
 if(a==='sample')return projectForm(sample);
 if(a==='editProject')return projectForm(current());
 if(a==='newPlan')return planForm();
 if(a==='newAgent')return modal('选择本机运行时','chooseRuntime','<p>先选运行时，再填写角色指令与 Skills。</p>'+pick('runtime',all('runtimes').filter(x=>x.installed).map(x=>[x.id,x.name+(x.executable?'':' · 仅配置')])),'继续');
 if(a==='editAgent')return agentForm(get('agent',id));
 if(a==='iris')return act({op:'import_iris'},r=>{page='研究计划';id=r.id;project=r.workspace});
 if(a==='newTool')return modal('添加工具','tool',input('name','名称')+pick('kind',[['link','网页链接'],['command','命令参考']])+input('target','链接或命令'),'保存');
 if(a==='newSkill')return modal('新建 Skill','skill',input('name','名称')+area('markdown','Skill Markdown'),'保存');

 if(a==='attach')return modal('关联项目','attach',all('workspace').length?'<label>项目'+pick('workspace',all('workspace').map(x=>[x.id,x.name]),get('plan',id)?.workspace)+'</label>':'<p>还没有项目。</p>'+btn('新建项目','projectForPlan'),'关联');
 if(a==='start'){
   const env=get('workspace',get('plan',id)?.workspace);if(!env)return;
   return modal('确认并启动实验','start','<p>'+E(env.name)+' · '+E(modeNames[env.mode])+(env.adapter==='iris'?' · 真实数据</p>':' · 模拟</p>')+kv('数据',env.dataset)+kv(env.adapter==='iris'?'准确率下限':'整体 AUC 下限',env.floor)+(env.adapter==='iris'?kv('固定基线',env.baseline):input('baseline','对照基线',env.baseline))+input('budget','实验预算（1–10）',3,'number')+'<label>执行者'+pick('agent',all('agent').filter(x=>x.runtime==='local-process').map(x=>[x.id,x.name+' · v'+x.version]))+'</label>',env.adapter==='iris'?'启动本机评测':'启动模拟研究');
 }
 if(a==='feedback')return modal('给 Worker 反馈','feedback','<p>当前训练继续。可发送「保守」或「强度 0.55」来改变下一轮。</p>'+area('text','反馈'),'发送反馈');
 if(a==='check'){
   const f=$('#modal form');if(!f.reportValidity())return;
   const d=payload(f);act({...d,op:'check',floor:Number(d.floor)},r=>{const el=$('#modal .submit-error');if(el)el.textContent=r.message});return;
 }
 if(['pause','resume','decision'].includes(a))act({op:a,id,value:k});
});
document.addEventListener('change',e=>{
 if(e.target.name==='项目'){project=e.target.value;render()}
 if(e.target.name==='mode')modeFields(e.target.value);
});
document.addEventListener('input',e=>{if(e.target.matches('#send textarea'))drafts[page+id]=e.target.value});
document.addEventListener('focusout',e=>{if(e.target.matches('#send textarea'))setTimeout(()=>{if(!busy&&!$('#send textarea')?.matches(':focus')&&!$('#modal').open)render()},80)});
document.addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.isComposing&&e.target.matches('#send textarea')){e.preventDefault();e.target.form.requestSubmit()}});
document.addEventListener('submit',async e=>{
 const f=e.target;if(f.id!=='send'&&!f.dataset.form)return;e.preventDefault();if(busy)return;
 const d=payload(f), op=f.dataset.form;
 if(f.id==='send'){
   const text=d.text.trim(), key=page+id;if(!text)return;
   return act({op:'message',text,[page==='聊天'?'thread':'plan']:id},r=>{delete drafts[key];id=r.id});
 }
 if(op==='workspace'){
   const attach=d.attach==='yes', plan=id;delete d.attach;
   return act({...d,op,floor:Number(d.floor)},r=>{close();project=r.id;if(attach)setTimeout(()=>act({op:'attach',id:plan,workspace:r.id}),0);else{page='项目';id=''}});
 }
 if(op==='plan')return act({...d,op},r=>{close();page='研究计划';id=r.id});
 if(op==='chooseRuntime')return agentForm({},d.runtime);
 if(op==='tool'||op==='skill')return act({...d,op},close);
 if(op==='agent')return act({...d,op,skills:['adaptive-ctr',...(d.wide?['wide-search']:[]),...new FormData(f).getAll('skill')]},r=>{close();id=r.id});
 if(op==='settings')return act({op,delay:Number(d.delay),slots:Number(d.slots)},()=>notice('已保存设置'));
 if(op==='attach'&&!d.workspace)return notice('请先新建项目');
 if(op==='start')d.budget=Number(d.budget);
 act({...d,op,id},close);
});
render();load();setInterval(load,850);
