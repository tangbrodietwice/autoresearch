'use strict';
const $=q=>document.querySelector(q), E=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const modeNames={local:'本机执行',hybrid:'本机 Agent · 远端训练',remote:'远端执行'};
const statusNames={ready:'待调度',waiting:'训练中',paused:'已暂停',completed:'待评审'};
const modes={local:[],hybrid:[['training_host','远端训练连接'],['delivery','代码交付方式']],remote:[['agent_host','远端 Agent 连接'],['remote_dir','远端工作目录']]};
let S=null,page='项目',id='',project='',busy=false,timer,refreshing=false,epoch=0;
const drafts={};
let needsRender=false, lastPlan='', toolTab='发现', agentTab='概览';
const chartChoices={};
const metricNames={macro_f1:'Macro F1',accuracy:'准确率',low_freq_auc:'低频 AUC',overall_auc:'整体 AUC'};
const runtimeName=r=>all('runtimes').find(x=>x.id===r)?.name||r;
const runtimeStatus=r=>r?.installed?(r.executable?'可运行':'已检测 · 仅配置'):'未安装';
const navHeading=(crumb,actions='')=>'<header class="head"><div class="flex breadcrumb">'+crumb+'</div><div class="flex">'+actions+'</div></header>';
const search=(placeholder)=>'<input class="control search" data-search placeholder="'+E(placeholder)+'" aria-label="'+E(placeholder)+'" type="search">';
const tabs=(names,active,act)=>'<div class="view-tabs" aria-label="视图">'+names.map(n=>'<button type="button" data-act="'+act+'" data-key="'+E(n)+'" aria-pressed="'+(n===active)+'">'+E(n)+'</button>').join('')+'</div>';
const empty=(heading,copy,action='')=>'<div class="empty-state"><strong>'+E(heading)+'</strong><p>'+E(copy)+'</p>'+action+'</div>';
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
 if(p==='研究计划'){id=key||lastPlan||all('plan').at(-1)?.id||'';lastPlan=id}
 else id=key;
 if(p==='智能体')agentTab='概览';
 page=p;render()
}
function switcher(title, rows, act, selected, footer, a11y){
 return '<details class="switcher"><summary aria-label="'+E(a11y)+'" title="'+E(title)+'"><span>'+E(title)+'</span><span aria-hidden="true">⌄</span></summary><div class="switch-menu" data-filter-scope>'+search('搜索'+a11y.replace('切换',''))+'<div class="switch-rows">'+rows.map(([key,name,meta])=>'<button type="button" data-filter-item data-act="'+act+'" data-key="'+E(key)+'" '+(key===selected?'aria-current="true"':'')+'><span><strong>'+E(name)+'</strong><small>'+E(meta)+'</small></span>'+(key===selected?'✓':'')+'</button>').join('')+'<p class="filter-empty" hidden>没有匹配结果。</p></div><div class="switch-footer">'+footer+'</div></div></details>';
}
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
function experiment(e){return '<details><summary>第 '+e.round+' 轮 · '+E(outcome(e))+'</summary><p>'+metrics(e.result)+'</p><p class="mono">Job '+E(e.id)+(e.k?'<br>k='+E(e.k)+' · '+(e.scale?'已缩放':'未缩放'):'')+'<br>数据 '+E(e.dataset)+'<br>代码 '+E(e.revision)+'<br>报告 '+E(e.report)+'</p></details>'}
function rail(p){
 const t=task(p), env=t?.environment||get('workspace',p.workspace), job=t&&get('job',t.pending_job);
 const ex=t?all('experiment').filter(e=>e.task===t.id):[];
 let out='<div class="flex spread"><h2>研究计划状态</h2>'+label(state(p))+'</div><section>'+kv('项目',env?.name||'未关联项目')+kv('执行模式',env?modeNames[env.mode]+(env.adapter==='iris'?' · 真实数据':' · 模拟'):'待确认')+kv('基线',t?.baseline||env?.baseline||'待确认')+(env?kv('数据版本',env.dataset)+kv(env.adapter==='iris'?'准确率下限':'整体 AUC 下限',env.floor)+kv('项目配置版本','v'+env.version):'')+'</section>';
 if(!t)return out+'<section><h3>待安排</h3><p>讨论可以先开始。启动前确认项目、基线和轮次预算。</p><div class="flex">'+btn(env?'更换项目':'关联项目','attach')+(env?btn('确认实验计划','start',true):btn('新建项目','projectForPlan',true))+'</div></section><section><h3>正在运行</h3><p class="muted">计划尚未启动。</p></section><section><h3>已完成实验</h3><p class="muted">首轮完成后显示结果。</p></section>';
 out+='<section>'+kv('执行者',t.agent.name+' · v'+t.agent.version)+kv('预算',t.round+' / '+t.max_experiments)+'<details><summary>配置快照</summary><p>'+E(env.repo)+'<br>'+E(env.train)+' · '+E(env.evaluate)+'</p><p>'+E(t.agent.instructions)+'</p></details></section>';
 out+='<section><h3>正在运行</h3>'+(job?'<div class="runbox"><strong>第 '+t.round+' 轮 · '+(job.result?'结果已返回，待分析':job.k?'本机评测':'模拟训练')+'</strong><p class="mono">'+E(job.id)+'</p><p>'+ (job.k?'k='+E(job.k):'平滑强度 '+E(job.strength))+'</p></div>':'<small>当前没有训练 Job。</small>')+
 (t.status==='completed'?'': '<div class="flex">'+btn(t.status==='paused'?'恢复':'暂停后续调度',t.status==='paused'?'resume':'pause')+btn('给 Worker 反馈','feedback')+'</div>')+'</section>';
 out+='<section><h3>接下来</h3><p>'+(t.status==='completed'?'实验已结束。':'剩余预算 '+Math.max(0,t.max_experiments-t.round)+' 轮；具体参数由 Worker 根据当前结果和反馈决定。')+'</p>'+all('inbox').filter(x=>x.task===t.id&&!['pause','resume'].includes(x.message)).map(x=>'<p>'+label(x.consumed?(x.disposition||'已读取'):'已送达')+' '+E(x.message)+'</p>').join('')+'</section>';
 return out+'<section><h3>已完成实验</h3>'+(ex.slice().sort((a,b)=>b.round-a.round).map(experiment).join('')||'<p class="muted">还没有结果。</p>')+(p.decision?'<p>结论：'+E(p.decision)+'</p>'+(p.holdout?'<p>'+(p.holdout.candidate?'保留测试集：'+metrics(p.holdout.candidate)+'<br>':'')+'测试基线：'+metrics(p.holdout.baseline)+'</p>':''):t.status==='completed'?'<div class="flex">'+(t.best.revision?btn('保留候选','decision',true,'保留候选'):'')+btn('不采用','decision',false,'不采用')+'</div>':'')+'</section>';
}
function updateRail(){const p=get('plan',id), old=$('.rail');if(!p||!old)return;const y=old.scrollTop, expanded=Array.from(old.querySelectorAll('details'),d=>d.open);old.innerHTML=rail(p);old.querySelectorAll('details').forEach((d,i)=>d.open=!!expanded[i]);old.scrollTop=y}
function plans(){
 const p=get('plan',id), list=all('plan').slice().reverse();
 if(!p&&!list.length)return head('研究计划',btn('＋ 新建计划','newPlan',true))+body(title('研究计划','在对话中确定研究方向，随时跟踪实验进展。')+empty('还没有研究计划','先写下你想验证的问题。可以稍后再关联项目。',btn('创建第一项研究','newPlan',true)));
 const chooser=switcher(p?.title||'全部研究计划',list.map(x=>[x.id,x.title,(get('workspace',x.workspace)?.name||'未关联项目')+' · '+state(x)]),'plan',id,btn('查看全部计划','allPlans')+btn('＋ 新建计划','newPlan',true),'切换研究计划');
 const header=navHeading('<strong>研究计划</strong><span aria-hidden="true">/</span>'+chooser,btn('＋ 新建计划','newPlan'));
 if(!p)return header+body(title('全部研究计划','按项目和状态查找研究。')+'<div data-filter-scope>'+search('搜索计划、项目或状态')+list.map(x=>'<div data-filter-item>'+planRow(x)+'</div>').join('')+'<p class="filter-empty" hidden>没有匹配结果。</p></div>');
 return header+'<div class="issue"><div class="dialogue"><div class="conversation" aria-label="研究讨论"><div class="inner"><div class="issue-intro">'+title(p.title,p.direction)+'</div><div class="discussion-title">讨论</div>'+(p.messages.length?transcript(p.messages):'<p class="muted">还没有讨论。可以先明确要验证的假设、对照和成功标准。</p>')+'</div></div>'+composer('讨论假设、实验安排或询问进展…')+'</div><aside class="rail" aria-label="研究计划状态">'+rail(p)+'</aside></div>';
}
function outcome(e){return e.guardrail_passed===false?'未通过护栏':e.accepted?'刷新最佳候选':'未刷新最佳候选'}
function experimentSummary(e,p){
 const t=task(p), key=t?.constraints?.primary_metric, value=e.result?.[key];
 const idea=e.k?'k = '+e.k+' · '+(e.scale?'特征标准化':'原始特征'):'平滑强度 '+e.strength;
 return '<article class="result-row"><div class="flex spread"><strong>'+E(p.title)+' · 第 '+E(e.round)+' 轮</strong>'+label(outcome(e))+'</div><p>'+E(idea)+(value==null?'':' · <b>'+E(metricNames[key])+' '+Number(value).toFixed(4)+'</b>')+'</p><details><summary>查看指标与复现信息</summary><p>'+metrics(e.result)+'</p><p class="mono">代码 '+E(e.revision)+'<br>报告 '+E(e.report)+'</p></details>'+btn('打开研究计划','plan',false,p.id)+'</article>';
}
const projectMetrics=p=>p.adapter==='iris'?['macro_f1','accuracy']:['low_freq_auc','overall_auc'];
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
 const p=current(), actions=btn('＋ 新建项目','newProject',true)+btn('导入 Iris 任务','iris');
 if(!p)return head('项目')+body('<section class="guide"><div class="guide-copy"><span class="guide-tag">项目</span>'+title('从第一个研究项目开始','配置代码、训练与评测入口。实验开始后，结果会自动回到项目看板。')+actions+'</div><div class="guide-options"><h2>从模板开始</h2>'+card('<h3>CTR 排序研究</h3><p>预填模拟仓库、数据和评测设置。</p>'+btn('使用示例','sample'))+card('<h3>Iris 鸢尾花分类</h3><p>使用公开真实数据，自动创建项目和研究草稿。</p>'+btn('导入 Iris 任务','iris',true))+'</div></section>');
 const ps=all('plan').filter(x=>x.workspace===p.id), byTask=new Map(ps.filter(x=>x.task).map(x=>[x.task,x]));
 const ex=all('experiment').filter(x=>byTask.has(x.task)).sort((a,b)=>(b.ready_at||0)-(a.ready_at||0));
 return navHeading('<strong>项目</strong><span aria-hidden="true">/</span>'+switcher(p.name,all('workspace').map(w=>[w.id,w.name,modeNames[w.mode]]),'project',p.id,actions,'切换项目'),actions)+body(title(p.name,'项目看板 · '+(p.adapter==='iris'?'真实评测':'模拟评测'))+
 '<div class="dash-stats">'+card('<small>研究计划</small><strong>'+ps.length+'</strong>')+card('<small>进行中</small><strong>'+ps.filter(q=>['ready','waiting'].includes(task(q)?.status)).length+'</strong>')+card('<small>已完成实验</small><strong>'+ex.length+'</strong>')+'</div>'+trend(p)+
 card('<h3>近期实验</h3>'+(ex.slice(0,6).map(e=>experimentSummary(e,byTask.get(e.task))).join('')||empty('尚无实验结果','首轮评测完成后，这里会出现指标、结论和复现入口。',btn('从此项目新建计划','newPlan'))))+
 card('<div class="flex spread"><h3>研究计划</h3>'+btn('＋ 新建计划','newPlan')+'</div>'+(ps.map(planRow).join('')||'<p class="muted">此项目还没有研究计划。</p>'))+
 card('<details><summary>项目配置 · v'+E(p.version)+'</summary>'+kv('模式',modeNames[p.mode])+kv('默认基线',p.baseline)+kv('数据',p.dataset)+kv('训练入口',p.train)+kv('评测入口',p.evaluate)+(p.adapter==='iris'?'<p>固定协议 · 本机真实评测</p>':btn('编辑配置','editProject'))+'</details>'));
}
const irisTool={id:'builtin-iris',name:'Iris 实验启动器',description:'导入公开分类数据，生成预填配置和研究草稿。',kind:'builtin'};
function library(){return [irisTool,...all('tool').map(t=>({...t,description:t.kind==='link'?'打开研究文档或外部服务。':'保存常用命令供查看。'})),...all('skill').map(x=>({...x,kind:'skill',description:x.markdown.trim().split(/\r?\n/).find(line=>line.trim()&&!line.startsWith('#'))?.slice(0,110)||'可分配给智能体的 Markdown 指南。'}))]}
const kinds={builtin:'内置工作流',link:'网页链接',command:'命令参考',skill:'Skill'};
function toolCard(t){return '<button class="tool-tile" type="button" data-filter-item data-act="toolDetail" data-key="'+E(t.id)+'"><span class="tool-icon" aria-hidden="true">'+({builtin:'✦',link:'↗',command:'›_',skill:'◇'})[t.kind]+'</span><strong>'+E(t.name)+'</strong><small>'+E(t.description)+'</small>'+label(kinds[t.kind])+'</button>'}
function tools(){
 const items=library(), t=items.find(x=>x.id===id), add=btn('＋ 添加工具','newTool',true);
 if(t)return navHeading(btn('工具','nav',false,'工具')+'<span aria-hidden="true">/</span><strong>'+E(t.name)+'</strong>',add)+body('<div class="detail-intro">'+label(kinds[t.kind])+title(t.name,t.description)+'</div>'+
 card(t.kind==='builtin'?'<h3>包含的能力</h3><p>下载数据已打包，导入后可直接启动真实本机评测。</p>'+btn('导入 Iris 任务','iris',true):t.kind==='skill'?'<h3>SKILL.md</h3><pre>'+E(t.markdown)+'</pre>'+btn('管理智能体分配','nav',false,'智能体'):t.kind==='link'?'<h3>链接</h3><a target="_blank" rel="noopener noreferrer" href="'+E(t.target)+'">'+E(t.target)+'</a>':'<h3>命令参考</h3><pre>'+E(t.target)+'</pre><small>仅供查看，TripSci 不会执行。</small>'));
 const shown=toolTab==='发现'?[irisTool]:toolTab==='Skills'?items.filter(x=>x.kind==='skill'):items;
 return head('工具',add)+body(title('工具目录','发现研究工作流，管理工作区工具与 Skills。')+tabs(['发现','工作区工具','Skills'],toolTab,'toolTab')+
 '<div data-filter-scope><div class="flex spread library-bar">'+search('搜索工具')+(toolTab==='Skills'?btn('＋ 新建 Skill','newSkill'):'')+'</div>'+
 (shown.length?'<div class="tile-grid">'+shown.map(toolCard).join('')+'</div>':empty('还没有自定义 Skill','创建后可从智能体详情分配。',btn('新建第一个 Skill','newSkill',true)))+'<p class="filter-empty" hidden>没有匹配的工具。</p></div>');
}
function agentSkills(a){
 const names={'adaptive-ctr':'自适应实验策略','wide-search':'扩大搜索范围'};
 const chosen=a.skills.map(k=>[k,get('skill',k)?.name||names[k]||k]);
 const candidates=[['wide-search',names['wide-search']],...all('skill').map(x=>[x.id,x.name])].filter(([k])=>!a.skills.includes(k));
 return card('<h3>已分配 Skills</h3>'+(chosen.length?chosen.map(([k,n])=>'<div class="catalog-row"><strong>'+E(n)+'</strong>'+ (k==='adaptive-ctr'?label('内置默认'):btn('移除','removeSkill',false,k))+'</div>').join(''):'<p class="muted">还没有分配 Skill。</p>')+
 (candidates.length?'<form data-form="assignSkill" class="flex inline-form">'+pick('skill',candidates)+'<button class="primary">添加 Skill</button></form>':'<p class="muted">所有可用 Skills 已分配。可以从工具目录新建。</p>'+btn('去工具目录','openSkills')));
}
function agents(){
 const a=get('agent',id), newAgent=btn('＋ 新建智能体','newAgent',true), list=all('agent');
 if(!a)return head('智能体',newAgent)+body(title('智能体','管理研究角色及其运行位置。')+tabs(['智能体','运行时'],agentTab==='运行时'?'运行时':'智能体','agentTab')+
 (agentTab==='运行时'?card('<div class="flex spread"><h3>本机运行时</h3>'+btn('重新检测','scanRuntimes')+'</div>'+all('runtimes').map(r=>'<div class="catalog-row"><div><strong>'+E(r.name)+'</strong><br><small>本机</small></div>'+label(runtimeStatus(r))+(r.installed?btn('配置智能体','chooseAgent',false,r.id):'')+'</div>').join('')):
 '<div data-filter-scope><div class="library-bar">'+search('搜索智能体或运行时')+'</div>'+(list.length?list.map(x=>'<button type="button" class="catalog-row clickable" data-filter-item data-act="agent" data-key="'+E(x.id)+'"><span class="role-icon" aria-hidden="true">◇</span><span><strong>'+E(x.name)+'</strong><br><small>'+E(runtimeName(x.runtime))+' · 本机</small></span>'+label(runtimeStatus(all('runtimes').find(r=>r.id===x.runtime)))+'<span aria-hidden="true">›</span></button>').join(''):empty('还没有智能体','从本机检测到的运行时创建研究角色。',newAgent))+'<p class="filter-empty" hidden>没有匹配的智能体。</p></div>'));
 const r=all('runtimes').find(x=>x.id===a.runtime);
 return navHeading(btn('智能体','nav',false,'智能体')+'<span aria-hidden="true">/</span><strong>'+E(a.name)+'</strong>',newAgent)+body('<div class="detail-intro">'+label(runtimeStatus(r))+title(a.name,runtimeName(a.runtime)+' · 本机')+'</div>'+tabs(['概览','指令','Skills','运行设置'],agentTab,'agentTab')+
 (agentTab==='指令'?card('<h3>AGENTS.md</h3><p class="muted">这份 Markdown 属于当前智能体。</p><form class="fields inline-form" data-form="agentInstructions" data-retain>'+area('instructions','Markdown 指令',a.instructions)+'<button class="primary">保存指令</button></form>'):
 agentTab==='Skills'?agentSkills(a):agentTab==='运行设置'?card('<h3>运行时</h3>'+kv('机器','本机')+kv('运行时',runtimeName(a.runtime))+kv('状态',runtimeStatus(r))+(r?.executable?'':'<p class="muted">当前可保存配置，外部运行时尚未接入实验调度。</p>')):
 card('<div class="flex spread"><h3>角色配置</h3>'+btn('编辑名称','renameAgent')+'</div>'+kv('名称',a.name)+kv('配置版本','v'+a.version)+kv('已分配 Skills',a.skills.length))));
}
function settings(){return head('设置')+body(title('设置','本地工作区的模拟运行配置。')+card('<form class="fields" data-form="settings">'+input('delay','每轮模拟训练秒数',S.settings.delay,'number')+input('slots','训练并发上限',S.settings.slots||2,'number')+'<button class="primary">保存设置</button></form>'))}
function render(){
 needsRender=false;
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
function agentForm(a={},runtime=a.runtime||'local-process'){modal(a.id?'编辑智能体':'创建智能体 · 2 / 2','agent','<p>运行时：'+E(all('runtimes').find(x=>x.id===runtime)?.name||runtime)+'</p><input type="hidden" name="runtime" value="'+E(runtime)+'">'+input('name','名称',a.name)+area('instructions','Markdown 指令',a.instructions||'比较实验结果，遵守护栏。')+'<label><input type="checkbox" name="wide" '+(a.skills?.includes('wide-search')?'checked':'')+'> 启用 wide-search</label>'+all('skill').map(x=>'<label><input type="checkbox" name="skill" value="'+E(x.id)+'" '+(a.skills?.includes(x.id)?'checked':'')+'> '+E(x.name)+'</label>').join('')+'<input type="hidden" name="id" value="'+E(a.id)+'">','保存配置')}
const payload=f=>Object.fromEntries(new FormData(f));
const close=()=>$('#modal').close();
function saveAgent(a,patch){return act({op:'agent',id:a.id,name:a.name,runtime:a.runtime,instructions:a.instructions,skills:a.skills,...patch},close)}
document.addEventListener('click',e=>{for(const d of document.querySelectorAll('.switcher[open]'))if(!d.contains(e.target))d.open=false});
document.addEventListener('keydown',e=>{if(e.key==='Escape'){const d=$('.switcher[open]');if(d){d.open=false;d.querySelector('summary').focus()}}});
document.addEventListener('toggle',e=>{if(e.target.matches('.switcher[open]'))e.target.querySelector('[data-search]').focus()},true);
document.addEventListener('click',e=>{
 const b=e.target.closest('[data-act]');if(!b)return;const {act:a,key:k}=b.dataset;
 if(a==='retry')return load();
 if(a==='nav')return nav(k);
 if(a==='chat')return nav('聊天',k);
 if(a==='plan')return nav('研究计划',k);
 if(a==='allPlans'){page='研究计划';id='';return render()}
 if(a==='project'){project=k;return nav('项目')}
 if(a==='toolDetail')return nav('工具',k);
 if(a==='toolTab'){toolTab=k;return nav('工具')}
 if(a==='openSkills'){toolTab='Skills';return nav('工具')}
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
 if(a==='iris')return act({op:'import_iris'},r=>{page='研究计划';lastPlan=id=r.id;project=r.workspace});
 if(a==='newTool')return modal('添加工具','chooseTool','<p>选择要添加到工作区的工具类型。</p>'+pick('kind',[['link','网页链接'],['command','命令参考'],['skill','Skill']]),'继续');
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
 if(e.target.name==='趋势指标'){chartChoices[current().id]=e.target.value;render()}
 if(e.target.name==='mode')modeFields(e.target.value);
});
document.addEventListener('input',e=>{
 if(e.target.matches('#send textarea'))drafts[page+id]=e.target.value;
 if(e.target.matches('[data-search]')){
   const scope=e.target.closest('[data-filter-scope]'), query=e.target.value.toLowerCase().trim(), rows=Array.from(scope.querySelectorAll('[data-filter-item]'));
   rows.forEach(x=>x.hidden=!x.textContent.toLowerCase().includes(query));
   const no=scope.querySelector('.filter-empty');if(no)no.hidden=rows.some(x=>!x.hidden)||!query;
 }
});
document.addEventListener('focusout',e=>{if(e.target.matches('#send textarea'))setTimeout(()=>{if(!busy&&!$('#send textarea')?.matches(':focus')&&!$('#modal').open)render()},80)});
document.addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.isComposing&&e.target.matches('#send textarea')){e.preventDefault();e.target.form.requestSubmit()}});
document.addEventListener('submit',async e=>{
 const f=e.target, op=f.getAttribute('data-form'), send=f.getAttribute('id')==='send';
 if(!send&&!op)return;e.preventDefault();if(busy)return;
 const d=payload(f);
 if(send){
   const text=d.text.trim(), key=page+id;if(!text)return;
   return act({op:'message',text,[page==='聊天'?'thread':'plan']:id},r=>{delete drafts[key];id=r.id});
 }
 if(op==='workspace'){
   const attach=d.attach==='yes', plan=id;delete d.attach;
   return act({...d,op,floor:Number(d.floor)},r=>{close();project=r.id;if(attach)setTimeout(()=>act({op:'attach',id:plan,workspace:r.id}),0);else{page='项目';id=''}});
 }
 if(op==='noIntegration')return close();
 if(op==='integration'){
   const p=current(), plans=new FormData(f).getAll('sourcePlan');
   return act({op,workspace:p.id,plans,revision:d.revision,summary:d.summary,metrics:Object.fromEntries(projectMetrics(p).map(k=>[k,Number(d[k])]))},close);
 }
 if(op==='plan')return act({...d,op},r=>{close();page='研究计划';lastPlan=id=r.id});
 if(op==='chooseRuntime')return agentForm({},d.runtime);
 if(op==='chooseTool'){
   if(d.kind==='skill')return modal('新建 Skill','skill',input('name','名称')+area('markdown','Skill Markdown'),'保存');
   const name=kinds[d.kind];return modal('添加'+name,'tool',input('name','名称')+input('target',d.kind==='link'?'链接地址':'命令',undefined,d.kind==='link'?'url':'text')+'<input type="hidden" name="kind" value="'+E(d.kind)+'">','保存');
 }
 if(op==='tool'||op==='skill')return act({...d,op},r=>{close();id=r.id;toolTab=op==='skill'?'Skills':'工作区工具'});
 if(op==='assignSkill'){const x=get('agent',id);return saveAgent(x,{skills:[...new Set([...x.skills,d.skill])]})}
 if(op==='agentInstructions'||op==='renameAgent')return saveAgent(get('agent',id),d);
 if(op==='agent')return act({...d,op,skills:['adaptive-ctr',...(d.wide?['wide-search']:[]),...new FormData(f).getAll('skill')]},r=>{close();id=r.id;agentTab='概览';notice('智能体配置已保存')});
 if(op==='settings')return act({op,delay:Number(d.delay),slots:Number(d.slots)},()=>notice('已保存设置'));
 if(op==='attach'&&!d.workspace)return notice('请先新建项目');
 if(op==='start')d.budget=Number(d.budget);
 act({...d,op,id},close);
});
render();load();setInterval(load,850);
