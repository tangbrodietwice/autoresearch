'use strict';
const $=q=>document.querySelector(q), E=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const modeNames={local:'本机执行',hybrid:'本机 Agent · 远端训练',remote:'远端执行'};
const statusNames={ready:'进行中',waiting:'进行中',paused:'已暂停',failed:'执行失败',completed:'待评审'};
const modes={local:[],hybrid:[['training_host','远端训练连接'],['delivery','代码交付方式']],remote:[['agent_host','远端 Agent 连接'],['remote_dir','远端工作目录']]};
let S=null,page='项目',id='',project='',busy=false,timer,refreshing=false,epoch=0;
const drafts={};
let needsRender=false, toolTab='发现', agentTab='概览', returnPlan='';
const resultFilters={}, openPlanStatus=new Set();
const chartChoices={};
const metricNames={balanced_accuracy:'Balanced Accuracy',macro_f1:'Macro F1',accuracy:'准确率',low_freq_auc:'低频 AUC',overall_auc:'整体 AUC'};
const runtimeName=r=>all('runtimes').find(x=>x.id===r)?.name||r;
const runtimeStatus=r=>r?.installed?(r.executable?'可运行':'已检测 · 仅配置'):'未安装';
const navHeading=(crumb,actions='')=>'<header class="head"><div class="flex breadcrumb">'+crumb+'</div><div class="flex">'+actions+'</div></header>';
const search=(placeholder)=>'<input class="control search" data-search placeholder="'+E(placeholder)+'" aria-label="'+E(placeholder)+'" type="search">';
const tabs=(names,active,act)=>'<div class="view-tabs" aria-label="视图">'+names.map(n=>'<button type="button" data-act="'+act+'" data-key="'+E(n)+'" aria-pressed="'+(n===active)+'">'+E(n)+'</button>').join('')+'</div>';
const empty=(heading,copy,action='')=>'<div class="empty-state"><strong>'+E(heading)+'</strong><p>'+E(copy)+'</p>'+action+'</div>';
const all=k=>S?.[k]||[], get=(k,i)=>all(k).find(x=>x.id===i), task=p=>get('task',p?.task);
const current=()=>get('workspace',project)||all('workspace')[0];
const planRuns=p=>all('experiment').filter(e=>e.task===p.task);
const state=p=>p.decision?'已完成':statusNames[task(p)?.status]||'计划中';
const badgeStyle={'已完成':['done','✓'],'进行中':['active','◉'],'待评审':['review','◇'],'计划中':['neutral','○'],'已暂停':['review','Ⅱ'],'执行失败':['failed','!'],'通过护栏 · 有改进':['done','↑'],'通过护栏 · 未改进':['neutral','—'],'未通过护栏':['failed','!']};
const label=text=>{const [tone,mark]=badgeStyle[text]||[];return '<span class="pill'+(tone?' tone-'+tone:'')+'">'+(mark?'<span aria-hidden="true">'+mark+'</span>':'')+E(text)+'</span>'};
const mark='<img class="trip-mark" src="/TripSci-icon.png" width="32" height="32" alt="">';
const btn=(name,act,primary=false,key='')=>'<button type="button" '+(primary?'class="primary" ':'')+'data-act="'+E(act)+'" data-key="'+E(key)+'">'+E(name)+'</button>';
const pick=(name,options,selected='')=>'<select class="control" name="'+E(name)+'" aria-label="'+E(name)+'">'+options.map(([v,t])=>'<option value="'+E(v)+'" '+(selected===v?'selected':'')+'>'+E(t)+'</option>').join('')+'</select>';
const input=(name,title,value='',type='text')=>'<label>'+E(title)+'<input name="'+name+'" type="'+type+'" required value="'+E(value)+'" '+(type==='number'?'step="any"':'')+'></label>';
const area=(name,title,value='')=>'<label>'+E(title)+'<textarea name="'+name+'" required>'+E(value)+'</textarea></label>';
const head=(name,actions='')=>'<header class="head"><h1>'+E(name)+'</h1><div class="flex">'+actions+'</div></header>';
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
 try{const next=await api('/v1/state');if(requestEpoch!==epoch)return;const changed=JSON.stringify(next)!==JSON.stringify(S);S=next;if(changed||needsRender){needsRender=true;if(!$('#send textarea')?.matches(':focus')&&!$('#modal').open&&!document.activeElement?.matches('[data-search], .inline-form textarea, .inline-form input, .inline-form select')&&!$('.switcher[open]')&&!$('[data-retain]'))render();else if(page==='研究计划'&&id&&$('.rail'))updateRail()}}
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
function nav(p,key=''){
 $('#notice').hidden=true;
 id=key;
 if(p==='智能体'){agentTab='概览';returnPlan=''}
 page=p;render()
}
function switcher(title, rows, act, selected, footer, a11y){
 return '<details class="switcher"><summary aria-label="'+E(a11y)+'" title="'+E(title)+'"><span>'+E(title)+'</span><span aria-hidden="true">⌄</span></summary><div class="switch-menu" data-filter-scope>'+search('搜索'+a11y.replace('切换',''))+'<div class="switch-rows">'+rows.map(([key,name,meta])=>'<button type="button" data-filter-item data-act="'+act+'" data-key="'+E(key)+'" '+(key===selected?'aria-current="true"':'')+'><span><strong>'+E(name)+'</strong><small>'+E(meta)+'</small></span>'+(key===selected?'✓':'')+'</button>').join('')+'<p class="filter-empty" hidden>没有匹配结果。</p></div>'+(footer?'<div class="switch-footer">'+footer+'</div>':'')+'</div></details>';
}
function sidebar(){
 const navs=[['新聊天','聊天'],['研究计划','研究计划'],['项目','项目'],['智能体','智能体'],['工具','工具'],['设置','设置']];
 return '<div class="brand">'+mark+'TripSci</div><nav aria-label="工作区">'+navs.map(([t,p])=>'<div class="navrow"><button type="button" class="quiet" data-act="nav" data-key="'+p+'" '+(page===p?'aria-current="page"':'')+'>'+t+'</button></div>').join('')+'</nav>'+
 (all('thread').length?'<h4>最近聊天</h4>'+all('thread').slice(-8).reverse().map(t=>'<button type="button" class="quiet recent" data-act="chat" data-key="'+E(t.id)+'">'+E(t.title)+'</button>').join(''):'');
}
function transcript(items){
 return items.map(m=>'<div class="msg '+(m.role==='user'?'user':m.role==='event'?'event':'agent')+'">'+(m.role==='agent'?'<span class="avatar">'+mark+'</span>':'')+'<div class="content"><p>'+E(m.text)+'</p></div></div>').join('');
}
function composer(hint,context=''){
 const key=page+id;
 return '<div class="compose"><form id="send"><textarea name="text" aria-label="消息" maxlength="4000" placeholder="'+E(hint)+'" required>'+E(drafts[key])+'</textarea><div class="compose-footer"><small>'+E(context)+'</small><button class="primary send" aria-label="发送消息">↑</button></div></form></div>';
}
function chat(){
 const t=get('thread',id);
 if(!t)return '<div class="chat-home"><div class="chat-start">'+mark+'<h1>今天想聊什么？</h1>'+composer('自由讨论研究方向、进展或 Skills…')+'</div></div>';
 return head(t.title,btn('创建研究计划','newPlan'))+'<div class="dialogue chat-thread"><div class="conversation"><div class="inner">'+transcript(t.messages)+'</div></div>'+composer('继续聊天…')+'</div>';
}
function planRow(p){return '<button type="button" class="listrow" data-act="plan" data-key="'+E(p.id)+'"><span class="mono">'+E(p.id.slice(0,7))+'</span><strong>'+E(p.title)+'</strong><small class="projectCol">'+E(get('workspace',p.workspace)?.name||'未关联项目')+'</small>'+label(state(p))+'</button>'}
function metrics(r){return Object.entries(r||{}).map(([k,v])=>E(metricNames[k]||k)+' '+E(v)).join(' · ')}
const configLabel=e=>e.adapter==='name-llm'&&e.config?'词频 '+e.config.word+' · 字符 '+e.config.char+' · 文体 '+e.config.style+' · '+e.config.grams+'-gram':e.config?(e.config.family==='centroid'?'最近质心':'高斯朴素贝叶斯')+' · 先验权重 '+Number(e.config.prior).toFixed(2)+(e.config.shrinkage!=null?' · 方差收缩 '+Number(e.config.shrinkage).toFixed(2):''):e.k?'k = '+e.k+' · '+(e.scale?'按特征范围缩放':'原始特征'):'平滑强度 '+e.strength;
const shortScore=(e,k)=>Number.isFinite(e.result?.[k])?(metricNames[k]||k)+' '+e.result[k].toFixed(4):'暂无指标';
const delta=e=>Number.isFinite(e.baseline_delta)?' · 较基线 '+(e.baseline_delta>=0?'+':'')+e.baseline_delta.toFixed(4):'';
const phases={scheduled:'等待调度',queued:'等待训练名额',preparing:'编写实验代码',submitting:'提交训练任务',waiting:'等待训练结果',analyzing:'分析实验结果',cooldown:'等待下一轮窗口',finished:'实验已结束'};
function workerStage(t,job){
 if(t.status==='paused')return '暂停后续调度';
 if(t.status==='failed')return '执行失败';
 if(t.status==='completed')return phases.finished;
 if(job)return job.result?'分析实验结果':['beans','name-llm'].includes(job.adapter)?'本机训练或等待结果':phases.waiting;
 return phases[t.phase]||'等待调度';
}
function experiment(e,key){
 return '<article class="rail-result"><strong>第 '+e.round+' 轮 · '+E(outcome(e))+'</strong><p>'+E(configLabel(e))+'</p><p>'+E(shortScore(e,key)+delta(e))+'</p><details><summary>完整指标与复现信息</summary><p>'+metrics(e.result)+'</p><p class="mono">提交 '+E(e.revision)+'<br>报告 '+E(e.report)+'</p></details></article>';
}
function rail(p){
 const t=task(p), env=t?.environment||get('workspace',p.workspace), job=t&&get('job',t.pending_job), ex=planRuns(p);
 const projectLink=env?btn(env.name,'project',false,p.workspace):'未关联项目';
 let out='<div class="flex spread"><h2>状态</h2>'+label(state(p))+'</div><section>'+kv('基线',t?.baseline||env?.baseline||'待确认')+'<div class="flex spread"><small>项目</small>'+projectLink+'</div>'+(env?kv('数据',env.dataset):'')+'</section>';
 if(!t)return out+'<section><h3>下一步</h3><p>先在对话里明确假设与对照，再确认实验预算和执行者。</p><div class="flex">'+(env?btn('确认实验计划','start',true)+btn('更换项目','attach'):(all('workspace').length?btn('关联项目','attach',true):btn('新建项目','projectForPlan',true)))+'</div></section>';
 const stage=workerStage(t,job);
 out+='<section><h3>Worker</h3>'+kv('执行者',t.agent.name+' · v'+t.agent.version)+(t.status==='failed'?'':kv('当前阶段',stage))+kv('已完成',t.continuous?ex.length+' 轮 · 持续迭代':ex.length+' / '+t.max_experiments+' 轮')+
 '<details><summary>执行配置与阶段记录</summary><p>'+E(env.train)+' · '+E(env.evaluate)+'</p><p>'+E(modeNames[env.mode])+(env.adapter!=='mock'?' · 真实评测':' · 模拟')+'</p><ul>'+all('progress').filter(x=>x.task===t.id&&x.phase&&/preparing code|Submitting|Submitted|analyzing results/.test(x.event)).slice(-8).reverse().map(x=>'<li>'+E(phases[x.phase]||x.phase)+'</li>').join('')+'</ul></details></section>';
 if(t.status==='failed'){
   out+='<section><h3>恢复执行</h3><p>'+E(t.failure)+'</p>'+btn('重试执行','retryPlan',true)+'</section>';
 }else if(t.status!=='completed'){
   out+='<section><h3>进行中的实验</h3>'+(job?'<div class="runbox"><strong>第 '+t.round+' 轮 · '+E(job.result?'结果已返回':job.k||['beans','name-llm'].includes(job.adapter)?'本机评测':'模拟训练')+'</strong><p>'+E(configLabel(job))+'</p></div>':'<p class="muted">'+E(stage)+'，尚无已提交的实验。</p>')+
   '<div class="flex">'+btn(t.status==='paused'?'恢复调度':'暂停后续调度',t.status==='paused'?'resume':'pause')+btn('给 Worker 反馈','feedback')+(t.continuous?btn('结束并生成报告','finishLoop'):'')+'</div></section>'+
   '<section><h3>待安排</h3><p>'+(t.continuous?'每轮结束后等待 '+t.interval+' 秒，再自动提出下一轮。':'还有 '+Math.max(0,t.max_experiments-t.round)+' 轮未提交。')+'</p>'+all('inbox').filter(x=>x.task===t.id&&!['pause','resume'].includes(x.message)).map(x=>'<p>'+label(x.consumed?(x.disposition||'已读取'):'已送达')+' '+E(x.message)+'</p>').join('')+'</section>';
 }
 return out+'<section><h3>已完成实验</h3>'+(ex.slice().sort((a,b)=>b.round-a.round).map(e=>experiment(e,t.constraints.primary_metric)).join('')||'<p class="muted">首轮评测完成后显示摘要。</p>')+'</section>';
}
function reportText(r){
 return ['# '+r.title,'','## 实验设计',r.goal,'','基线：'+r.baseline+' · 数据：'+r.dataset,'Worker：'+r.agent.name+' v'+r.agent.version,'结论：'+(r.decision||(r.candidate?'有待评审候选':'没有达到采纳条件的候选')),'','## 实验结果',...r.runs.map(e=>'- 第 '+e.round+' 轮：'+configLabel(e)+'；'+shortScore(e,r.primary)+delta(e)+'；'+outcome(e)+'；'+e.revision),...(r.holdout?['','## 保留测试集','基线：'+JSON.stringify(r.holdout.baseline),...(r.holdout.candidate?['候选：'+JSON.stringify(r.holdout.candidate)]:[])]:[])].join('\n');
}
function reportCard(p){
 const r=p.report;if(!r)return '';
 const bad=r.runs.filter(e=>e.guardrail_passed===false).length;
 return '<article class="research-report" aria-label="实验报告"><div class="flex spread"><h2>实验报告</h2></div>'+
 '<p>'+E(r.goal)+'</p><p>完成 '+r.runs.length+' / '+r.budget+' 轮 · '+bad+' 轮未通过护栏</p><p>基线：'+E(r.baseline)+(Number.isFinite(r.baseline_value)?' · '+E(metricNames[r.primary]+' '+r.baseline_value.toFixed(4)):'')+'</p>'+
 '<p><strong>'+E(r.candidate?'最佳候选：第 '+r.candidate.round+' 轮 · '+shortScore(r.candidate,r.primary)+delta(r.candidate):'没有超过基线且通过护栏的候选。')+'</strong></p>'+
 '<details><summary>逐轮结果与复现信息</summary>'+r.runs.map(e=>experiment(e,r.primary)).join('')+'</details>'+
 (r.holdout?'<p>保留测试集 · 基线：'+metrics(r.holdout.baseline)+(r.holdout.candidate?'<br>候选：'+metrics(r.holdout.candidate):'')+'</p>':'')+
 (p.decision?'<p>结论：'+E(p.decision)+'</p>':'<div class="flex report-actions">'+(r.candidate?btn('保留候选','decision',true,'保留候选'):'')+btn('不采用','decision',false,'不采用')+'</div>')+
 '<div class="flex report-actions">'+btn('下载报告','downloadReport')+btn('配置 Worker','reportWorker',false,r.agent.id)+btn('从报告创建 Skill','reportSkill',false,r.agent.id)+'</div></article>';
}
function updateRail(){const p=get('plan',id), old=$('.rail');if(!p||!old)return;const y=old.scrollTop, expanded=Array.from(old.querySelectorAll('details'),d=>d.open);old.innerHTML=rail(p);old.querySelectorAll('details').forEach((d,i)=>d.open=!!expanded[i]);old.scrollTop=y}
const planGroups=['计划中','进行中','待评审','已暂停','执行失败','已完成'];
function plans(){
 const p=get('plan',id), list=all('plan').slice().reverse(), create=btn('＋ 新建计划','newPlan',true);
 if(!p){
   if(!list.length)return head('研究计划')+body(empty('还没有研究计划','建议先创建项目并设置评测，再从项目看板制定研究计划。',all('workspace').length?create:btn('去创建项目','nav',true,'项目')));
   return head('研究计划',create)+body('<div data-filter-scope><div class="library-bar">'+search('搜索计划、项目或状态')+'</div>'+
   planGroups.filter(k=>list.some(p=>state(p)===k)).map(k=>{const rows=list.filter(p=>state(p)===k);
     return '<details class="plan-group" data-detail="'+E(k)+'" open><summary>'+E(k)+' '+label(rows.length)+'</summary>'+rows.map(p=>'<div data-filter-item>'+planRow(p)+'</div>').join('')+'</details>';
   }).join('')+'<p class="filter-empty" hidden>没有匹配结果。</p></div>');
 }
 const chooser=switcher('切换计划',list.map(x=>[x.id,x.title,(get('workspace',x.workspace)?.name||'未关联项目')+' · '+state(x)]),'plan',id,'','切换研究计划');
 const showing=openPlanStatus.has(p.id);
 const header=navHeading(btn('研究计划','allPlans')+'<span aria-hidden="true">/</span><h1>'+E(p.title)+'</h1>',
 chooser+'<button type="button" class="mobile-status" data-act="togglePlanStatus" aria-controls="plan-status" aria-expanded="'+showing+'">实验状态</button>');
 const start='<div class="chat-welcome">'+mark+'<h2>讨论这项研究</h2><p>可以从一个要验证的假设开始，或先聊对照基线。</p><div class="flex">'+btn('梳理可验证的假设','planPrompt',false,'先梳理这项研究要验证的假设和成功标准。')+btn('讨论对照基线','planPrompt',false,'我们应该用什么作为对照基线？')+'</div></div>';
 return header+'<div class="issue research-chat'+(showing?' show-status':'')+'"><div class="dialogue"><div class="conversation" aria-label="研究对话"><div class="inner">'+
 '<details class="chat-context"><summary>研究方向</summary><p>'+E(p.direction)+'</p></details>'+
 (p.messages.length?transcript(p.messages):start)+reportCard(p)+'</div></div>'+composer('和 TripSci 讨论这项研究…','Enter 发送 · Shift + Enter 换行')+
 '</div><aside id="plan-status" class="rail" aria-label="研究计划状态">'+rail(p)+'</aside></div>';
}
function outcome(e){return e.guardrail_passed===false?'未通过护栏':e.accepted?'通过护栏 · 有改进':'通过护栏 · 未改进'}
function experimentSummary(e,p){
 const t=task(p), key=t?.constraints?.primary_metric, value=e.result?.[key];
 const idea=configLabel(e);
 return '<article class="result-row"><div class="flex spread"><strong>'+E(p.title)+' · 第 '+E(e.round)+' 轮</strong>'+label(outcome(e))+'</div><p>'+E(idea)+(value==null?'':' · <b>'+E(metricNames[key])+' '+Number(value).toFixed(4)+'</b>'+E(delta(e)))+'</p><details data-detail="'+E(e.id)+'"><summary>查看指标与复现信息</summary><p>'+metrics(e.result)+'</p><p class="mono">代码 '+E(e.revision)+'<br>报告 '+E(e.report)+'</p></details>'+btn('打开研究计划','plan',false,p.id)+'</article>';
}
const projectMetrics=p=>p.adapter==='name-llm'?['balanced_accuracy','accuracy']:p.adapter!=='mock'?['macro_f1','accuracy']:['low_freq_auc','overall_auc'];
function trend(p){
 const opts=projectMetrics(p), metric=chartChoices[p.id]||opts[0];
 const history=all('integration').filter(r=>r.workspace===p.id).sort((a,b)=>a.ordinal-b.ordinal);
 const protocol=history.filter(r=>r.dataset===p.dataset&&r.evaluate===p.evaluate&&r.adapter===p.adapter);
 const points=protocol.filter(r=>Number.isFinite(r.metrics[metric]));
 const scores=points.map(r=>r.metrics[metric]);
 const maxRound=Math.max(4,points.length);
 const min=scores.length?Math.max(0,Math.floor((Math.min(...scores)-.005)*100)/100):0;
 const max=scores.length?Math.min(1,Math.ceil((Math.max(...scores)+.005)*100)/100):1;
 const x=i=>62+i*650/(maxRound-1), y=v=>169-(v-min)/(max-min)*145;
 const grid=Array.from({length:5},(_,i)=>{const value=min+(max-min)*i/4, yy=y(value);return '<line x1="62" x2="712" y1="'+yy+'" y2="'+yy+'"/><text x="52" y="'+(yy+4)+'" text-anchor="end">'+value.toFixed(scores.length?3:2)+'</text>'}).join('');
 const ticks=Array.from({length:maxRound},(_,i)=>maxRound>9&&i!==maxRound-1&&i%Math.ceil(maxRound/8)!==0?'':'<text x="'+x(i)+'" y="194" text-anchor="middle">'+(points[i]?'v'+points[i].ordinal:scores.length?'':'v'+(i+1))+'</text>').join('');
 const line=scores.length?'<polyline fill="none" stroke="#ab563c" stroke-width="2.5" points="'+scores.map((v,i)=>x(i)+','+y(v)).join(' ')+'"/>'+points.map((r,i)=>'<circle cx="'+x(i)+'" cy="'+y(r.metrics[metric])+'" r="4" fill="#ab563c"><title>v'+r.ordinal+' · '+E(r.revision.slice(0,8))+' · '+r.metrics[metric].toFixed(4)+'</title></circle>').join(''):'';
 return card('<div class="flex spread"><div><h3>项目指标趋势</h3><small>仅展示成果合并后的项目评测 · '+E(p.dataset)+'</small></div><div class="flex">'+pick('趋势指标',opts.map(k=>[k,metricNames[k]]),metric)+btn('记录合并评测','recordIntegration')+'</div></div><div class="chart"><svg viewBox="0 0 738 206" role="img" aria-label="'+E('项目 '+metricNames[metric]+' 趋势'+(!scores.length?'，暂无合并评测':''))+'">'+grid+ticks+line+'</svg>'+(!scores.length?'<span class="chart-empty">暂无合并后的评测</span>':'')+'</div>'+
 (history.length!==protocol.length?'<p class="muted">较早的评测协议与当前配置不同，记录保留在下方，不参与本图比较。</p>':'')+
 (history.length?'<details><summary>合并评测记录（'+history.length+'）</summary>'+history.slice().reverse().map(r=>'<article class="result-row"><strong>v'+r.ordinal+' · '+E(r.revision.slice(0,8))+'</strong><p>'+E(r.summary)+'</p><p>'+metrics(r.metrics)+'</p><small>成果来源：'+E(r.plans.map(q=>q.title).join('、'))+' · '+E(r.dataset)+'</small></article>').join('')+'</details>':'<small>研究计划的候选成绩会显示在近期实验中，不会改变项目曲线。</small>'));
}
function integrationForm(){
 const p=current(), sources=all('plan').filter(q=>q.workspace===p.id&&q.decision==='保留候选');
 if(!sources.length)return modal('记录合并评测','noIntegration','<p>此项目还没有已保留的候选。先在研究计划中完成评审，再合并成果并用项目的固定评测配置重新评估。</p>','知道了');
 return modal('记录合并评测','integration','<p>录入已经合并和重新评测的项目版本。此操作记录结果，不执行 Git 合并或训练。</p>'+
 '<fieldset><legend>纳入此版本的研究计划</legend>'+sources.map(q=>'<label><input name="sourcePlan" type="checkbox" value="'+E(q.id)+'"> '+E(q.title)+'</label>').join('')+'</fieldset>'+
 input('revision','合并后的 Git 提交哈希')+projectMetrics(p).map(k=>input(k,metricNames[k],undefined,'number')).join('')+
 area('summary','变更与评测摘要'),'保存评测');
}
function projects(){
 const p=get('workspace',id), actions=btn('＋ 新建项目','newProject',true);
 if(!all('workspace').length)return head('项目')+body('<section class="guide"><div class="guide-copy">'+title('从第一个研究项目开始','配置代码、训练与评测入口。实验开始后，结果会自动回到项目看板。')+actions+'</div><div class="guide-options"><h2>从模板开始</h2>'+card('<h3>CTR 排序研究</h3><p>预填模拟仓库、数据和评测设置。</p>'+btn('使用示例','sample'))+card('<h3>Iris 鸢尾花分类</h3><p>使用公开真实数据，自动创建项目和研究草稿。</p>'+btn('导入 Iris 任务','iris',true))+'</div></section>');
 if(!p)return head('项目',actions)+body('<div data-filter-scope><div class="library-bar flex spread">'+search('搜索项目')+btn('导入 Iris 任务','iris')+'</div>'+all('workspace').map(w=>{
   const plans=all('plan').filter(q=>q.workspace===w.id), ids=new Set(plans.map(q=>q.task));
   const runs=all('experiment').filter(e=>ids.has(e.task));
   return '<button type="button" class="study-row project-row" data-filter-item data-act="project" data-key="'+E(w.id)+'"><span><strong>'+E(w.name)+'</strong><small>'+E(modeNames[w.mode])+' · '+E(w.dataset)+'</small></span><small>'+plans.length+' 项研究 · '+runs.length+' 轮实验</small><span aria-hidden="true">›</span></button>';
 }).join('')+'<p class="filter-empty" hidden>没有匹配项目。</p></div>');
 const ps=all('plan').filter(x=>x.workspace===p.id), byTask=new Map(ps.filter(x=>x.task).map(x=>[x.task,x]));
 const ex=all('experiment').filter(x=>byTask.has(x.task)).sort((a,b)=>(b.ready_at||0)-(a.ready_at||0));
 const filter=resultFilters[p.id]||'全部', shown=ex.filter(e=>filter==='全部'||(filter==='有改进'?e.accepted:filter==='未通过护栏'?e.guardrail_passed===false:e.guardrail_passed!==false&&!e.accepted));
 return navHeading(btn('项目列表','nav',false,'项目')+'<span aria-hidden="true">/</span>'+switcher(p.name,all('workspace').map(w=>[w.id,w.name,modeNames[w.mode]]),'project',p.id,'','切换项目'),btn('＋ 新建研究计划','newPlan',true))+body('<p class="lede">项目看板 · '+(p.adapter!=='mock'?'真实评测':'模拟评测')+'</p>'+
 '<div class="dash-stats">'+card('<small>研究计划</small><strong>'+ps.length+'</strong>')+card('<small>有改进的实验</small><strong>'+ex.filter(e=>e.accepted).length+'</strong>')+card('<small>未通过护栏</small><strong>'+ex.filter(e=>e.guardrail_passed===false).length+'</strong>')+'</div>'+
 card('<h3>研究概览</h3>'+(ps.map(q=>{const runs=planRuns(q);return '<button type="button" class="study-row" data-act="plan" data-key="'+E(q.id)+'"><span><strong>'+E(q.title)+'</strong><small>'+E(q.direction)+'</small></span><small>'+runs.length+' 轮 · '+runs.filter(r=>r.accepted).length+' 轮有改进</small>'+label(state(q))+'</button>'}).join('')||'<p class="muted">此项目还没有研究计划。可以从右上角创建。</p>'))+
 trend(p)+card('<h3>实验结果 <small>（'+ex.length+'）</small></h3>'+(ex.length?tabs(['全部','有改进','未改进','未通过护栏'],filter,'resultFilter')+(shown.map(e=>experimentSummary(e,byTask.get(e.task))).join('')||'<p class="muted">当前筛选没有结果。</p>'):'<p class="muted">首轮评测完成后，这里会显示方案、指标和结论。</p>'))+
 card('<details><summary>项目配置 · v'+E(p.version)+'</summary>'+kv('模式',modeNames[p.mode])+kv('默认基线',p.baseline)+kv('数据',p.dataset)+kv('训练入口',p.train)+kv('评测入口',p.evaluate)+(p.adapter!=='mock'?'<p>固定协议 · 本机真实评测</p>':btn('编辑配置','editProject'))+'</details>'));
}
const ntlTool={id:'builtin-ntl',name:'Name That LLM · Kaggle',description:'导入官方训练数据后，按提示分组验证文本来源分类。',kind:'builtin'};
const beansTool={id:'builtin-beans',name:'Dry Bean 并行研究',description:'七分类真实评测，支持多计划并行和持续迭代。',kind:'builtin'};
const irisTool={id:'builtin-iris',name:'Iris 实验启动器',description:'导入公开分类数据，生成预填配置和研究草稿。',kind:'builtin'};
function library(){return [irisTool,beansTool,ntlTool,...all('tool').map(t=>({...t,description:t.kind==='link'?'打开研究文档或外部服务。':'保存常用命令供查看。'})),...all('skill').map(x=>({...x,kind:'skill',description:x.markdown.trim().split(/\r?\n/).find(line=>line.trim()&&!line.startsWith('#'))?.slice(0,110)||'可分配给智能体的 Markdown 指南。'}))]}
const kinds={builtin:'内置工作流',link:'网页链接',command:'命令参考',skill:'Skill'};
function toolCard(t){return '<button class="tool-tile" type="button" data-filter-item data-act="toolDetail" data-key="'+E(t.id)+'"><span class="tool-icon" aria-hidden="true">'+({builtin:'✦',link:'↗',command:'›_',skill:'◇'})[t.kind]+'</span><strong>'+E(t.name)+'</strong><small>'+E(t.description)+'</small>'+label(kinds[t.kind])+'</button>'}
function tools(){
 const items=library(), t=items.find(x=>x.id===id);
 if(t)return navHeading(btn('工具','nav',false,'工具')+'<span aria-hidden="true">/</span><h1>'+E(t.name)+'</h1>')+body('<div class="detail-intro">'+label(kinds[t.kind])+'<p class="lede">'+E(t.description)+'</p></div>'+
 card(t.id===ntlTool.id?'<h3>导入比赛项目</h3><p>先从 Kaggle 下载训练数据，再用本地导入脚本准备。</p>'+btn('打开已导入的比赛项目','nameLLM',true):t.kind==='builtin'?'<h3>包含的能力</h3><p>下载数据已打包，导入后可直接启动真实本机评测。</p>'+(t.id===beansTool.id?btn('导入 Dry Bean 项目','beans',true):btn('导入 Iris 任务','iris',true)):t.kind==='skill'?'<h3>SKILL.md</h3><pre>'+E(t.markdown)+'</pre>'+btn('管理智能体分配','nav',false,'智能体'):t.kind==='link'?'<h3>链接</h3><a target="_blank" rel="noopener noreferrer" href="'+E(t.target)+'">'+E(t.target)+'</a>':'<h3>命令参考</h3><pre>'+E(t.target)+'</pre><small>仅供查看，TripSci 不会执行。</small>'));
 const skills=toolTab==='Skills', discover=toolTab==='发现';
 const shown=discover?[irisTool,beansTool,ntlTool]:items.filter(x=>skills?x.kind==='skill':['link','command'].includes(x.kind));
 const add=discover?'':skills?btn('＋ 新建 Skill','newSkill',true):btn('＋ 添加工具','newTool',true);
 return head('工具',add)+body(tabs(['发现','工作区','Skills'],toolTab,'toolTab')+
 '<div data-filter-scope>'+(shown.length?'<div class="library-bar">'+search(skills?'搜索 Skills':discover?'搜索工作流':'搜索链接或命令')+'</div><div class="tile-grid">'+shown.map(toolCard).join('')+'</div>':skills?
 empty('还没有自定义 Skill','创建后可以分配给一个或多个智能体。'):
 empty('还没有保存链接或命令','把常用研究文档和命令参考集中到这里。'))+
 '<p class="filter-empty" hidden>没有匹配结果。</p></div>');
}
function agentSkills(a){
 const names={'adaptive-ctr':'自适应实验策略','wide-search':'扩大搜索范围'};
 const chosen=a.skills.map(k=>[k,get('skill',k)?.name||names[k]||k]);
 const candidates=[['wide-search',names['wide-search']],...all('skill').map(x=>[x.id,x.name])].filter(([k])=>!a.skills.includes(k));
 return card('<div class="flex spread"><h3>已分配 Skills</h3>'+btn('＋ 创建并分配 Skill','agentSkill',false,a.id)+'</div><p class="muted">自定义 Skill 会随新计划保存。目前内置 Worker 只执行内置策略。</p>'+(chosen.length?chosen.map(([k,n])=>'<div class="catalog-row"><strong>'+E(n)+'</strong>'+ (k==='adaptive-ctr'?label('内置默认'):btn('移除','removeSkill',false,k))+'</div>').join(''):'<p class="muted">还没有分配 Skill。</p>')+
 (candidates.length?'<form data-form="assignSkill" class="flex inline-form">'+pick('skill',candidates)+'<button class="primary">分配已有 Skill</button></form>':'<p class="muted">所有可用 Skills 已分配。</p>'));
}
function agents(){
 const a=get('agent',id), newAgent=btn('＋ 新建智能体','newAgent',true), list=all('agent');
 if(!a)return head('智能体',newAgent)+body(tabs(['已配置','本机运行时'],agentTab==='本机运行时'?'本机运行时':'已配置','agentTab')+
 (agentTab==='本机运行时'?card('<div class="flex spread"><p class="muted">检测这台电脑安装的执行工具。</p>'+btn('重新检测','scanRuntimes')+'</div>'+all('runtimes').map(r=>'<div class="catalog-row"><div><strong>'+E(r.name)+'</strong><br><small>本机</small></div>'+label(runtimeStatus(r))+(r.installed?btn('配置智能体','chooseAgent',false,r.id):'')+'</div>').join('')):
 '<div data-filter-scope><div class="library-bar">'+search('搜索智能体或运行时')+'</div>'+(list.length?list.map(x=>'<button type="button" class="catalog-row clickable" data-filter-item data-act="agent" data-key="'+E(x.id)+'"><span class="role-icon" aria-hidden="true">◇</span><span><strong>'+E(x.name)+'</strong><br><small>'+E(runtimeName(x.runtime))+' · 本机</small></span>'+label(runtimeStatus(all('runtimes').find(r=>r.id===x.runtime)))+'<span aria-hidden="true">›</span></button>').join(''):empty('还没有智能体','从本机检测到的运行时创建研究角色。'))+'<p class="filter-empty" hidden>没有匹配的智能体。</p></div>'));
 const r=all('runtimes').find(x=>x.id===a.runtime);
 return navHeading(btn('智能体','nav',false,'智能体')+'<span aria-hidden="true">/</span><h1>'+E(a.name)+'</h1>')+body((returnPlan?btn('← 返回实验报告','plan',false,returnPlan):'')+(agentTab==='运行设置'?'':'<p class="lede">'+E(runtimeName(a.runtime))+' · 本机 '+label(runtimeStatus(r))+'</p>')+tabs(['概览','指令','Skills','运行设置'],agentTab,'agentTab')+
 (agentTab==='指令'?card('<h3>AGENTS.md</h3><p class="muted">这份 Markdown 属于当前智能体。</p><form class="fields inline-form" data-form="agentInstructions" data-retain>'+area('instructions','Markdown 指令',a.instructions)+'<button class="primary">保存指令</button></form>'):
 agentTab==='Skills'?agentSkills(a):agentTab==='运行设置'?card('<h3>运行时</h3>'+kv('机器','本机')+kv('运行时',runtimeName(a.runtime))+kv('状态',runtimeStatus(r))+(r?.executable?'':'<p class="muted">当前可保存配置，外部运行时尚未接入实验调度。</p>')):
 card('<div class="flex spread"><h3>角色配置</h3>'+btn('编辑名称','renameAgent')+'</div>'+kv('配置版本','v'+a.version)+kv('已分配 Skills',a.skills.length))));
}
function settings(){return head('设置')+body(card('<h2 class="section-heading">模拟训练</h2><form class="fields" data-form="settings">'+input('delay','每轮模拟训练秒数',S.settings.delay,'number')+input('slots','训练并发上限',S.settings.slots||2,'number')+'<button class="primary">保存设置</button></form>'))}
let renderedView='', quickThread=sessionStorage.getItem('tripsci-quick-thread')||'', quickSignature='';
function quickChat(){
 const root=$('#quick-chat');
 if(!root.childElementCount)root.innerHTML='<button type="button" class="quick-toggle" aria-label="工作区聊天" data-act="quickToggle" aria-controls="quick-panel" aria-expanded="false">◌ <span>工作区聊天</span></button><section id="quick-panel" aria-label="工作区聊天" hidden><header><strong>工作区聊天</strong><button type="button" data-act="quickFull" aria-label="打开完整聊天">↗</button><button type="button" data-act="quickToggle" aria-label="收起工作区聊天">−</button></header><div class="quick-log" role="log" aria-label="工作区消息"></div><form id="quick-send"><textarea name="text" aria-label="工作区聊天消息" placeholder="问进度、工作区或 Skills…" maxlength="4000" required></textarea><button class="primary" aria-label="发送工作区消息">↑</button></form></section>';
 const list=get('thread',quickThread)?.messages||[];
 const signature=JSON.stringify(list);
 if(signature!==quickSignature){
   const log=$('.quick-log'), follow=log.scrollHeight-log.clientHeight-log.scrollTop<35;
   log.innerHTML=list.length?transcript(list):'<p class="muted">在这里提问，当前页面会保持打开。</p>';
   if(follow)log.scrollTop=log.scrollHeight;
   quickSignature=signature;
 }
}
function render(){
 needsRender=false;
 const side=$('#side'), oldNav=side.scrollTop;
 const sidebarHtml=sidebar();if(sidebarHtml!==side._view){side.innerHTML=sidebarHtml;side._view=sidebarHtml;side.scrollTop=oldNav}
 if(!S){$('#main').innerHTML='<div class="loading">正在连接研究服务…</div>';return}
 const view=page+':'+id, same=renderedView===view;
 const html=({聊天:chat,研究计划:plans,项目:projects,智能体:agents,工具:tools,设置:settings})[page]();
 const main=$('#main');
 if(!same||html!==main._view){
   const saved={}, expanded=new Set(), groups=new Set([...main.querySelectorAll('.plan-group')].map(d=>d.dataset.detail));
   if(same){
     for(const key of ['.body','.conversation','.rail']){
       const el=main.querySelector(key);
       if(el)saved[key]=[el.scrollTop,el.scrollHeight-el.clientHeight-el.scrollTop<40];
     }
     for(const d of main.querySelectorAll('details[open]:not(.switcher)')){
       const key=d.dataset.detail||d.querySelector('summary')?.textContent;
       if(key)expanded.add(key);
     }
   }
   main.innerHTML=html;main._view=html;renderedView=view;
   if(same)for(const d of main.querySelectorAll('details:not(.switcher)')){
     const key=d.dataset.detail||d.querySelector('summary')?.textContent;
     if(key&&(expanded.has(key)||!d.matches('.plan-group')||groups.has(key)))d.open=expanded.has(key);
   }
   for(const key of ['.body','.conversation','.rail']){
     const el=main.querySelector(key), prior=saved[key];
     if(el&&(prior||key==='.conversation'))el.scrollTop=key==='.conversation'&&(!prior||prior[1])?el.scrollHeight:prior[0];
   }
 }
 quickChat();
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
 '<label>所属项目'+pick('workspace',[['','暂不关联'],...all('workspace').map(w=>[w.id,w.name])],page==='项目'?get('workspace',id)?.id:'')+'</label><input type="hidden" name="source" value="'+E(thread?.id)+'">','创建并打开');
}
function agentForm(a={},runtime=a.runtime||'local-process'){modal(a.id?'编辑智能体':'创建智能体 · 2 / 2','agent','<p>运行时：'+E(all('runtimes').find(x=>x.id===runtime)?.name||runtime)+'</p><input type="hidden" name="runtime" value="'+E(runtime)+'">'+input('name','名称',a.name)+area('instructions','Markdown 指令',a.instructions||'比较实验结果，遵守护栏。')+'<label><input type="checkbox" name="wide" '+(a.skills?.includes('wide-search')?'checked':'')+'> 启用 wide-search</label>'+all('skill').map(x=>'<label><input type="checkbox" name="skill" value="'+E(x.id)+'" '+(a.skills?.includes(x.id)?'checked':'')+'> '+E(x.name)+'</label>').join('')+'<input type="hidden" name="id" value="'+E(a.id)+'">','保存配置')}
const payload=f=>Object.fromEntries(new FormData(f));
const close=()=>$('#modal').close();
function saveAgent(a,patch){return act({op:'agent',id:a.id,name:a.name,runtime:a.runtime,instructions:a.instructions,skills:a.skills,...patch},close)}
document.addEventListener('click',e=>{for(const d of document.querySelectorAll('.switcher[open]'))if(!d.contains(e.target))d.open=false});
document.addEventListener('keydown',e=>{if(e.key==='Escape'){if($('#quick-panel')&&!$('#quick-panel').hidden&&e.target.closest('#quick-chat')){e.target.blur();$('.quick-toggle').click();$('.quick-toggle').focus();return}const d=$('.switcher[open]');if(d){d.open=false;d.querySelector('summary').focus()}}});
document.addEventListener('toggle',e=>{if(e.target.matches('.switcher[open]'))e.target.querySelector('[data-search]').focus()},true);
document.addEventListener('click',e=>{
 const b=e.target.closest('[data-act]');if(!b)return;const {act:a,key:k}=b.dataset;
 if(a==='quickToggle'){
   const panel=$('#quick-panel');panel.hidden=!panel.hidden;
   $('.quick-toggle').setAttribute('aria-expanded',String(!panel.hidden));
   if(!panel.hidden){const log=$('.quick-log');log.scrollTop=log.scrollHeight;$('#quick-send textarea').focus();}
   return;
 }
 if(a==='quickFull'){if(!$('#quick-panel').hidden){$('#quick-panel').hidden=true;$('.quick-toggle').setAttribute('aria-expanded','false')}return nav('聊天',quickThread)}
 if(a==='retry')return load();
 if(a==='retryPlan')return act({op:'retry',id});
 if(a==='nav')return nav(k);
 if(a==='chat')return nav('聊天',k);
 if(a==='plan')return nav('研究计划',k);
 if(a==='togglePlanStatus'){if(openPlanStatus.has(id))openPlanStatus.delete(id);else openPlanStatus.add(id);return render()}
 if(a==='planPrompt'){const field=$('#send textarea');if(!field.value){field.value=k;drafts[page+id]=k}field.focus();return}
 if(a==='resultFilter'){resultFilters[current().id]=k;return render()}
 if(a==='reportWorker'){const plan=id;nav('智能体',k);returnPlan=plan;agentTab='Skills';return render()}
 if(a==='reportSkill'||a==='agentSkill'){
   const p=a==='reportSkill'?get('plan',id):null, target=get('agent',k);if(!target)return;
   const template=p?'# 实验评审规范\n\n参考「'+p.title+'」的实验报告。\n\n- 明确假设、对照基线和主要指标。\n- 固定数据划分与评测入口。\n- 记录未通过护栏或没有改进的实验，以及下一步。':'# 实验规范\n\n- ';
   return modal('为 '+target.name+' 创建 Skill','workerSkill','<p>保存后直接分配给该 Worker。运行中的计划仍使用启动时的配置。</p>'+input('name','名称',p?'实验评审规范':'')+area('markdown','Skill Markdown',template)+'<input type="hidden" name="agent" value="'+E(k)+'">','保存并分配');
 }
 if(a==='downloadReport'){
   const p=get('plan',id);if(!p?.report)return;
   const url=URL.createObjectURL(new Blob([reportText(p.report)],{type:'text/markdown;charset=utf-8'}));
   const link=document.createElement('a');link.href=url;link.download='TripSci-'+p.id+'-report.md';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);return;
 }
 if(a==='allPlans'){page='研究计划';id='';return render()}
 if(a==='project'){project=k;return nav('项目',k)}
 if(a==='toolDetail')return nav('工具',k);
 if(a==='toolTab'){toolTab=k;return nav('工具')}
 if(a==='agentTab'){agentTab=k;return render()}
 if(a==='scanRuntimes')return load().then(()=>notice('已重新检测本机运行时'));
 if(a==='chooseAgent')return agentForm({},k);
 if(a==='renameAgent')return modal('编辑智能体名称','renameAgent',input('name','名称',get('agent',id).name),'保存');
 if(a==='removeSkill'){const x=get('agent',id);return saveAgent(x,{skills:x.skills.filter(v=>v!==k)})}
 if(a==='agent')return nav('智能体',k);
 if(a==='close')return close();
 if(a==='newProject'||a==='projectForPlan')return projectForm({},a==='projectForPlan');
 if(a==='sample')return projectForm(sample);
 if(a==='editProject')return projectForm(current());
 if(a==='newPlan')return planForm();
 if(a==='recordIntegration')return integrationForm();
 if(a==='newAgent')return modal('创建智能体 · 1 / 2','chooseRuntime','<h3>在哪里运行？</h3><p class="muted">本机 · 选择检测到的运行时。</p>'+all('runtimes').filter(r=>r.installed).map((r,i)=>'<label class="runtime-choice"><input name="runtime" type="radio" value="'+E(r.id)+'" '+(!i?'checked':'')+' required><span><strong>'+E(r.name)+'</strong><br><small>'+E(runtimeStatus(r))+'</small></span></label>').join(''),'继续');
 if(a==='editAgent')return agentForm(get('agent',id));
 if(a==='nameLLM')return act({op:'import_name_llm'},r=>{page='项目';id=project=r.id});
 if(a==='beans')return act({op:'import_beans'},r=>{page='项目';id=project=r.id});
 if(a==='finishLoop')return modal('结束持续迭代','finish','<p>已提交的实验会完成，再生成报告。不会再启动下一轮。</p>','确认结束');
 if(a==='iris')return act({op:'import_iris'},r=>{page='研究计划';id=r.id;project=r.workspace});
 if(a==='newTool')return modal('添加工具','chooseTool','<p>选择要添加到工作区的工具类型。</p>'+pick('kind',[['link','网页链接'],['command','命令参考']]),'继续');
 if(a==='newSkill')return modal('新建 Skill','skill',input('name','名称')+area('markdown','Skill Markdown'),'保存');

 if(a==='attach')return modal('关联项目','attach',all('workspace').length?'<label>项目'+pick('workspace',all('workspace').map(x=>[x.id,x.name]),get('plan',id)?.workspace)+'</label>':'<p>还没有项目。</p>'+btn('新建项目','projectForPlan'),'关联');
 if(a==='start'){
   const p=get('plan',id),env=get('workspace',p?.workspace);if(!env)return;
   const bean=env.adapter==='beans', ntl=env.adapter==='name-llm', real=bean||ntl||env.adapter==='iris';
   const extra=ntl?'<label>研究策略'+pick('strategy',[['char','字符 n-gram'],['style','文体与标点'],['adaptive','自由迭代']])+'</label>':bean?'<label>研究策略'+pick('strategy',[['centroid','质心与特征消融'],['bayes','高斯朴素贝叶斯'],['adaptive','自适应特征权重']])+'</label><label>运行方式'+pick('run_mode',[['bounded','固定轮次'],['continuous','持续迭代（自适应策略）']])+'</label><div id="loopInterval" hidden>'+input('interval','轮次间隔（秒）',30,'number')+'</div>':'';
   return modal('确认并启动实验','start','<p>'+E(env.name)+' · '+E(modeNames[env.mode])+(real?' · 真实数据</p>':' · 模拟</p>')+kv('数据',env.dataset)+kv(real?'准确率下限':'整体 AUC 下限',env.floor)+(real?kv('固定基线',env.baseline):input('baseline','对照基线',env.baseline))+area('design','已确认的实验设计',p.direction)+extra+'<div id="roundBudget">'+input('budget',ntl?'实验预算（1–20）':'实验预算（1–10）',ntl?4:3,'number')+'</div><label>执行者'+pick('agent',all('agent').filter(x=>x.runtime==='local-process').map(x=>[x.id,x.name+' · v'+x.version]))+'</label>',real?'启动本机评测':'启动模拟研究');
 }
 if(a==='feedback')return modal('给 Worker 反馈','feedback','<p>当前训练继续。可发送「保守」或「强度 0.55」来改变下一轮。</p>'+area('text','反馈'),'发送反馈');
 if(a==='check'){
   const f=$('#modal form');if(!f.reportValidity())return;
   const d=payload(f);act({...d,op:'check',floor:Number(d.floor)},r=>{const el=$('#modal .submit-error');if(el)el.textContent=r.message});return;
 }
 if(['pause','resume','decision'].includes(a))act({op:a,id,value:k});
});
document.addEventListener('change',e=>{
 if(e.target.name==='趋势指标'){chartChoices[current().id]=e.target.value;render()}
 if(e.target.name==='strategy'&&get('workspace',get('plan',id)?.workspace)?.adapter==='name-llm')$('#roundBudget input').value=e.target.value==='adaptive'?20:4;
 if(e.target.name==='run_mode'){
   const continuous=e.target.value==='continuous';$('#roundBudget').hidden=continuous;$('#loopInterval').hidden=!continuous;
   if(continuous)$('#modal select[name=strategy]').value='adaptive';
 }
 if(e.target.name==='mode')modeFields(e.target.value);
});
document.addEventListener('input',e=>{
 if(e.target.matches('#send textarea'))drafts[page+id]=e.target.value;
 if(e.target.matches('[data-search]')){
   const scope=e.target.closest('[data-filter-scope]'), query=e.target.value.toLowerCase().trim(), rows=Array.from(scope.querySelectorAll('[data-filter-item]'));
   rows.forEach(x=>x.hidden=!(x.textContent+' '+(x.closest('.plan-group')?.querySelector('summary').textContent||'')).toLowerCase().includes(query));
   scope.querySelectorAll('.plan-group').forEach(g=>{g.hidden=!g.querySelector('[data-filter-item]:not([hidden])');if(query&&!g.hidden)g.open=true});
   const no=scope.querySelector('.filter-empty');if(no)no.hidden=rows.some(x=>!x.hidden)||!query;
 }
});
document.addEventListener('focusout',e=>{if(e.target.matches('#send textarea'))setTimeout(()=>{if(!busy&&!$('#send textarea')?.matches(':focus')&&!$('#modal').open)render()},80)});
document.addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.isComposing&&e.target.matches('#send textarea,#quick-send textarea')){e.preventDefault();e.target.form.requestSubmit()}});
document.addEventListener('submit',async e=>{
 const f=e.target, op=f.getAttribute('data-form'), send=f.getAttribute('id')==='send';
 if(f.id==='quick-send'){
   e.preventDefault();
   const field=f.querySelector('textarea'), text=field.value.trim();
   if(!text||busy)return;
   return act({op:'message',text,thread:quickThread},r=>{quickThread=r.id;sessionStorage.setItem('tripsci-quick-thread',r.id);if(field.value.trim()===text)field.value=''});
 }
 if(!send&&!op)return;e.preventDefault();if(busy)return;
 const d=payload(f);
 if(send){
   const text=d.text.trim(), key=page+id;if(!text)return;
   return act({op:'message',text,[page==='聊天'?'thread':'plan']:id},r=>{delete drafts[key];id=r.id});
 }
 if(op==='workspace'){
   const attach=d.attach==='yes', plan=id;delete d.attach;
   return act({...d,op,floor:Number(d.floor)},r=>{close();project=r.id;if(attach)setTimeout(()=>act({op:'attach',id:plan,workspace:r.id}),0);else{page='项目';id=r.id}});
 }
 if(op==='noIntegration')return close();
 if(op==='integration'){
   const p=current(), plans=new FormData(f).getAll('sourcePlan');
   return act({op,workspace:p.id,plans,revision:d.revision,summary:d.summary,metrics:Object.fromEntries(projectMetrics(p).map(k=>[k,Number(d[k])]))},close);
 }
 if(op==='plan')return act({...d,op},r=>{close();page='研究计划';id=r.id});
 if(op==='chooseRuntime')return agentForm({},d.runtime);
 if(op==='chooseTool'){
   const name=kinds[d.kind];return modal('添加'+name,'tool',input('name','名称')+input('target',d.kind==='link'?'链接地址':'命令',undefined,d.kind==='link'?'url':'text')+'<input type="hidden" name="kind" value="'+E(d.kind)+'">','保存');
 }
 if(op==='workerSkill')return act({...d,op:'skill'},()=>{close();notice('已保存并分配给 Worker')});
 if(op==='tool'||op==='skill')return act({...d,op},r=>{close();id=r.id;toolTab=op==='skill'?'Skills':'工作区'});
 if(op==='assignSkill'){const x=get('agent',id);return saveAgent(x,{skills:[...new Set([...x.skills,d.skill])]})}
 if(op==='agentInstructions'||op==='renameAgent')return saveAgent(get('agent',id),d);
 if(op==='agent')return act({...d,op,skills:['adaptive-ctr',...(d.wide?['wide-search']:[]),...new FormData(f).getAll('skill')]},r=>{close();id=r.id;agentTab='概览';notice('智能体配置已保存')});
 if(op==='settings')return act({op,delay:Number(d.delay),slots:Number(d.slots)},()=>notice('已保存设置'));
 if(op==='attach'&&!d.workspace)return notice('请先新建项目');
 if(op==='start'){d.budget=Number(d.budget);if(d.interval!=null)d.interval=Number(d.interval)}
 act({...d,op,id},close);
});
render();load();setInterval(load,850);
