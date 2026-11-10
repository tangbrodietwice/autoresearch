'use strict';
const $=q=>document.querySelector(q), E=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const modeNames={local:'本机执行',hybrid:'本机 Agent · 远端训练',remote:'远端执行'};
const statusNames={ready:'进行中',waiting:'进行中',paused:'已暂停',failed:'执行失败',completed:'待评审'};
const modes={local:[],hybrid:[['training_host','远端训练连接'],['delivery','代码交付方式']],remote:[['agent_host','远端 Agent 连接'],['remote_dir','远端工作目录']]};
let S=null,page='项目',id='',project='',busy=false,timer,refreshing=false,epoch=0;
const drafts={};
let needsRender=false, toolTab='我的工具', agentTab='概览', returnPlan='';
const resultFilters={}, openPlanStatus=new Set();
const chartChoices={};
const metricNames={balanced_accuracy:'Balanced Accuracy',macro_f1:'Macro F1',accuracy:'准确率',low_freq_auc:'低频 AUC',overall_auc:'整体 AUC'};
const runtimeName=r=>r==='local-process'?'TripSci 内置执行器':all('runtimes').find(x=>x.id===r)?.name||r;
const externalRuntimes=()=>all('runtimes').filter(r=>r.id!=='local-process');
const supervisorStatus=a=>a.runtime_detected?'已检测 Codex':'未检测到 Codex';
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
const pendingActions=new Map();
async function act(payload,done=()=>{},onError=null){
 if(busy)return;
 busy=true;epoch++;
 const err=$('#modal .submit-error');
 if(err)err.textContent='';
 const signature=JSON.stringify(payload);
 const key=pendingActions.get(signature)||crypto.randomUUID();
 pendingActions.set(signature,key);
 let row;
 try{
   row=await api('/v1/action',{...payload,request_key:key});
 }catch(e){
   if(onError)onError(e.message);
   else if(err&&$('#modal').open)err.textContent=e.message;
   else notice(e.message);
   busy=false;
   return;
 }
 pendingActions.delete(signature);
 let refreshFailed=false;
 try{S=await api('/v1/state')}catch{refreshFailed=true}
 finally{busy=false}
 done(row);
 render();
 if(refreshFailed)notice('操作已保存，正在重新同步。');
}
function nav(p,key='',fromRecent=false){
 $('#notice').hidden=true;
 id=key;
 if(p==='智能体'){agentTab='概览';returnPlan=''}
 page=p;if(!fromRecent)rememberView(p,key);render()
}
function switcher(title, rows, act, selected, footer, a11y){
 return '<details class="switcher"><summary aria-label="'+E(a11y)+'" title="'+E(title)+'"><span>'+E(title)+'</span><span aria-hidden="true">⌄</span></summary><div class="switch-menu" data-filter-scope>'+search('搜索'+a11y.replace('切换',''))+'<div class="switch-rows">'+rows.map(([key,name,meta])=>'<button type="button" data-filter-item data-act="'+act+'" data-key="'+E(key)+'" '+(key===selected?'aria-current="true"':'')+'><span><strong>'+E(name)+'</strong><small>'+E(meta)+'</small></span>'+(key===selected?'✓':'')+'</button>').join('')+'<p class="filter-empty" hidden>没有匹配结果。</p></div>'+(footer?'<div class="switch-footer">'+footer+'</div>':'')+'</div></details>';
}
const glyphs={
 home:'<path d="m3 10 9-7 9 7v10H3z"/><path d="M9 20v-6h6v6"/>',
 agent:'<rect x="4" y="7" width="16" height="13" rx="4"/><path d="M12 3v4m-4 5h.01m8 0h.01m-7 4h6"/>',
 tools:'<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><path d="M17.5 14v7m-3.5-3.5h7"/>',
 settings:'<circle cx="12" cy="12" r="3"/><path d="m9 3-1 3-3 1-2 3 2 2-1 4 3 2 3-1 2 4 3-2 1-3 4-1 1-3-3-2V6l-3-2-3 2z"/>',
 project:'<path d="M3 7h7l2 2h9v10H3z"/>',
 chat:'<path d="M20 15a2 2 0 0 1-2 2H8l-4 4V6a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2z"/>',
 plans:'<rect x="5" y="3" width="14" height="18" rx="2"/><path d="M9 8h6m-6 4h6m-6 4h4"/>',

};
const icon=(name)=>'<svg viewBox="0 0 24 24" width="17" height="17" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'+glyphs[name]+'</svg>';
const projectIcon=()=>'<span class="project-icon">'+icon('project')+'</span>';
let recentViews=[];
try{recentViews=JSON.parse(localStorage.getItem('tripsci-recent')||'[]')}catch{}
let projectsExpanded=true;
const chatTurns=new Map();
try{
 for(const turn of JSON.parse(sessionStorage.getItem('tripsci-chat-turns')||'[]')){
   chatTurns.set(turn.page+turn.id,turn);
   page=turn.page;id=turn.id;
 }
}catch{}
function saveChatTurns(){
 try{sessionStorage.setItem('tripsci-chat-turns',JSON.stringify([...chatTurns.values()]))}catch{}
}
function rememberView(kind,key){
 if(!key||!['聊天','研究计划'].includes(kind))return;
 recentViews=[{kind,key},...recentViews.filter(x=>x.kind!==kind||x.key!==key)].slice(0,12);
 localStorage.setItem('tripsci-recent',JSON.stringify(recentViews));
}
function sideButton(text,action,key,symbol,active=false){
 return '<button type="button" class="quiet side-link" title="'+E(text)+'" data-act="'+action+'" data-key="'+E(key)+'" '+(active?'aria-current="page"':'')+'>'+symbol+'<span>'+E(text)+'</span></button>';
}
function sidebar(){
 const work=['项目','聊天','研究计划','实验库'].includes(page);
 const railItems=[['工作区','项目','home'],['智能体','智能体','agent'],['工具','工具','tools'],['设置','设置','settings']];
 const rail=railItems.map(([label,key,glyph])=>'<button type="button" class="rail-link" title="'+label+'" aria-label="'+label+'" data-act="nav" data-key="'+key+'" '+((key==='项目'?work:page===key)?'aria-current="page"':'')+'>'+icon(glyph)+'</button>').join('');
 const projects=all('workspace').map(w=>{
   const children=all('plan').filter(p=>p.workspace===w.id).slice().reverse();
   return '<div class="side-project"><div class="side-project-row">'+
     sideButton(w.name,'project',w.id,projectIcon(),page==='项目'&&id===w.id)+'</div>'+
     (children.length?'<div class="side-project-plans">'+children.map(p=>sideButton(p.title,'plan',p.id,icon('plans'),page==='研究计划'&&id===p.id)).join('')+'</div>':'')+'</div>';
 }).join('');
 const kinds={'聊天':['thread','chat','chat'],'研究计划':['plan','plan','plans']};
 const chats=all('thread').slice(-6).reverse();
 const plans=all('plan').slice(-8).reverse();
 const entries=[...recentViews];
 for(let i=0;i<Math.max(chats.length,plans.length);i++){
   if(chats[i])entries.push({kind:'聊天',key:chats[i].id});
   if(plans[i])entries.push({kind:'研究计划',key:plans[i].id});
 }
 const seen=new Set();
 const recent=entries.map(({kind,key})=>{
   if(!kinds[kind]||seen.has(key))return '';
   seen.add(key);
   const [collection,action,glyph]=kinds[kind], row=get(collection,key);
   return row?sideButton(row.title||row.name,action,key,icon(glyph),page===kind&&id===key):'';
 }).filter(Boolean).slice(0,8);
 return '<nav class="primary-nav" aria-label="一级导航">'+rail+'</nav><div class="workspace-nav"><div class="brand">'+mark+'TripSci</div><nav aria-label="工作区">'+
 sideButton('新聊天','newChat','',icon('chat'),page==='聊天'&&!id)+
 sideButton('新研究计划','newPlan','',icon('plans'),false)+'</nav>'+
 '<section class="project-section" aria-label="项目"><div class="project-heading">'+sideButton('项目','nav','项目','',page==='项目'&&!id)+
 '<button type="button" class="quiet project-add" aria-label="新建项目" title="新建项目" data-act="newProject">＋</button>'+
 (projects?'<button type="button" class="quiet project-expand" aria-label="'+(projectsExpanded?'收起所有项目':'展开所有项目')+'" aria-controls="project-tree" aria-expanded="'+projectsExpanded+'" data-act="toggleProjects">'+(projectsExpanded?'⌄':'›')+'</button>':'')+
 '</div><div id="project-tree" class="project-tree"'+(projectsExpanded?'':' hidden')+'>'+projects+'</div></section>'+
 '<section class="recent-section" aria-label="最近"><h4>最近</h4>'+
 '<div class="recent-items">'+recent.join('')+'</div></section></div>';
}
const proposalFields={
 name:'名称',title:'标题',repo:'代码地址',baseline:'基线',dataset:'数据版本',train:'训练入口',evaluate:'评测入口',
 mode:'执行模式',floor:'评测护栏',training_host:'训练服务器',delivery:'代码交付方式',agent_host:'智能体服务器',
 remote_dir:'远端目录',direction:'研究方向',workspace:'所属项目',design:'实验设计',budget:'实验轮数',
 agent:'执行智能体',strategy:'实验策略',research_mode:'研究决策方式',run_mode:'运行方式',interval:'轮次间隔（秒）',
 text:'反馈',markdown:'Skill 内容',instructions:'智能体指令',runtime:'运行时',skills:'Skills',delay:'模拟训练时长（秒）',slots:'并发上限'
};
function proposalSummary(proposal){
 const kind={workspace:'workspace',agent:'agent'}[proposal.operation]||'plan';
 return Object.entries(proposal.payload).map(([key,value])=>{
   const resource={id:kind,workspace:'workspace',agent:'agent'}[key];
   const row=resource&&get(resource,value);
   const display=row?.name||row?.title||(key==='mode'?modeNames[value]:undefined)||
     (key==='run_mode'?{bounded:'固定轮次',continuous:'持续迭代'}[value]:undefined)||
     (Array.isArray(value)?value.map(id=>get('skill',id)?.name||id).join('、'):String(value??''));
   return '<dt>'+E(key==='agent'&&proposal.operation==='skill'?'分配给':key==='id'?{workspace:'目标项目',agent:'目标智能体',plan:'目标研究计划'}[kind]:proposalFields[key]||key)+
     '</dt><dd>'+E(display)+'</dd>';
 }).join('');
}
function supervisorProposal(proposal){
 if(!proposal)return '';
 const pending=proposal.status==='pending';
 const effect=proposal.operation==='workspace'&&!proposal.payload.id
   ?'确认后将在 TripSci 项目存储中创建专属目录并保存配置。'
   :'确认后按工作区规则校验并执行。';
 return '<section class="supervisor-proposal" aria-label="主管提案"><div class="flex spread"><strong>'+E(proposal.label)+'</strong>'+
   label(pending?'待确认':proposal.status==='cancelled'?'已取消':'已执行')+'</div><dl class="proposal-fields">'+proposalSummary(proposal)+'</dl>'+
   (pending?'<p class="muted">'+E(effect)+'</p>'+'<div class="flex">'+btn('取消','cancelSupervisor',false,proposal.id)+btn('确认执行','confirmSupervisor',true,proposal.id)+'</div>':'')+'</section>';
}
// markdown-it 15.0.3 is bundled locally so chat formatting also works offline.
const messageMarkdown=window.markdownit?.({html:false,linkify:true,breaks:true}).disable('image');
if(messageMarkdown){
 messageMarkdown.validateLink=url=>/^https?:\/\//i.test(url);
 messageMarkdown.renderer.rules.link_open=(tokens,index,options,env,self)=>{
   tokens[index].attrSet('target','_blank');
   tokens[index].attrSet('rel','noopener noreferrer');
   return self.renderToken(tokens,index,options);
 };
 messageMarkdown.renderer.rules.table_open=()=>'<div class="message-table" tabindex="0" role="region" aria-label="消息表格"><table>';
 messageMarkdown.renderer.rules.table_close=()=>'</table></div>';
}
function messageContent(message){
 if(message.role==='agent'&&messageMarkdown){
   return '<div class="rich-message">'+messageMarkdown.render(String(message.text??''))+'</div>';
 }
 return '<p>'+E(message.text)+'</p>';
}
function transcript(items){
 return items.map(m=>'<div class="msg '+(m.role==='user'?'user':m.role==='event'?'event':'agent')+'">'+(m.role==='agent'?'<span class="avatar">'+mark+'</span>':'')+'<div class="content">'+messageContent(m)+supervisorProposal(m.proposal)+'</div></div>').join('');
}
function composer(hint,context=''){
 const key=page+id, turn=chatTurns.get(key), pending=turn&&!turn.error;
 return '<div class="compose"><form id="send"><textarea name="text" aria-label="消息" maxlength="4000" placeholder="'+E(hint)+'" required'+(pending?' disabled':'')+'>'+E(drafts[key])+'</textarea>'+
 '<div class="compose-footer"><div class="composer-options">'+(context?'<small>'+E(context)+'</small>':'')+
 '</div><button class="primary send" aria-label="发送消息"'+(pending?' disabled':'')+'>↑</button></div></form></div>';
}
function turnPreview(turn){
 if(!turn)return '';
 if(turn.editing)return '<form class="turn-edit" data-form="editChatTurn"><textarea aria-label="编辑消息" name="text" required maxlength="4000">'+E(turn.text)+'</textarea>'+
 '<div class="flex">'+btn('取消','cancelChatEdit')+'<button class="primary">保存并重试</button></div></form>';
 return transcript([{role:'user',text:turn.text}])+
   (turn.error?'<div class="turn-actions"><button type="button" class="quiet" data-act="retryChatTurn" aria-label="重试" title="重试">↻</button>'+
     '<button type="button" class="quiet" data-act="editChatTurn" aria-label="编辑消息" title="编辑消息">✎</button></div>':'')+
   '<p class="chat-send-status" role="status">'+E(turn.error||turn.progress||'研发主管正在回复…')+'</p>';
}
async function runChatTurn(turn){
 const key=turn.page+turn.id, visible=()=>page===turn.page&&id===turn.id;
 const active=()=>chatTurns.get(key)===turn;
 try{
   const request={op:'message',background:true,text:turn.text,request_key:turn.requestKey,
     [turn.page==='聊天'?'thread':'plan']:turn.id};
   let response=await api('/v1/action',request);
   while(response.status==='running'){
     if(active()&&turn.progress!==response.progress){
       turn.progress=response.progress;
       if(visible())render();
     }
     await new Promise(resolve=>setTimeout(resolve,650));
     response=await api('/v1/action',{op:'chat_status',request_key:turn.requestKey});
   }
   if(response.status==='failed'){
     turn.finished=true;
     throw new Error(response.error);
   }
   const result=response.result||response;
   rememberView(turn.page,result.id);
   if(active()){
     chatTurns.delete(key);
     if(visible())id=result.id;
   }
   try{S=await api('/v1/state')}catch{needsRender=true}
   render();
   if(page===turn.page&&id===result.id&&document.activeElement===document.body&&!$('#modal').open)$('#send textarea')?.focus({preventScroll:true});
 }catch(error){
   if(active()){
     turn.error=error.message;
     if(visible())render();
   }
 }finally{saveChatTurns()}
}
function startChatTurn(text,requestKey=crypto.randomUUID()){
 const key=page+id, turn={text,page,id,requestKey};
 chatTurns.set(key,turn);
 delete drafts[key];
 saveChatTurns();
 render();
 const conversation=$('#main .conversation');
 if(conversation)conversation.scrollTop=conversation.scrollHeight;
 return runChatTurn(turn);
}
function chat(){
 const t=get('thread',id);
 const draft=chatTurns.get(page+id);
 if(!t&&!draft)return '<div class="chat-home"><div class="chat-start">'+mark+'<h1>今天想聊什么？</h1>'+
   composer('自由讨论想法、进展或 Skills…')+'</div></div>';
 return head(t?.title||'新聊天')+'<div class="dialogue chat-thread"><div class="conversation"><div class="inner">'+transcript(t?.messages||[])+turnPreview(draft)+'</div></div>'+composer('继续聊天…')+'</div>';
}
function planRow(p){return '<button type="button" class="listrow" data-act="plan" data-key="'+E(p.id)+'"><span class="mono">'+E(p.id.slice(0,7))+'</span><strong>'+E(p.title)+'</strong><small class="projectCol">'+E(get('workspace',p.workspace)?.name||'未关联项目')+'</small>'+label(state(p))+'</button>'}
function metrics(r){return Object.entries(r||{}).map(([k,v])=>E(metricNames[k]||k)+' '+E(v)).join(' · ')}
const configLabel=e=>e.adapter==='name-llm'&&e.config?(e.config.classifier==='multinomial_nb'?'多项式朴素贝叶斯':'余弦质心')+' · 词频 '+e.config.word+' · 字符 '+e.config.char+' · 文体 '+e.config.style+' · '+e.config.grams+'-gram':e.config?(e.config.family==='centroid'?'最近质心':'高斯朴素贝叶斯')+' · 先验权重 '+Number(e.config.prior).toFixed(2)+(e.config.shrinkage!=null?' · 方差收缩 '+Number(e.config.shrinkage).toFixed(2):''):e.k?'k = '+e.k+' · '+(e.scale?'按特征范围缩放':'原始特征'):'平滑强度 '+e.strength;
const shortScore=(e,k)=>Number.isFinite(e.result?.[k])?(metricNames[k]||k)+' '+e.result[k].toFixed(4):'暂无指标';
const delta=e=>Number.isFinite(e.baseline_delta)?' · 较基线 '+(e.baseline_delta>=0?'+':'')+e.baseline_delta.toFixed(4):'';
const phases={scheduled:'等待调度',queued:'等待训练名额',preparing:'编写实验代码',submitting:'提交训练任务',waiting:'等待训练结果',analyzing:'分析实验结果',cooldown:'等待下一轮窗口',training_retry:'等待重试训练',research_decision:'Codex 正在检索历史并作出研究决策',finished:'实验已结束'};
function workerStage(t,job){
 if(t.status==='paused')return '暂停后续调度';
 if(t.status==='failed')return '执行失败';
 if(t.status==='completed')return phases.finished;
 if(t.phase==='research_decision')return phases.research_decision;
 if(t.phase==='training_retry')return phases.training_retry;
 if(job)return job.result?'分析实验结果':['beans','name-llm'].includes(job.adapter)?'本机训练或等待结果':phases.waiting;
 return phases[t.phase]||'等待调度';
}
function analyzeRun(e,t){
 const info=e.assessment||{}, primary=info.primary_metric||t?.constraints?.primary_metric;
 const guard=info.guardrail_metric||t?.constraints?.guardrail_metric||'overall_auc';
 const threshold=info.guardrail_floor??t?.constraints?.overall_auc_floor;
 const primaryResult=shortScore(e,primary)+delta(e);
 const guardEvidence=Number.isFinite(threshold)&&Number.isFinite(e.result?.[guard])
   ?shortScore(e,guard)+'，最低要求 '+threshold.toFixed(4)+'。':'';
 const comparison=Number.isFinite(info.previous_best)?'，此前最佳 '+info.previous_best.toFixed(4):'';
 let conclusion='本轮没有留下可用的比较结论。', expectation='历史记录未保留判定结果。';
 if(e.guardrail_passed===false){
   conclusion='本轮未通过护栏，保留此前的候选。'+guardEvidence;
   expectation='未达到预期。护栏是本计划的最低要求。';
 }else if(e.accepted){
   conclusion=primaryResult+comparison+'。本轮成为待评审候选。';
   expectation='达到本轮验证集的筛选条件。能否推广到保留测试集，需要单独评估。';
 }else if(e.guardrail_passed===true){
   conclusion=primaryResult+comparison+'。本轮通过护栏，但未刷新当前最佳。';
   expectation='部分符合预期。满足护栏，未达到提升目标。';
 }
 return {what:configLabel(e),objective:info.objective||t?.goal,conclusion,expectation};
}
function runAnalysis(e,t,compact=false){
 const a=analyzeRun(e,t);
 const proposal=e.research_proposal, analysis=e.research_analysis;
 return '<div class="run-analysis">'+(proposal?'<p><strong>假设</strong> '+E(proposal.hypothesis)+'</p>'+(proposal.objective_alignment?'<p><strong>与目标的关系</strong> '+E(proposal.objective_alignment)+'</p>':'')+'<p><strong>预期与反证</strong> '+E(proposal.expected)+' · '+E(proposal.disconfirming_result)+'</p><p><strong>选择依据</strong> '+E(proposal.rationale)+(proposal.history_refs.length?' · '+E(proposal.history_refs.join('、')):'')+'</p>':'')+
 (analysis?'<p><strong>Agent 分析</strong> '+E(analysis.observations)+'</p><p><strong>替代解释</strong> '+E(analysis.alternative_explanation)+'</p><p><strong>下一步</strong> '+E(analysis.next_step)+'</p>':'')+(!compact&&a.objective?'<p><strong>研究目标</strong> '+E(a.objective)+'</p>':'')+
 '<p><strong>本轮验证</strong> '+E(a.what)+'</p><p><strong>结论</strong> '+E(a.conclusion)+'</p><p><strong>是否符合预期</strong> '+E(a.expectation)+'</p></div>';
}
function runDiagnostics(e){
 if(!e.diagnostics)return '';
 const elapsed=e.training_ended_at-e.training_started_at;
 return '<p>按 '+E(e.diagnostics.group_key)+' 分组 · 切分种子 '+E(e.diagnostics.split_seed)+
   (Number.isFinite(elapsed)?' · 评测耗时 '+elapsed.toFixed(2)+' 秒':'')+'</p><ul>'+
   Object.entries(e.diagnostics.recalls).map(([name,{correct,total}])=>'<li>'+E(name)+' '+correct+' / '+total+'</li>').join('')+'</ul>';
}
function experiment(e,t){
 return '<article class="rail-result"><div class="flex spread"><strong>第 '+e.round+' 轮</strong>'+label(outcome(e))+'</div>'+runAnalysis(e,t,true)+
 '<details data-detail="'+E(e.id)+'"><summary>指标与复现证据</summary><p>'+metrics(e.result)+'</p>'+runDiagnostics(e)+'<p class="mono">提交 '+E(e.revision)+'<br>报告 '+E(e.report)+(e.run_path?'<br>运行目录 '+E(e.run_path):'')+'</p></details></article>';
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
   out+='<section><h3>恢复执行</h3><p>'+E(t.failure)+'</p>'+(t.failure_info?.log?'<small>日志 '+E(t.failure_info.log)+'</small>':'')+btn('重试执行','retryPlan',true)+'</section>';
 }else if(t.status!=='completed'){
   out+='<section><h3>执行控制</h3>'+
   '<div class="flex">'+btn(t.status==='paused'?'恢复调度':'暂停后续调度',t.status==='paused'?'resume':'pause')+btn('给 Worker 反馈','feedback')+(t.continuous?btn('结束并生成报告','finishLoop'):'')+'</div></section>'+
   '<section><h3>待安排</h3><p>'+(t.continuous?'每轮结束后等待 '+t.interval+' 秒，再自动提出下一轮。':'还有 '+Math.max(0,t.max_experiments-t.round)+' 轮未提交。')+'</p></section>';
 }
 return out;
}
function researchActivity(p){
 const t=task(p);
 if(!t)return '';
 let content=reportCard(p);
 if(!content){
   const job=get('job',t.pending_job);
   const completed=planRuns(p).slice().sort((a,b)=>a.round-b.round);
   const feedback=all('inbox').filter(x=>x.task===t.id&&!['pause','resume'].includes(x.message));
   content=(job?'<p><strong>进行中的实验</strong> · 第 '+t.round+' 轮</p><p>'+E(configLabel(job))+'</p>':'')+
     (completed.length?'<details data-detail="plan-run-history"><summary>逐轮结果与复现信息</summary>'+
       completed.map(e=>experiment(e,t)).join('')+'</details>':'')+
     feedback.map(x=>'<p>'+label(x.consumed?(x.disposition||'已读取'):'已送达')+' '+E(x.message)+'</p>').join('');
 }
 return content?'<div class="msg agent research-update"><span class="avatar">'+mark+'</span><div class="content">'+content+'</div></div>':'';
}

function reportText(r){
 const summaries=r.runs.flatMap(e=>{
   const a=analyzeRun(e,{goal:r.goal,constraints:{primary_metric:r.primary}});
   const p=e.research_proposal, v=e.research_analysis;
   return ['','### 第 '+e.round+' 轮',a.what+'。'+a.conclusion,
     ...(p?['- 假设：'+p.hypothesis,'- 目标关系：'+(p.objective_alignment||r.goal),'- 预期：'+p.expected,'- 反证：'+p.disconfirming_result,
            '- 选择依据：'+p.rationale+'（'+(p.history_refs.join('、')||'初始假设')+'）']:[]),
     ...(v?['- 观察：'+v.observations,'- 替代解释：'+v.alternative_explanation,'- 下一步：'+v.next_step]:[]),
     '- 复现：'+e.revision+' · '+(e.run_path||e.report)];
 });
 return ['# '+r.title,'','## 实验设计',r.goal,'','基线：'+r.baseline+' · 数据：'+r.dataset,'Worker：'+r.agent.name+' v'+r.agent.version,'结论：'+(r.decision||(r.candidate?'有待评审候选':'没有达到采纳条件的候选')),'','## 实验结果',...summaries,...(r.research_summary?['','## 研究结论',r.research_summary.findings,'','## 局限',r.research_summary.limitations,'','## 后续验证',r.research_summary.next_steps]:[]),...(r.holdout?['','## 保留测试集','基线：'+JSON.stringify(r.holdout.baseline),...(r.holdout.candidate?['候选：'+JSON.stringify(r.holdout.candidate)]:[])]:[])].join('\n');
}
function reportCard(p){
 const r=p.report;if(!r)return '';
 const bad=r.runs.filter(e=>e.guardrail_passed===false).length;
 const holdoutBaseline=r.holdout?.baseline?.[r.primary];
 const holdoutCandidate=r.holdout?.candidate?.[r.primary];
 let holdoutConclusion='';
 if(Number.isFinite(holdoutBaseline)&&Number.isFinite(holdoutCandidate)){
   const change=holdoutCandidate-holdoutBaseline;
   holdoutConclusion=change>0?'候选在保留测试集上也高于基线。':
     change<0?'验证集上的提升未在保留测试集复现。':'候选在保留测试集上与基线持平。';
 }
 return '<article class="research-report" aria-label="实验报告"><div class="flex spread"><h2>实验报告</h2></div>'+
 '<p>完成 '+r.runs.length+' / '+r.budget+' 轮 · '+bad+' 轮未通过护栏</p><p>基线：'+E(r.baseline)+(Number.isFinite(r.baseline_value)?' · '+E(metricNames[r.primary]+' '+r.baseline_value.toFixed(4)):'')+'</p>'+
 '<p><strong>'+E(r.candidate?'最佳候选：第 '+r.candidate.round+' 轮 · '+shortScore(r.candidate,r.primary)+delta(r.candidate):'没有超过基线且通过护栏的候选。')+'</strong></p>'+
 (r.research_summary?'<section><h3>研究结论</h3><p>'+E(r.research_summary.findings)+'</p><h3>局限</h3><p>'+E(r.research_summary.limitations)+'</p><h3>后续验证</h3><p>'+E(r.research_summary.next_steps)+'</p></section>':'')+
 '<details><summary>逐轮结果与复现信息</summary>'+r.runs.map(e=>experiment(e,task(p))).join('')+'</details>'+
 (r.holdout?'<p>保留测试集 · 基线：'+metrics(r.holdout.baseline)+(r.holdout.candidate?'<br>候选：'+metrics(r.holdout.candidate):'')+(holdoutConclusion?'<br><strong>'+E(holdoutConclusion)+'</strong>':'')+'</p>':'')+
 (p.decision?'<p>结论：'+E(p.decision)+'</p>':'<div class="flex report-actions">'+(r.candidate?btn('保留候选','decision',true,'保留候选'):'')+btn('不采用','decision',false,'不采用')+'</div>')+
 '<div class="flex report-actions">'+btn('下载报告','downloadReport')+btn('配置 Worker','reportWorker',false,r.agent.id)+btn('从报告创建 Skill','reportSkill',false,r.agent.id)+'</div></article>';
}
function updateRail(){const p=get('plan',id), old=$('.rail');if(!p||!old)return;const y=old.scrollTop, expanded=Array.from(old.querySelectorAll('details'),d=>d.open);old.innerHTML=rail(p);old.querySelectorAll('details').forEach((d,i)=>d.open=!!expanded[i]);old.scrollTop=y}
const researchTabs=active=>tabs(['研究计划','实验记录'],active,'researchTab');
const planGroups=['计划中','进行中','待评审','已暂停','执行失败','已完成'];
function plans(){
 const p=get('plan',id), list=all('plan').slice().reverse(), create=btn('＋ 新研究计划','newPlan',true);
 if(!p){
   if(!list.length)return head('研究计划')+body(researchTabs('研究计划')+empty('还没有研究计划','先写下要验证的方向。可以在创建时选择项目，也可以稍后关联。',create));
   return head('研究计划',create)+body(researchTabs('研究计划')+'<div data-filter-scope><div class="library-bar">'+search('搜索计划、项目或状态')+'</div>'+
   planGroups.filter(k=>list.some(p=>state(p)===k)).map(k=>{const rows=list.filter(p=>state(p)===k);
     return '<details class="plan-group" data-detail="'+E(k)+'" open><summary>'+E(k)+' '+label(rows.length)+'</summary>'+rows.map(p=>'<div data-filter-item>'+planRow(p)+'</div>').join('')+'</details>';
   }).join('')+'<p class="filter-empty" hidden>没有匹配结果。</p></div>');
 }
 const chooser=switcher('切换计划',list.map(x=>[x.id,x.title,(get('workspace',x.workspace)?.name||'未关联项目')+' · '+state(x)]),'plan',id,'','切换研究计划');
 const showing=openPlanStatus.has(p.id);
 const header=navHeading(btn('研究计划','allPlans')+'<span aria-hidden="true">/</span><h1>'+E(p.title)+'</h1>',
 chooser+btn('删除计划','archivePlan')+'<button type="button" class="mobile-status" data-act="togglePlanStatus" aria-controls="plan-status" aria-expanded="'+showing+'">实验状态</button>');
 return header+'<div class="issue research-chat'+(showing?' show-status':'')+'"><div class="dialogue"><div class="conversation" aria-label="研究对话"><div class="inner">'+
 '<details class="chat-context" data-detail="plan-direction"><summary>研究方向</summary><p>'+E(p.direction)+'</p></details>'+
 transcript(p.messages)+researchActivity(p)+turnPreview(chatTurns.get(page+id))+'</div></div>'+composer('回复这项研究…','Enter 发送 · Shift + Enter 换行')+
 '</div><aside id="plan-status" class="rail" aria-label="研究计划状态">'+rail(p)+'</aside></div>';
}
function outcome(e){return e.guardrail_passed===false?'未通过护栏':e.accepted?'通过护栏 · 有改进':'通过护栏 · 未改进'}
function experimentSummary(e,p){
 const t=task(p);
 return '<article class="result-row"><div class="flex spread"><strong>'+E(p.title)+' · 第 '+E(e.round)+' 轮</strong>'+label(outcome(e))+'</div>'+runAnalysis(e,t)+
 '<details data-detail="'+E(e.id)+'"><summary>指标与复现证据</summary><p>'+metrics(e.result)+'</p><p class="mono">代码 '+E(e.revision)+'<br>报告 '+E(e.report)+(e.run_path?'<br>运行目录 '+E(e.run_path):'')+'</p></details>'+btn('打开研究计划','plan',false,p.id)+'</article>';
}
let experimentProject='', experimentOutcome='', experimentLimit=25;
function experimentLibrary(){
 const planByTask=new Map(all('plan').filter(p=>p.task).map(p=>[p.task,p]));
 const matching=all('experiment').filter(e=>{
   const p=planByTask.get(e.task);
   return p&&(!experimentProject||p.workspace===experimentProject)&&(!experimentOutcome||outcome(e)===experimentOutcome);
 }).sort((a,b)=>(b.ready_at||0)-(a.ready_at||0));
 return head('实验库')+body(researchTabs('实验记录')+'<p class="lede">跨项目复查验证内容、结论和证据。</p><div class="flex library-bar">'+
 pick('实验所属项目',[['','全部项目'],...all('workspace').map(w=>[w.id,w.name])],experimentProject)+
 pick('实验结论',[['','全部结论'],...['通过护栏 · 有改进','通过护栏 · 未改进','未通过护栏'].map(x=>[x,x])],experimentOutcome)+'</div>'+
 (matching.length?matching.slice(0,experimentLimit).map(e=>card(experimentSummary(e,planByTask.get(e.task)))).join(''):
 empty('暂无匹配实验','已完成的实验会在这里汇总。'))+
 (matching.length>experimentLimit?btn('显示更多实验','moreExperiments'):''));
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
function projectSidebar(p, plans){
 const imported=['iris','beans','name-llm'].includes(p.adapter);
 const field=(name,value)=>'<dt>'+E(name)+'</dt><dd>'+E(value||'未配置')+'</dd>';
 const source=p.repo&&/^https?:\/\//i.test(p.repo)?
   '<a href="'+E(p.repo)+'" target="_blank" rel="noopener noreferrer">'+E(p.repo)+'</a>':E(p.repo||'未配置');
 const active=plans.filter(plan=>state(plan)==='进行中').length;
 const remoteFields=(modes[p.mode]||[]).map(([key,name])=>field(name,p[key])).join('');
 return '<aside class="rail project-sidebar" aria-label="项目状态与配置"><section><h2>项目状态</h2>'+
   kv('评测环境',imported?'本机真实评测':'模拟评测')+kv('进行中的研究计划',active)+'</section>'+
   '<section><div class="flex spread"><h2>项目配置</h2>'+label('v'+p.version)+'</div>'+
   '<dl>'+field('执行模式',modeNames[p.mode])+
   '<dt>'+(imported?'数据来源':'代码仓库地址')+'</dt><dd>'+source+'</dd>'+
   (imported?field('执行代码','TripSci 内置评测代码'):'')+
   (p.source_repo?field('上游代码仓库',p.source_repo)+field('上游提交',p.source_revision)+field('本机代码目录',p.source_checkout):'')+
   (p.managed_dir?field('TripSci 管理目录',p.managed_dir):'')+field('数据版本',p.dataset)+field('默认基线',p.baseline)+field('训练入口',p.train)+field('评测入口',p.evaluate)+
   (Number.isFinite(p.floor)?field(imported?'准确率护栏':'AUC 护栏',String(p.floor)):'')+remoteFields+'</dl>'+
   (imported?'<p class="muted">此项目使用固定的导入数据和评测协议。</p>':btn('编辑配置','editProject'))+btn('删除项目','archiveProject')+'</section></aside>';
}
function projects(){
 const p=get('workspace',id), actions=btn('＋ 新建项目','newProject',true);
 if(!all('workspace').length)return head('项目')+body('<section class="guide guide-single"><div class="guide-copy">'+
 title('从第一个研究项目开始','填写项目的代码、数据和评测配置，再创建第一项研究。')+actions+'</div></section>');
 if(!p)return head('项目',actions)+body('<div data-filter-scope><div class="library-bar flex spread">' +search('搜索项目')+'</div>'+all('workspace').map(w=>{
   const plans=all('plan').filter(q=>q.workspace===w.id), ids=new Set(plans.map(q=>q.task));
   const runs=all('experiment').filter(e=>ids.has(e.task));
   return '<button type="button" class="study-row project-row" data-filter-item data-act="project" data-key="'+E(w.id)+'"><span class="project-cell">'+projectIcon()+'<span><strong>'+E(w.name)+'</strong><small>'+E(modeNames[w.mode])+' · '+E(w.dataset)+'</small></span></span><small>'+plans.length+' 项研究 · '+runs.length+' 轮实验</small><span aria-hidden="true">›</span></button>';
 }).join('')+'<p class="filter-empty" hidden>没有匹配项目。</p></div>');
 const ps=all('plan').filter(x=>x.workspace===p.id), byTask=new Map(ps.filter(x=>x.task).map(x=>[x.task,x]));
 const ex=all('experiment').filter(x=>byTask.has(x.task)).sort((a,b)=>(b.ready_at||0)-(a.ready_at||0));
 const filter=resultFilters[p.id]||'全部', shown=ex.filter(e=>filter==='全部'||(filter==='有改进'?e.accepted:filter==='未通过护栏'?e.guardrail_passed===false:e.guardrail_passed!==false&&!e.accepted));
 return navHeading(btn('项目列表','nav',false,'项目')+'<span aria-hidden="true">/</span>'+switcher(p.name,all('workspace').map(w=>[w.id,w.name,modeNames[w.mode]]),'project',p.id,'','切换项目'),btn('＋ 新研究计划','newPlan',true))+'<div class="project-dashboard">'+projectSidebar(p,ps)+body('<p class="lede">项目看板 · '+(p.adapter!=='mock'?'真实评测':'模拟评测')+'</p>'+
 '<div class="dash-stats">'+card('<small>研究计划</small><strong>'+ps.length+'</strong>')+card('<small>有改进的实验</small><strong>'+ex.filter(e=>e.accepted).length+'</strong>')+card('<small>未通过护栏</small><strong>'+ex.filter(e=>e.guardrail_passed===false).length+'</strong>')+'</div>'+
 card('<h3>研究概览</h3>'+(ps.map(q=>{const runs=planRuns(q);return '<button type="button" class="study-row" data-act="plan" data-key="'+E(q.id)+'"><span><strong>'+E(q.title)+'</strong><small>'+E(q.direction)+'</small></span><small>'+runs.length+' 轮 · '+runs.filter(r=>r.accepted).length+' 轮有改进</small>'+label(state(q))+'</button>'}).join('')||'<p class="muted">此项目还没有研究计划。可以从右上角创建。</p>'))+
 trend(p)+card('<h3>实验结果 <small>（'+ex.length+'）</small></h3>'+(ex.length?tabs(['全部','有改进','未改进','未通过护栏'],filter,'resultFilter')+(shown.map(e=>experimentSummary(e,byTask.get(e.task))).join('')||'<p class="muted">当前筛选没有结果。</p>'):'<p class="muted">首轮评测完成后，这里会显示方案、指标和结论。</p>')))+'</div>';
}
function library(){return [...all('tool').map(t=>({...t,description:t.kind==='link'?'打开研究文档或外部服务。':'保存常用命令供查看。'})),...all('skill').map(x=>({...x,kind:'skill',description:x.markdown.trim().split(/\r?\n/).find(line=>line.trim()&&!line.startsWith('#'))?.slice(0,110)||'可分配给智能体的 Markdown 指南。'}))]}
const kinds={link:'网页链接',command:'命令参考',skill:'Skill'};
function toolCard(t){return '<button class="tool-tile" type="button" data-filter-item data-act="toolDetail" data-key="'+E(t.id)+'"><span class="tool-icon" aria-hidden="true">'+({link:'↗',command:'›_',skill:'◇'})[t.kind]+'</span><strong>'+E(t.name)+'</strong><small>'+E(t.description)+'</small>'+label(kinds[t.kind])+'</button>'}
function tools(){
 const items=library(), t=items.find(x=>x.id===id);
 if(t)return navHeading(btn('工具','nav',false,'工具')+'<span aria-hidden="true">/</span><h1>'+E(t.name)+'</h1>')+body('<div class="detail-intro">'+label(kinds[t.kind])+'<p class="lede">'+E(t.description)+'</p></div>'+
 card(t.kind==='skill'?'<h3>SKILL.md</h3><pre>'+E(t.markdown)+'</pre>'+btn('管理智能体分配','nav',false,'智能体'):t.kind==='link'?'<h3>链接</h3><a target="_blank" rel="noopener noreferrer" href="'+E(t.target)+'">'+E(t.target)+'</a>':'<h3>命令参考</h3><pre>'+E(t.target)+'</pre><small>仅供查看，TripSci 不会执行。</small>'));
 const skills=toolTab==='Skills';
 const shown=items.filter(x=>skills?x.kind==='skill':['link','command'].includes(x.kind));
 const add=skills?btn('＋ 新建 Skill','newSkill',true):btn('＋ 添加工具','newTool',true);
 return head('工具',add)+body(tabs(['我的工具','Skills'],toolTab,'toolTab')+
 '<div data-filter-scope>'+(shown.length?'<div class="library-bar">'+search(skills?'搜索 Skills':'搜索链接或命令')+'</div><div class="tile-grid">'+shown.map(toolCard).join('')+'</div>':skills?
 empty('还没有自定义 Skill','创建后可以分配给一个或多个智能体。'):
 empty('还没有保存链接或命令','把常用研究文档和命令参考集中到这里。'))+
 '<p class="filter-empty" hidden>没有匹配结果。</p></div>');
}
function agentSkills(a){
 const names={'adaptive-ctr':'自适应实验策略','wide-search':'扩大搜索范围'};
 const chosen=a.skills.map(k=>[k,get('skill',k)?.name||names[k]||k]);
 const supervisor=a.role==='supervisor';
 const candidates=[...(supervisor?[]:[['wide-search',names['wide-search']]]),...all('skill').map(x=>[x.id,x.name])].filter(([k])=>!a.skills.includes(k));
 return card('<div class="flex spread"><h3>已分配 Skills</h3>'+btn('＋ 创建并分配 Skill','agentSkill',false,a.id)+'</div><p class="muted">'+(supervisor?'已分配的 Skills 会在下一次主管回复时加载。':'自定义 Skill 会随新计划保存。目前内置 Worker 只执行内置策略。')+'</p>'+(chosen.length?chosen.map(([k,n])=>'<div class="catalog-row"><strong>'+E(n)+'</strong>'+ (k==='adaptive-ctr'?label('内置默认'):btn('移除','removeSkill',false,k))+'</div>').join(''):'<p class="muted">还没有分配 Skill。</p>')+
 (candidates.length?'<form data-form="assignSkill" class="flex inline-form">'+pick('skill',candidates)+'<button class="primary">分配已有 Skill</button></form>':'<p class="muted">所有可用 Skills 已分配。</p>'));
}
const proposalRestrictions={
 projects:'项目配置提案',research:'研究计划与调度提案',configuration:'Skills、智能体与设置提案'
};
function agentTools(a){
 if(a.role!=='supervisor')return card('<h3>工具</h3><p>当前运行时没有可独立配置的工具。执行范围由项目和研究计划确定。</p>');
 return card('<h3>网页搜索</h3><p class="muted">让 Codex 搜索公开资料。工作区变更会在对话中单独确认。</p>'+
 '<form class="fields inline-form" data-form="agentPermissions" data-key="'+E(a.id)+'" data-retain>'+
 '<label><input type="checkbox" name="web_search" '+(a.permissions.web_search?'checked':'')+'> 启用网页搜索</label>'+
 '<p class="submit-error" role="alert"></p><button class="primary">保存工具设置</button></form>');
}
function proposalPolicy(){
 const a=all('agent').find(x=>x.role==='supervisor');
 if(!a)return '';
 const toggles=Object.entries(proposalRestrictions).map(([key,name])=>
   '<label><input type="checkbox" name="'+key+'" '+(a.permissions[key]?'checked':'')+'> 允许'+E(name)+'</label>').join('');
 return card('<details class="proposal-policy"><summary>研发主管提案限制</summary><p class="muted">以下是工作区级限制。允许提出的变更仍须在对话中逐项确认。</p>'+
   '<form class="fields inline-form" data-form="agentPermissions" data-key="'+E(a.id)+'" data-retain>'+toggles+
   '<p class="submit-error" role="alert"></p><button class="primary">保存提案限制</button></form></details>');
}
function agents(){
 const a=get('agent',id), newAgent=btn('＋ 新建智能体','newAgent',true), list=all('agent');
 if(!a)return head('智能体',newAgent)+body(tabs(['已配置','本机运行时'],agentTab==='本机运行时'?'本机运行时':'已配置','agentTab')+
 (agentTab==='本机运行时'?card('<div class="flex spread"><p class="muted">检测这台电脑上的外部执行工具。</p>'+btn('重新检测','scanRuntimes')+'</div>'+externalRuntimes().map(r=>'<div class="catalog-row"><div><strong>'+E(r.name)+'</strong><br><small>本机</small></div>'+label(runtimeStatus(r))+(r.installed?btn('配置智能体','chooseAgent',false,r.id):'')+'</div>').join('')):
 '<div data-filter-scope><div class="library-bar">'+search('搜索智能体或运行时')+'</div>'+(list.length?list.map(x=>'<button type="button" class="catalog-row clickable" data-filter-item data-act="agent" data-key="'+E(x.id)+'"><span class="role-icon" aria-hidden="true">◇</span><span><strong>'+E(x.name)+'</strong><br><small>'+E(x.role==='supervisor'?'工作区与研究对话 · Codex':runtimeName(x.runtime)+' · 本机')+'</small></span>'+label(x.role==='supervisor'?supervisorStatus(x):runtimeStatus(all('runtimes').find(r=>r.id===x.runtime)))+'<span aria-hidden="true">›</span></button>').join(''):empty('还没有智能体','从本机检测到的运行时创建研究角色。'))+'<p class="filter-empty" hidden>没有匹配的智能体。</p></div>'));
 const supervisor=a.role==='supervisor', r=all('runtimes').find(x=>x.id===a.runtime);
 const views=['概览','指令','Skills','运行设置','工具'];
 const instructions=()=>card('<h3>AGENTS.md</h3>'+(supervisor?
   '<p class="muted">TripSci 内置角色指令。</p><pre>'+E(a.instructions)+'</pre>':
   '<p class="muted">这份 Markdown 属于当前智能体。</p><form class="fields inline-form" data-form="agentInstructions" data-retain>'+area('instructions','Markdown 指令',a.instructions)+'<button class="primary">保存指令</button></form>'));
 const overview=()=>supervisor?
   card('<h3>职责</h3><p>负责项目配置提案、研究方向、Worker 委派与反馈，以及 Skill 和配置管理。</p>'+kv('对话入口','工作区聊天、研究计划对话')):
   card('<div class="flex spread"><h3>角色配置</h3>'+btn('编辑名称','renameAgent')+'</div>'+kv('配置版本','v'+a.version)+kv('已分配 Skills',a.skills.length));
 const content={
   概览:overview,
   指令:instructions,
   Skills:()=>agentSkills(a),
   运行设置:()=>card('<h3>运行时</h3>'+kv('机器','本机')+kv('运行时',runtimeName(a.runtime))+
     kv('状态',supervisor?supervisorStatus(a):runtimeStatus(r))+
     (supervisor?'<p class="muted">对话需要本机 Codex 登录和网络连接。</p>':r?.executable?'':'<p class="muted">当前可保存配置，外部运行时尚未接入实验调度。</p>')),
   工具:()=>agentTools(a)
 };
 return navHeading(btn('智能体','nav',false,'智能体')+'<span aria-hidden="true">/</span><h1>'+E(a.name)+'</h1>')+
   body((returnPlan?btn('← 返回实验报告','plan',false,returnPlan):'')+tabs(views,agentTab,'agentTab')+content[agentTab]());
}
function settings(){return head('设置')+body(card('<h2 class="section-heading">模拟训练</h2><form class="fields" data-form="settings">'+input('delay','每轮模拟训练秒数',S.settings.delay,'number')+input('slots','训练并发上限',S.settings.slots||2,'number')+'<button class="primary">保存设置</button></form>')+proposalPolicy())}
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
 const side=$('#side'), oldNav=side.querySelector('.workspace-nav')?.scrollTop||0;
 const sidebarHtml=sidebar();
 if(sidebarHtml!==side._view){
   const focused=document.activeElement?.closest('.recent-items button');
   side.innerHTML=sidebarHtml;
   side._view=sidebarHtml;
   side.querySelector('.workspace-nav').scrollTop=oldNav;
   if(focused){
     const replacement=[...side.querySelectorAll('.recent-items button')].find(button=>
       button.dataset.act===focused.dataset.act&&button.dataset.key===focused.dataset.key);
     replacement?.focus({preventScroll:true});
   }
 }
 if(!S){$('#main').innerHTML='<div class="loading">正在连接研究服务…</div>';return}
 const view=page+':'+id, same=renderedView===view;
 const html=({聊天:chat,研究计划:plans,项目:projects,智能体:agents,工具:tools,设置:settings,实验库:experimentLibrary})[page]();
 const main=$('#main');
 if(!same||html!==main._view){
   const saved={}, expanded=new Set(), groups=new Set([...main.querySelectorAll('.plan-group')].map(d=>d.dataset.detail));
   if(same){
     for(const key of ['.body','.conversation','.rail','.project-dashboard']){
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
   for(const key of ['.body','.conversation','.rail','.project-dashboard']){
     const el=main.querySelector(key), prior=saved[key];
     if(el&&(prior||key==='.conversation'))el.scrollTop=key==='.conversation'&&(!prior||prior[1])?el.scrollHeight:prior[0];
   }
 }
 quickChat();
}
function modal(title,kind,fields,submit){
 const m=$('#modal');m.innerHTML='<h2>'+E(title)+'</h2><form class="fields" data-form="'+kind+'">'+fields+'<p class="submit-error" role="alert"></p><div class="flex">'+btn('取消','close')+'<button class="primary">'+E(submit)+'</button></div></form>';if(!m.open)m.showModal();
}
function projectForm(p={},attach=false){
 const fields=[['name','项目名称'],['repo','代码地址'],['baseline','默认基线'],['dataset','数据版本'],['train','训练入口'],['evaluate','评测入口']];
 modal(p.id?'编辑项目配置':'初始化研究项目','workspace','<p class="muted">保存后，TripSci 会在自己的项目存储中保存配置。三种模式目前均使用本机模拟训练。</p>'+
 fields.map(([k,t])=>input(k,t,p[k])).join('')+input('floor','整体 AUC 下限',p.floor??.715,'number')+
 '<label>执行模式'+pick('mode',Object.entries(modeNames),p.mode||'local')+'</label><div id="modeFields"></div>'+
 '<input type="hidden" name="id" value="'+E(p.id)+'"><input type="hidden" name="attach" value="'+(attach?'yes':'')+'">'+btn('检查配置','check'),'保存项目');
 modeFields(p.mode||'local',p);
}
function modeFields(mode,p={}){$('#modeFields').innerHTML=modes[mode].map(([k,t])=>input(k,t,p[k])).join('')}
function planForm(){
 const workspace=page==='项目'?get('workspace',id)?.id:'';
 modal('新研究计划','plan',
   '<div class="plan-create">'+input('title','标题')+area('direction','大致方向')+
   '<div class="plan-create-properties"><label>所属项目'+pick('workspace',[['','暂不关联'],...all('workspace').map(w=>[w.id,w.name])],workspace)+'</label>'+
   '<span class="pill">计划中</span></div></div>',
   '创建并打开');
 $('#modal input[name=title]').focus();
}
function agentForm(a={},runtime=a.runtime||'local-process'){modal(a.id?'编辑智能体':'创建智能体 · 2 / 2','agent','<p>运行时：'+E(runtimeName(runtime))+'</p><input type="hidden" name="runtime" value="'+E(runtime)+'">'+input('name','名称',a.name)+area('instructions','Markdown 指令',a.instructions||'比较实验结果，遵守护栏。')+'<label><input type="checkbox" name="wide" '+(a.skills?.includes('wide-search')?'checked':'')+'> 启用 wide-search</label>'+all('skill').map(x=>'<label><input type="checkbox" name="skill" value="'+E(x.id)+'" '+(a.skills?.includes(x.id)?'checked':'')+'> '+E(x.name)+'</label>').join('')+'<input type="hidden" name="id" value="'+E(a.id)+'">','保存配置')}
const payload=f=>Object.fromEntries(new FormData(f));
const close=()=>$('#modal').close();
function saveAgent(a,patch){return act({op:'agent',id:a.id,name:a.name,runtime:a.runtime,instructions:a.instructions,skills:a.skills,...patch},close)}
document.addEventListener('click',e=>{for(const d of document.querySelectorAll('.switcher[open]'))if(!d.contains(e.target))d.open=false});
document.addEventListener('keydown',e=>{if(e.key==='Escape'){if($('#quick-panel')&&!$('#quick-panel').hidden&&e.target.closest('#quick-chat')){e.target.blur();$('.quick-toggle').click();$('.quick-toggle').focus();return}const d=$('.switcher[open]');if(d){d.open=false;d.querySelector('summary').focus()}}});
document.addEventListener('toggle',e=>{if(e.target.matches('.switcher[open]'))e.target.querySelector('[data-search]')?.focus()},true);
document.addEventListener('click',e=>{
 const b=e.target.closest('[data-act]');if(!b)return;const {act:a,key:k}=b.dataset;
 if(a==='quickToggle'){
   const panel=$('#quick-panel');panel.hidden=!panel.hidden;
   $('.quick-toggle').setAttribute('aria-expanded',String(!panel.hidden));
   if(!panel.hidden){const log=$('.quick-log');log.scrollTop=log.scrollHeight;$('#quick-send textarea').focus();}
   return;
 }
 if(a==='quickFull'){if(!$('#quick-panel').hidden){$('#quick-panel').hidden=true;$('.quick-toggle').setAttribute('aria-expanded','false')}return nav('聊天',quickThread)}
 if(a==='retryChatTurn'||a==='editChatTurn'||a==='cancelChatEdit'){
   const turn=chatTurns.get(page+id);
   if(!turn?.error)return;
   if(a==='retryChatTurn')return startChatTurn(turn.text,turn.finished?undefined:turn.requestKey);
   turn.editing=a==='editChatTurn';saveChatTurns();render();
   if(turn.editing)$('#main .turn-edit textarea')?.focus();
   return;
 }
 if(a==='newChat'){if(chatTurns.delete('聊天')){delete drafts['聊天'];saveChatTurns()}return nav('聊天')}
 if(a==='cancelSupervisor')return act({op:'cancel_supervisor',proposal_id:k},()=>notice('主管提案已取消'));
 if(a==='confirmSupervisor')return act({op:'confirm_supervisor',proposal_id:k},()=>notice('主管提案已执行'));
 if(a==='retry')return load();
 if(a==='retryPlan')return act({op:'retry',id});
 if(a==='nav')return nav(k);
 if(a==='researchTab')return nav(k==='实验记录'?'实验库':'研究计划');
 if(a==='moreExperiments'){experimentLimit+=25;return render()}
 if(a==='toggleProjects'){projectsExpanded=!projectsExpanded;return render()}
 if(a==='chat')return nav('聊天',k,!!b.closest('.recent-items'));
 if(a==='plan')return nav('研究计划',k,!!b.closest('.recent-items'));
 if(a==='togglePlanStatus'){if(openPlanStatus.has(id))openPlanStatus.delete(id);else openPlanStatus.add(id);return render()}
 if(a==='resultFilter'){resultFilters[current().id]=k;return render()}
 if(a==='reportWorker'){const plan=id;nav('智能体',k);returnPlan=plan;agentTab='Skills';return render()}
 if(a==='reportSkill'||a==='agentSkill'){
   const p=a==='reportSkill'?get('plan',id):null, target=get('agent',k);if(!target)return;
   const template=p?'# 实验评审规范\n\n参考「'+p.title+'」的实验报告。\n\n- 明确假设、对照基线和主要指标。\n- 固定数据划分与评测入口。\n- 记录未通过护栏或没有改进的实验，以及下一步。':'# 实验规范\n\n- ';
   return modal('为 '+target.name+' 创建 Skill','createAssignedSkill','<p>保存后分配给当前智能体，下次运行时生效。</p>'+input('name','名称',p?'实验评审规范':'')+area('markdown','Skill Markdown',template)+'<input type="hidden" name="agent" value="'+E(k)+'">','保存并分配');
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
 if(a==='removeSkill'){const x=get('agent',id);return act({op:'agent_skills',id:x.id,skills:x.skills.filter(v=>v!==k)})}
 if(a==='agent')return nav('智能体',k);
 if(a==='close')return close();
 if(a==='newProject'||a==='projectForPlan')return projectForm({},a==='projectForPlan');
 if(a==='archiveProject'||a==='archivePlan'){
   const projectRemoval=a==='archiveProject';
   const target=get(projectRemoval?'workspace':'plan',id);
   const note=projectRemoval?'此项目及所属研究计划会从工作区移除。':'此研究计划会从工作区和项目看板移除。';
   return modal(projectRemoval?'删除项目':'删除研究计划',projectRemoval?'archive_workspace':'archive_plan',
     '<p><strong>'+E(target.name||target.title)+'</strong></p><p>'+note+'代码、数据和实验文件会保留。</p>','确认删除');
 }
 if(a==='editProject')return projectForm(current());
 if(a==='newPlan')return planForm();
 if(a==='recordIntegration')return integrationForm();
 if(a==='newAgent')return modal('创建智能体 · 1 / 2','chooseRuntime','<h3>在哪里运行？</h3><p class="muted">选择内置执行器或已检测到的外部运行时。</p>'+all('runtimes').filter(r=>r.installed).map((r,i)=>'<label class="runtime-choice"><input name="runtime" type="radio" value="'+E(r.id)+'" '+(!i?'checked':'')+' required><span><strong>'+E(runtimeName(r.id))+'</strong><br><small>'+E(runtimeStatus(r))+'</small></span></label>').join(''),'继续');
 if(a==='editAgent')return agentForm(get('agent',id));
 if(a==='finishLoop')return modal('结束持续迭代','finish','<p>已提交的实验会完成，再生成报告。不会再启动下一轮。</p>','确认结束');
 if(a==='newTool')return modal('添加工具','chooseTool','<p>选择要添加到工作区的工具类型。</p>'+pick('kind',[['link','网页链接'],['command','命令参考']]),'继续');
 if(a==='newSkill')return modal('新建 Skill','skill',input('name','名称')+area('markdown','Skill Markdown'),'保存');

 if(a==='attach')return modal('关联项目','attach',all('workspace').length?'<label>项目'+pick('workspace',all('workspace').map(x=>[x.id,x.name]),get('plan',id)?.workspace)+'</label>':'<p>还没有项目。</p>'+btn('新建项目','projectForPlan'),'关联');
 if(a==='start'){
   const p=get('plan',id),env=get('workspace',p?.workspace);if(!env)return;
   const bean=env.adapter==='beans', ntl=env.adapter==='name-llm', real=bean||ntl||env.adapter==='iris';
   const extra=ntl?'<label>研究策略'+pick('strategy',[['char','字符 n-gram'],['style','文体与标点'],['adaptive','自由迭代']])+'</label>':bean?'<label>研究策略'+pick('strategy',[['centroid','质心与特征消融'],['bayes','高斯朴素贝叶斯'],['adaptive','自适应特征权重']])+'</label><label>运行方式'+pick('run_mode',[['bounded','固定轮次'],['continuous','持续迭代（自适应策略）']])+'</label><div id="loopInterval" hidden>'+input('interval','轮次间隔（秒）',30,'number')+'</div>':'';
   const research=ntl?'<label>研究决策'+pick('research_mode',[['codex','Codex 自主研究 · 根据目标和证据选择下一轮'],['rules','内置策略 · 固定扫描或参数搜索']])+'</label>':!real&&env.mode==='local'?'<label>研究决策'+pick('research_mode',[['rules','内置规则'],['codex','Codex 研究决策（模拟评测）']])+'</label>':'';
   return modal('确认并启动实验','start','<p>'+E(env.name)+' · '+E(modeNames[env.mode])+(real?' · 真实数据</p>':' · 模拟</p>')+kv('数据',env.dataset)+kv(real?'准确率下限':'整体 AUC 下限',env.floor)+(real?kv('固定基线',env.baseline):input('baseline','对照基线',env.baseline))+area('design','已确认的实验设计',p.direction)+research+(ntl?'<div id="rule-strategy" hidden>'+extra+'</div>':extra)+'<div id="roundBudget">'+input('budget','实验预算（1–10）',ntl?4:3,'number')+'</div><label>执行者'+pick('agent',all('agent').filter(x=>x.role!=='supervisor'&&(x.runtime==='local-process'||((env.mode==='local'&&(ntl||!real))&&x.runtime==='codex'))).map(x=>[x.id,x.name+' · v'+x.version]))+'</label>',real?'启动本机评测':'启动模拟研究');
 }
 if(a==='feedback')return modal('给 Worker 反馈','feedback','<p>当前训练继续。可发送「保守」或「强度 0.55」来改变下一轮。</p>'+area('text','反馈'),'发送反馈');
 if(a==='check'){
   const f=$('#modal form');if(!f.reportValidity())return;
   const d=payload(f);act({...d,op:'check',floor:Number(d.floor)},r=>{const el=$('#modal .submit-error');if(el)el.textContent=r.message});return;
 }
 if(['pause','resume','decision'].includes(a))act({op:a,id,value:k});
});
document.addEventListener('change',e=>{

 if(e.target.name==='实验所属项目'||e.target.name==='实验结论'){
   if(e.target.name==='实验所属项目')experimentProject=e.target.value;else experimentOutcome=e.target.value;
   experimentLimit=25;return render();
 }
 if(e.target.name==='趋势指标'){chartChoices[current().id]=e.target.value;render()}
 if(e.target.name==='strategy'&&get('workspace',get('plan',id)?.workspace)?.adapter==='name-llm')$('#roundBudget input').value=e.target.value==='adaptive'?20:4;
 if(e.target.name==='agent'&&e.target.closest('form')?.dataset.form==='start'){
   const mode=$('#modal select[name=research_mode]');
   if(mode&&get('agent',e.target.value)?.runtime==='codex'){mode.value='codex';mode.dispatchEvent(new Event('change',{bubbles:true}))}
 }
 if(e.target.name==='research_mode'&&$('#rule-strategy'))$('#rule-strategy').hidden=e.target.value==='codex';
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
async function sendChat(form, payload, done){
 const submit=form.querySelector('button[type="submit"], button:not([type])');
 let status=form.querySelector('.chat-send-status');
 if(!status){
   status=document.createElement('small');
   status.className='chat-send-status';
   status.setAttribute('role','status');
   form.append(status);
 }
 status.textContent='研发主管正在回复…';
 if(submit)submit.disabled=true;
 try{
   await act(payload,row=>{status.textContent='';done(row)},message=>{status.textContent=message});
 }finally{
   if(submit)submit.disabled=false;
 }
}
document.addEventListener('submit',async e=>{
 const f=e.target, op=f.getAttribute('data-form'), send=f.getAttribute('id')==='send';
 if(f.id==='quick-send'){
   e.preventDefault();
   const field=f.querySelector('textarea'), text=field.value.trim();
   if(!text||busy)return;
   return sendChat(f,{op:'message',text,thread:quickThread},r=>{quickThread=r.id;sessionStorage.setItem('tripsci-quick-thread',r.id);if(field.value.trim()===text)field.value=''});
 }
 if(!send&&!op)return;e.preventDefault();if(busy)return;
 const d=payload(f);
 if(send){
   const text=d.text.trim(), turn=chatTurns.get(page+id);
   if(text&&(!turn||turn.error))return startChatTurn(text);
   return;
 }
 if(op==='editChatTurn'){
   const turn=chatTurns.get(page+id), text=d.text.trim();
   if(text&&turn?.error)return startChatTurn(text,text===turn.text&&!turn.finished?turn.requestKey:undefined);
   return;
 }
 if(op==='archive_workspace'||op==='archive_plan')return act({op,id},()=>{
   close();
   if(op==='archive_workspace'&&project===id)project='';
   nav(op==='archive_workspace'?'项目':'研究计划');
   notice('已从工作区移除');
 });
 if(op==='workspace'){
   const attach=d.attach==='yes', plan=id;delete d.attach;
   return act({...d,op,attach_plan:attach?plan:'',floor:Number(d.floor)},r=>{close();project=r.id;if(!attach){page='项目';id=r.id;rememberView(page,id)}});
 }
 if(op==='noIntegration')return close();
 if(op==='integration'){
   const p=current(), plans=new FormData(f).getAll('sourcePlan');
   return act({op,workspace:p.id,plans,revision:d.revision,summary:d.summary,metrics:Object.fromEntries(projectMetrics(p).map(k=>[k,Number(d[k])]))},close);
 }
 if(op==='plan'){
   return act({...d,op},r=>{
     close();
     nav('研究计划',r.id);
     $('#send textarea')?.focus({preventScroll:true});
   });
 }
 if(op==='chooseRuntime')return agentForm({},d.runtime);
 if(op==='chooseTool'){
   const name=kinds[d.kind];return modal('添加'+name,'tool',input('name','名称')+input('target',d.kind==='link'?'链接地址':'命令',undefined,d.kind==='link'?'url':'text')+'<input type="hidden" name="kind" value="'+E(d.kind)+'">','保存');
 }
 if(op==='createAssignedSkill')return act({...d,op:'skill'},()=>{close();notice('已保存并分配')});
 if(op==='tool'||op==='skill')return act({...d,op},r=>{close();id=r.id;toolTab=op==='skill'?'Skills':'我的工具'});
 if(op==='assignSkill'){const x=get('agent',id);return act({op:'agent_skills',id:x.id,skills:[...new Set([...x.skills,d.skill])]})}
 if(op==='agentPermissions'){
   const permissions=Object.fromEntries(Array.from(f.querySelectorAll('input[type=checkbox]'),field=>[field.name,field.checked]));
   return act({op:'agent_permissions',id:f.dataset.key,permissions},()=>notice('设置已保存'),message=>{f.querySelector('.submit-error').textContent=message});
 }
 if(op==='agentInstructions'||op==='renameAgent')return saveAgent(get('agent',id),d);
 if(op==='agent')return act({...d,op,skills:['adaptive-ctr',...(d.wide?['wide-search']:[]),...new FormData(f).getAll('skill')]},r=>{close();id=r.id;agentTab='概览';notice('智能体配置已保存')});
 if(op==='settings')return act({op,delay:Number(d.delay),slots:Number(d.slots)},()=>notice('已保存设置'));
 if(op==='attach'&&!d.workspace)return notice('请先新建项目');
 if(op==='start'){d.budget=Number(d.budget);if(d.interval!=null)d.interval=Number(d.interval)}
 act({...d,op,id},close);
});
render();load();setInterval(load,850);

for(const turn of chatTurns.values())if(!turn.error)runChatTurn(turn);
