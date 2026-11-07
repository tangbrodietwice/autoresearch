"""Versioned application operations shared by the native client and tests."""
import copy
import re
import shutil
from pathlib import Path
from urllib.parse import urlparse
import iris
import uuid

MODES = {"local": (), "hybrid": ("training_host", "delivery"),
         "remote": ("agent_host", "remote_dir")}
COMMON = ("name", "repo", "baseline", "dataset", "train", "evaluate")


def runtimes():
    specs=(("codex","Codex"),("claude","Claude Code"),("gemini","Gemini CLI"),("opencode","OpenCode"),("aider","Aider"))
    result=[{"id":"local-process","name":"TripSci Worker","installed":True,"executable":True}]
    for key,name in specs:
        path=shutil.which(key)
        if not path:
            path=next((str(p) for p in [Path.home()/".local/bin"/key,Path.home()/".bun/bin"/key,*Path.home().glob(f".nvm/versions/node/*/bin/{key}")] if p.is_file() and p.stat().st_mode & 0o111),None)
        if not path and key=="codex":
            p=Path("/Applications/Codex.app/Contents/Resources/codex")
            if p.is_file(): path=str(p)
        result.append(dict(id=key,name=name,installed=bool(path),path=path,executable=False))
    return result


class WorkspaceAPI:
    def __init__(self, project, manager):
        self.p, self.manager = project, manager

    def get(self, db, kind, key):
        row = self.p.get(db, kind, key)
        if row is None:
            raise ValueError(f"{kind} 不存在。")
        return row

    def put(self, db, kind, row):
        self.p.put(db, kind, row["id"], row)
        return row

    def state(self, db):
        data = {k: self.p.all(db, k) for k in ("workspace", "plan", "thread", "agent", "task", "job", "experiment", "progress", "inbox", "tool", "skill", "integration")}
        if not any(x["id"]=="worker" for x in data["agent"]):
            data["agent"].insert(0,{"id":"worker", "name":"研究 Worker", "runtime":"local-process",
                              "instructions":"比较模拟 CTR 平滑策略；遵守计划护栏。", "skills":["adaptive-ctr"], "version":1})
        data["runtimes"] = runtimes()
        data["settings"] = self.p.get(db, "settings", "active")
        return data

    @staticmethod
    def string(d, key, default="", required=False):
        x = d.get(key, default)
        if not isinstance(x, str) or len(x) > 4000 or (required and not x.strip()):
            raise ValueError(f"请检查字段：{key}")
        return x.strip()

    def action(self, db, d):
        op = d.get("op")
        uid = lambda: uuid.uuid4().hex[:12]
        s = lambda key, default="", required=False: self.string(d,key,default,required)
        if op == "integration":
            env = self.get(db, "workspace", s("workspace", required=True))
            plans = d.get("plans")
            if not isinstance(plans, list) or not plans or any(not isinstance(k, str) for k in plans):
                raise ValueError("请选择成果来源研究计划。")
            sources = []
            for key in dict.fromkeys(plans):
                plan = self.get(db, "plan", key)
                if plan["workspace"] != env["id"] or plan.get("decision") != "保留候选":
                    raise ValueError("只能记录此项目已保留候选的研究计划。")
                task = self.get(db, "task", plan["task"])
                sources.append({"id": key, "title": plan["title"], "revision": task["best"]["revision"]})
            revision = s("revision", required=True).lower()
            if not re.fullmatch(r"[a-f0-9]{40}|[a-f0-9]{64}", revision):
                raise ValueError("请输入合并后的完整 Git 提交哈希。")
            prior = [r for r in self.p.all(db, "integration") if r["workspace"] == env["id"]]
            if any(r["revision"] == revision for r in prior):
                raise ValueError("这个项目提交已经记录。")
            keys = ("macro_f1", "accuracy") if env.get("adapter") == "iris" else ("low_freq_auc", "overall_auc")
            metrics = d.get("metrics", {})
            if not isinstance(metrics, dict) or any(type(metrics.get(k)) not in (int, float) or not 0 <= metrics[k] <= 1 for k in keys):
                raise ValueError("请提供 0 到 1 之间的完整项目评测指标。")
            return self.put(db, "integration", dict(id=uid(), workspace=env["id"], revision=revision,
                            dataset=env["dataset"], evaluate=env["evaluate"], adapter=env["adapter"],
                            ordinal=max((r["ordinal"] for r in prior), default=0)+1, plans=sources,
                            metrics={k: metrics[k] for k in keys}, summary=s("summary", required=True)))
        if op == "import_iris":
            existing=next((x for x in self.p.all(db,"workspace") if x.get("adapter")=="iris"),None)
            if existing:
                return next(x for x in self.p.all(db,"plan") if x["workspace"]==existing["id"])
            data=iris.dataset()
            env=self.put(db,"workspace",dict(id=uid(),name="Iris 鸢尾花分类",repo=iris.SOURCE,baseline="k=11 · 未缩放",
              dataset="uci-iris-"+data["sha256"][:8],train="内置 kNN",evaluate="固定验证集 · macro F1 / accuracy",
              version=1,mode="local",floor=.85,adapter="iris"))
            return self.put(db,"plan",dict(id=uid(),title="改进 Iris 分类器",direction="比较 kNN 邻居数和特征缩放；按验证集 macro F1 选候选。",
                workspace=env["id"],task="",messages=[{"role":"event","text":"已导入公开 Iris 数据：84 训练 / 33 验证 / 33 保留测试。"}],decision=""))
        if op == "tool":
            kind=s("kind",required=True)
            target=s("target",required=True)
            if kind not in ("link","command"): raise ValueError("未知工具类型。")
            if kind=="link" and (urlparse(target).scheme not in ("http","https") or not urlparse(target).hostname):
                raise ValueError("请输入有效的 HTTP/HTTPS 链接。")
            return self.put(db,"tool",dict(id=uid(),name=s("name",required=True),kind=kind,target=target))
        if op == "skill":
            return self.put(db,"skill",dict(id=uid(),name=s("name",required=True),markdown=s("markdown",required=True)))
        if op in ("workspace", "check"):
            mode = s("mode")
            if mode not in MODES:
                raise ValueError("请选择执行模式。")
            config = {key:s(key,required=True) for key in (*COMMON,*MODES[mode])}
            floor = d.get("floor")
            if type(floor) not in (float,int) or not 0 <= floor <= 1:
                raise ValueError("AUC 护栏必须介于 0 和 1。")
            config.update(mode=mode,floor=floor,adapter="mock")
            if op=="check":
                return {"message":"模拟配置通过。未连接服务器，也未验证实际仓库、命令或数据。"}
            key = s("id") or uid()
            old = self.p.get(db,"workspace",key)
            if s("id") and not old: raise ValueError("找不到要编辑的项目。")
            if old and old.get("adapter")=="iris": raise ValueError("内置 Iris 项目使用固定数据与评测协议。")
            return self.put(db,"workspace",dict(config,id=key,version=1 if not old else old["version"]+1))
        if op == "agent":
            key = s("id") or uid()
            old = self.p.get(db,"agent",key)
            if not old and key=="worker":
                old={"version":1}
            if s("id") and not old:
                raise ValueError("找不到要编辑的智能体。")
            skills = d.get("skills",["adaptive-ctr"])
            catalog={x["id"]:x for x in self.p.all(db,"skill")}
            if not isinstance(skills,list) or "adaptive-ctr" not in skills or any(not isinstance(x,str) or x not in ("adaptive-ctr","wide-search") and x not in catalog for x in skills):
                raise ValueError("请选择支持的研究 Skill。")
            runtime=s("runtime","local-process")
            if not any(x["id"]==runtime and x["installed"] for x in runtimes()):
                raise ValueError("请选择已检测到的运行时。")
            name, instructions = s("name",required=True), s("instructions")
            version=1 if not old else old["version"]+1
            directory=self.p.root/"agents"/key/f"v{version}"
            directory.mkdir(parents=True,exist_ok=True)
            path=directory/"AGENTS.md"
            path.write_text(instructions+"\n",encoding="utf-8")
            return self.put(db,"agent",{"id":key,"name":name,"instructions":instructions,"instructions_path":str(path.relative_to(self.p.root)),
                                        "runtime":runtime,"skills":skills,"skill_files":[catalog[x] for x in skills if x in catalog],"version":version})
        if op == "plan":
            key=s("workspace")
            if key: self.get(db,"workspace",key)
            source=s("source")
            messages=[]
            if source:
                thread=self.get(db,"thread",source)
                messages.append({"role":"event","text":"来源聊天："+thread["title"]})
            return self.put(db,"plan",{"id":uid(),"title":s("title",required=True),"direction":s("direction",required=True),
                                       "workspace":key,"task":"","messages":messages,"decision":""})
        if op == "message":
            msg=s("text",required=True)
            key=s("plan")
            if key:
                plan=self.get(db,"plan",key)
                task=self.p.get(db,"task",plan["task"])
                reply=(f"实验进度：{task['round']}/{task['max_experiments']}。实验安排建议可通过「给 Worker 反馈」单独发送。"
                       if task else "先明确对照和可检验的目标。准备好后，在右侧确认项目、基线、护栏与预算。")
                row=plan
            else:
                key=s("thread") or uid()
                row=self.p.get(db,"thread",key) or {"id":key,"title":msg[:30],"messages":[]}
                reply="可在这段聊天里梳理研究方向，或把讨论整理成研究计划草稿。"
                if "skill" in msg.lower():
                    reply="Skill 草案：读取实验记录，按锁定的 overall_auc 护栏检查，并引用原始结果。"
                elif "进度" in msg or "阻塞" in msg:
                    rows=self.p.all(db,"task")
                    reply=f"共有 {len(rows)} 项已启动的研究，{sum(x['status']=='waiting' for x in rows)} 项正在等训练结果。"
            row["messages"] += [{"role":"user","text":msg},{"role":"agent","text":reply}]
            return self.put(db,"plan" if s("plan") else "thread",row)
        if op == "settings":
            delay, slots=d.get("delay"),d.get("slots")
            if type(delay) not in (int,float) or not .2<=delay<=60 or type(slots) is not int or not 1<=slots<=8:
                raise ValueError("模拟时长为 0.2–60 秒，并发为 1–8。")
            row=self.p.get(db,"settings","active")
            row.update(delay=delay,slots=slots)
            self.p.put(db,"settings","active",row)
            return row
        if op not in ("attach","start","feedback","pause","resume","decision"):
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
            agent=next((x for x in self.state(db)["agent"] if x["id"]==s("agent","worker")),None)
            if not agent: raise ValueError("请选择执行智能体。")
            if agent["runtime"]!="local-process": raise ValueError("外部运行时目前仅检测和配置；执行请选择 TripSci Worker。")
            budget=d.get("budget")
            if type(budget) is not int or not 1<=budget<=10: raise ValueError("预算必须为 1–10 轮。")
            key=self.manager.create(db,plan["direction"],budget)
            task=self.get(db,"task",key)
            task.update(workspace=env["id"],environment=copy.deepcopy(env),agent=copy.deepcopy(agent),
                        plan=plan["id"],baseline=env["baseline"] if env.get("adapter")=="iris" else s("baseline") or env["baseline"])
            task["constraints"].update(overall_auc_floor=env["floor"],dataset=env["dataset"])
            task["settings"]["skills"]=agent["skills"]
            if env.get("adapter")=="iris":
                task["best"]=iris.evaluate(iris.dataset(),*iris.BASELINE)
                task["constraints"]["primary_metric"]="macro_f1"
                task["constraints"]["guardrail_metric"]="accuracy"
            self.manager.save(db,task,"TripSci contract locked")
            plan["task"]=key
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
