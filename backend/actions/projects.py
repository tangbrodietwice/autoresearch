"""Workspace commands: projects."""
from .common import COMMON
from .common import MODES
from .common import uid
from pathlib import Path
from urllib.parse import urlparse
import beans
import iris
import name_llm
import re


def archive_workspace(self, db, d):
    op = d["op"]
    def s(key, default="", required=False):
        return self.string(d, key, default, required)

    kind = "workspace" if op == "archive_workspace" else "plan"
    row = self.get(db, kind, s("id", required=True))
    plans = [row] if kind == "plan" else [
        plan for plan in self.p.all(db, "plan") if plan.get("workspace") == row["id"]]
    for plan in plans:
        task = self.p.get(db, "task", plan.get("task")) or {}
        if task.get("status") in ("ready", "waiting"):
            raise ValueError("还有实验在运行，请先暂停研究计划再删除。")
    return self.put(db, kind, dict(row, archived=True))


def import_name_llm(self, db, d):
    def s(key, default="", required=False):
        return self.string(d, key, default, required)

    manifest=name_llm.latest(self.p.root)
    source = s("source_repo")
    revision = s("source_revision")
    checkout = s("source_checkout")
    if source and (urlparse(source).scheme not in ("https", "http") or not urlparse(source).hostname
                   or not re.fullmatch(r"[0-9a-f]{40}", revision) or not Path(checkout).is_absolute()):
        raise ValueError("上游代码来源需要仓库 URL、完整 Git 提交和本机目录。")
    provenance = {"source_repo":source, "source_revision":revision, "source_checkout":checkout} if source else {}
    existing=next((x for x in self.p.all(db,"workspace") if not x.get("archived") and x.get("adapter")=="name-llm" and x["manifest"]==manifest and all(x.get(k)==v for k,v in provenance.items())),None)
    if existing:
        return existing
    score=name_llm.evaluate(self.p.root,manifest,name_llm.BASELINE)
    return self.save_project_config(db,dict(id=uid(),name=s("name") or "Name That LLM"+(" · 合成测试" if manifest["fixture"] else " · Kaggle"),
        repo=name_llm.SOURCE,baseline="词频余弦质心",dataset="ntl-"+manifest["sha256"][:10],
        train="本机文本分类",evaluate="按 prompt_id 分组 · Balanced Accuracy",
        version=1,mode="local",floor=max(0,round(score["accuracy"]-.01,6)),adapter="name-llm",
        manifest=manifest,baseline_metrics=score,**provenance))


def import_beans(self, db, d):
    def s(key, default="", required=False):
        return self.string(d, key, default, required)

    name=s("name") or "Dry Bean · 豆类品种分类"
    existing=next((x for x in self.p.all(db,"workspace") if not x.get("archived") and x.get("adapter")=="beans" and x["name"]==name),None)
    if existing:
        return existing
    data=beans.dataset()
    return self.put(db,"workspace",dict(id=uid(),name=name,repo=beans.SOURCE,
        baseline="标准化最近质心",dataset="uci-dry-bean-"+data["sha256"][:8],
        train="本机独立 CPU 训练进程",evaluate="固定分层验证集 · macro F1 / accuracy",
        version=1,mode="local",floor=round(beans.baseline()["accuracy"]-.01,6),adapter="beans"))


def import_iris(self, db, d):
    existing=next((x for x in self.p.all(db,"workspace") if not x.get("archived") and x.get("adapter")=="iris"),None)
    if existing:
        plan = next((x for x in self.p.all(db,"plan")
                     if x["workspace"]==existing["id"] and not x.get("archived")), None)
        if plan:
            return plan
    data=iris.dataset()
    env=existing or self.put(db,"workspace",dict(id=uid(),name="Iris 鸢尾花分类",repo=iris.SOURCE,baseline="k=11 · 未缩放",
      dataset="uci-iris-"+data["sha256"][:8],train="内置 kNN",evaluate="固定验证集 · macro F1 / accuracy",
      version=1,mode="local",floor=.85,adapter="iris"))
    return self.put(db,"plan",dict(id=uid(),title="改进 Iris 分类器",direction="比较 kNN 邻居数和特征缩放；按验证集 macro F1 选候选。",
        workspace=env["id"],task="",messages=[{"role":"event","text":"已导入公开 Iris 数据：84 训练 / 33 验证 / 33 保留测试。"}],decision=""))


def workspace(self, db, d):
    op = d["op"]
    def s(key, default="", required=False):
        return self.string(d, key, default, required)

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
    if s("id") and (not old or old.get("archived")): raise ValueError("找不到要编辑的项目。")
    if old and old.get("adapter") in ("iris","beans","name-llm"): raise ValueError("公开数据集项目使用固定数据与评测协议。")
    plan_id=s("attach_plan")
    if plan_id:
        plan=self.get(db,"plan",plan_id)
        if old or plan["task"]:
            raise ValueError("只能为尚未启动的计划新建并关联项目。")
        plan["workspace"]=key
        self.put(db,"plan",plan)
    return self.save_project_config(db, dict(config,id=key,version=1 if not old else old["version"]+1))


def integration(self, db, d):
    def s(key, default="", required=False):
        return self.string(d, key, default, required)

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
    keys = ("balanced_accuracy", "accuracy") if env.get("adapter")=="name-llm" else ("macro_f1", "accuracy") if env.get("adapter") in ("iris","beans","name-llm") else ("low_freq_auc", "overall_auc")
    metrics = d.get("metrics", {})
    if not isinstance(metrics, dict) or any(type(metrics.get(k)) not in (int, float) or not 0 <= metrics[k] <= 1 for k in keys):
        raise ValueError("请提供 0 到 1 之间的完整项目评测指标。")
    return self.put(db, "integration", dict(id=uid(), workspace=env["id"], revision=revision,
                    dataset=env["dataset"], evaluate=env["evaluate"], adapter=env["adapter"],
                    ordinal=max((r["ordinal"] for r in prior), default=0)+1, plans=sources,
                    metrics={k: metrics[k] for k in keys}, summary=s("summary", required=True)))
