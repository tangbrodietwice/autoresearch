"""Workspace commands: plans."""
from .common import uid
from research.planner import SKILL as SCIENTIFIC_SKILL
from legacy.benchmarks import beans
import copy
from legacy.benchmarks import iris
from legacy.benchmarks import name_llm
from execution import PROVIDERS


def start_batch(self, db, d):
    rows = d.get("plans")
    if not isinstance(rows,list) or not 2<=len(rows)<=8 or any(not isinstance(row,dict) for row in rows):
        raise ValueError("每次批量启动需提供 2–8 个研究计划。")
    keys = [self.string(row,"id",required=True) for row in rows]
    if len(set(keys)) != len(keys):
        raise ValueError("不能重复启动同一个研究计划。")
    return {"plans":[self.action(db,{**row,"op":"start"}) for row in rows]}


def plan(self, db, d):
    def s(key, default="", required=False):
        return self.string(d, key, default, required)

    key=s("workspace")
    if key: self.get(db,"workspace",key)
    source=s("source")
    messages=[]
    if source:
        thread=self.get(db,"thread",source)
        messages.append({"role":"event","text":"来源聊天："+thread["title"]})
    return self.put(db,"plan",{"id":uid(),"title":s("title",required=True),"direction":s("direction",required=True),
                               "workspace":key,"source":source,"task":"","messages":messages,"decision":""})


def control(self, db, d):
    op = d["op"]
    def s(key, default="", required=False):
        return self.string(d, key, default, required)

    if op not in ("attach","start","feedback","pause","resume","retry","finish","decision"):
        raise ValueError("未知操作。")
    plan=self.get(db,"plan",s("id"))
    if op=="attach":
        if plan["task"]: raise ValueError("已启动的计划不能更换项目。")
        key=s("workspace",required=True)
        self.get(db,"workspace",key)
        plan["workspace"]=key
    elif op=="start":
        if plan["task"]: raise ValueError("计划已启动。")
        env=self.get(db,"workspace",plan["workspace"])
        agent=self.p.get(db,"agent",s("agent","worker"))
        if not agent: raise ValueError("请选择执行智能体。")
        if agent.get("role") == "supervisor":
            raise ValueError("请选择研究 Worker，研发主管负责讨论与分派。")
        if agent["runtime"] not in ("local-process", "codex"):
            raise ValueError("此 Provider 当前仅检测与配置，尚未接入研究执行。")
        if env.get("adapter") == "local-project":
            return start_local_project(self, db, d, plan, env, agent)
        research_mode=s("research_mode","rules")
        if research_mode not in ("rules","codex"):
            raise ValueError("未知研究决策模式。")
        if agent["runtime"] == "codex" and research_mode != "codex":
            raise ValueError("Codex Worker 需要选择自主研究决策。")
        if research_mode=="codex" and (env.get("adapter") not in ("mock", "name-llm") or env.get("mode")!="local" or not PROVIDERS["codex"].detect()):
            raise ValueError("Codex 自主研究需要本机 Codex CLI，并支持本机模拟评测和 Name That LLM。")
        run_mode = d.get("run_mode", "bounded")
        if run_mode not in ("bounded", "continuous"):
            raise ValueError("未知实验运行模式。")
        continuous = run_mode == "continuous"
        strategy=s("strategy","adaptive")
        interval=d.get("interval",30)
        ntl=env.get("adapter")=="name-llm"
        if ntl and strategy not in name_llm.STRATEGIES:
            raise ValueError("请选择 Name That LLM 实验策略。")
        if env.get("adapter")=="beans" and strategy not in beans.STRATEGIES:
            raise ValueError("请选择 Dry Bean 实验策略。")
        if continuous and (env.get("adapter")!="beans" or strategy!="adaptive" or type(interval) is not int or not 2<=interval<=3600):
            raise ValueError("持续迭代仅支持 Dry Bean 自适应策略，间隔 2–3600 秒。")
        budget=1 if continuous else d.get("budget")
        cap=20 if ntl and research_mode=="rules" else 10
        if type(budget) is not int or not 1<=budget<=cap: raise ValueError(f"预算必须为 1–{cap} 轮。")
        key=self.manager.create(db,s("design") or plan["direction"],budget,cap)
        task=self.get(db,"task",key)
        task.update(research_mode=research_mode,workspace=env["id"],environment=copy.deepcopy(env),agent=copy.deepcopy(agent),
                    plan=plan["id"],baseline=env["baseline"] if env.get("adapter") in ("iris","beans","name-llm") else s("baseline") or env["baseline"])
        task["constraints"].update(overall_auc_floor=env["floor"],dataset=env["dataset"])
        task["settings"]["skills"]=agent["skills"]
        if research_mode=="codex":
            task["decision_provider"] = "codex"
            task["scientific_skill"] = SCIENTIFIC_SKILL.read_text(encoding="utf-8")
        if env.get("adapter")=="iris":
            task["best"]=iris.evaluate(iris.dataset(),*iris.BASELINE)
            task["constraints"]["primary_metric"]="macro_f1"
            task["constraints"]["guardrail_metric"]="accuracy"
        if env.get("adapter")=="beans":
            task.update(strategy=strategy,continuous=continuous,interval=interval)
            task["best"]=dict(beans.baseline())
            task["constraints"].update(primary_metric="macro_f1",guardrail_metric="accuracy")
        if ntl:
            task.update(strategy=strategy,best=dict(env["baseline_metrics"]))
            task["constraints"].update(primary_metric="balanced_accuracy",guardrail_metric="accuracy")
        task["baseline_metrics"] = copy.deepcopy(task["best"])
        self.manager.save(db,task,"TripSci contract locked")
        plan["task"]=key
    elif op=="retry":
        task=self.get(db,"task",plan["task"])
        if task["status"]!="failed": raise ValueError("只有执行失败的计划可以重试。")
        failure=task.pop("failure","")
        stage=task.pop("failure_stage",None)
        task.pop("failure_info",None)
        resume_job = (stage=="training" or (stage is None and failure.startswith("本机训练失败"))) and task.get("pending_job")
        if resume_job:
            job=self.get(db,"job",task["pending_job"])
            attempts=job.setdefault("attempts",[])
            if not attempts:
                attempts.append({"number":0,"state":"failed","error_code":"legacy_failure"})
            job.update(retry_from=len(attempts),retry_at=0)
            self.put(db,"job",job)
        task.update(status="waiting" if resume_job else "ready",phase="scheduled",not_before=0)
        self.manager.save(db,task,"Retry requested")
    elif op=="finish":
        task=self.get(db,"task",plan["task"])
        if not task.get("continuous") or task["status"] not in ("ready","waiting","paused"):
            raise ValueError("只有运行或暂停的持续计划可以结束。")
        job=self.p.get(db,"job",task["pending_job"]) if task.get("pending_job") else None
        task.update(continuous=False,max_experiments=task["round"],not_before=0,
                    status="waiting" if job and not job.get("result") else "ready")
        self.manager.save(db,task,"Finish requested")
    elif op=="decision":
        task=self.get(db,"task",plan["task"])
        if task["status"]!="completed": raise ValueError("实验尚未完成。")
        if plan["decision"]: raise ValueError("结论已保存。")
        decision=s("value")
        if decision not in ("保留候选","不采用"): raise ValueError("请选择结论。")
        if decision=="保留候选" and "revision" not in task["best"]: raise ValueError("没有通过护栏的改进候选。")
        if task.get("environment",{}).get("adapter")=="iris":
            best=task["best"]
            data=iris.dataset()
            plan["holdout"]={"baseline":iris.evaluate(data,*iris.BASELINE,split="test")}
            if decision=="保留候选":
                plan["holdout"]["candidate"]=iris.evaluate(data,best["k"],best["scale"],split="test")
        if task.get("environment",{}).get("adapter")=="beans":
            data=beans.dataset()
            plan["holdout"]={"baseline":beans.evaluate(data,beans.BASELINE,split="test")}
            if decision=="保留候选":
                plan["holdout"]["candidate"]=beans.evaluate(data,task["best"]["config"],split="test")
        if task.get("environment",{}).get("adapter")=="name-llm":
            manifest=task["environment"]["manifest"]
            plan["holdout"]={"baseline":name_llm.evaluate(self.p.root,manifest,name_llm.BASELINE,"holdout")}
            if decision=="保留候选":
                plan["holdout"]["candidate"]=name_llm.evaluate(self.p.root,manifest,task["best"]["config"],"holdout")
        plan["decision"]=decision
    else:
        task=self.get(db,"task",plan["task"])
        if op=="pause" and task["status"] not in ("ready","waiting"): raise ValueError("当前不能暂停。")
        if op=="resume" and task["status"]!="paused": raise ValueError("计划未暂停。")
        message=s("text",required=True) if op=="feedback" else op
        if op=="feedback" and message in ("pause","resume"):
            raise ValueError("请使用计划控制按钮。")
        self.manager.feedback(db,task["id"],message)
    return self.put(db,"plan",plan)


def start_local_project(api, db, request, plan, env, agent):
    if agent["runtime"] != "codex" or not PROVIDERS["codex"].detect():
        raise ValueError("请选择可用的 Codex Worker。")
    goal = api.string(request, "design") or plan["direction"]
    key = api.manager.create(db, goal, request.get("budget"))
    task = api.get(db, "task", key)
    primary = env["primary_metric"]
    baseline = {primary: env["baseline_value"]}
    task.update(research_mode="agent", workspace=env["id"], plan=plan["id"],
                environment=copy.deepcopy(env), agent=copy.deepcopy(agent),
                baseline=env["baseline"], baseline_metrics=baseline, best=dict(baseline),
                constraints={"primary_metric": primary, "dataset": env["dataset"]})
    api.manager.save(db, task, "Local project research contract approved")
    plan["task"] = key
    return api.put(db, "plan", plan)
