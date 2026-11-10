"""Worker for legacy sample and benchmark plans."""
from mock_training import MockTraining
from research import planner
from run_workspace import prepare
from run_workspace import publish_result
from scheduler import TaskManager
from legacy.benchmarks import beans
from pathlib import Path
import fcntl
from legacy.benchmarks import iris
import json
from legacy.benchmarks import name_llm
import re
import subprocess
import sys
import time

BASE = Path(__file__).resolve().parent


class ResearchWorker:
    def __init__(self, project):
        self.p = project
        self.manager = TaskManager(project)

    @staticmethod
    def propose(best, tried, conservative):
        pool = [.2, .5, .8, .65, .35, .55, .6, .7, .75, .45, .1, .9, .25, .3]
        candidates = [x for x in pool if x not in tried and (not conservative or x <= .65)]
        if not tried:
            return candidates[0]
        if len(tried) == 1:
            return candidates[0]
        target = best.get("strength", .5) + (.12 if not conservative else -.05)
        return min(candidates, key=lambda x: abs(x-target))

    def run(self, key):
        with self.p.tx(readonly=True) as db:
            task = self.p.get(db, "task", key)
        if not task or task["status"] != "ready":
            return
        completed = []
        if task.get("research_mode") == "codex":
            directory = self.p.root / "decisions" / key
            directory.mkdir(parents=True, exist_ok=True)
            with (directory/"lock").open("a") as lock:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX|fcntl.LOCK_NB)
                except BlockingIOError:
                    return
                with self.p.tx(readonly=True) as db:
                    task = self.p.get(db, "task", key)
                    if task["status"] != "ready":
                        return
                    context = planner.snapshot(self.p, db, task)
                try:
                    decision = planner.decide(self.p.root, context)
                except (ValueError, OSError, subprocess.SubprocessError) as exc:
                    if isinstance(exc, subprocess.TimeoutExpired):
                        reason = "Codex 在 120 秒内未返回研究决策"
                    elif isinstance(exc, ValueError):
                        reason = str(exc)[:240]
                    else:
                        reason = "无法启动 Codex 决策进程"
                    print(reason, file=sys.stderr)
                    with self.p.tx() as db:
                        current = self.p.get(db, "task", key)
                        if current["status"] == "ready" and current["round"] == context["round"]:
                            current.update(status="failed", phase="failed", failure_stage="worker",
                                           failure=reason, failure_info={"log":f"decisions/{key}/worker.log"})
                            self.manager.save(db, current, "Codex research decision failed")
                    return
                self._run(key, completed, context, decision)
        else:
            self._run(key, completed)
        for record, report_text in completed:
            publish_result(self.p.root, record, report_text)

    def _run(self, key, completed, context=None, decision=None):
        with self.p.tx() as db:
            task = self.p.get(db, "task", key)
            if not task or task["status"] != "ready":
                return
            if context is not None:
                latest = planner.snapshot(self.p, db, task)
                if any(context[k] != latest[k] for k in ("round","result","feedback","budget","constraints")):
                    return
            if task.get("workspace"):
                self.p.repo = self.p.root / "projects" / task["workspace"]
                self.p.bootstrap()
            adapter = task.get("environment",{}).get("adapter")
            real = adapter == "iris"
            bean = adapter == "beans"
            ntl = adapter == "name-llm"
            primary=task["constraints"]["primary_metric"]
            guardrail=task["constraints"].get("guardrail_metric","overall_auc")
            if real and not (self.p.repo/"data/iris.json").exists():
                self.p.write("data/iris.json",iris.dataset())
                self.p.commit("Lock UCI Iris data and split", "data/iris.json")
            if bean and not (self.p.repo/"data/dry-bean.csv.gz").exists():
                target = self.p.repo/"data/dry-bean.csv.gz"
                target.parent.mkdir(exist_ok=True)
                temp=target.with_suffix(".tmp")
                temp.write_bytes((BASE/"benchmarks/datasets/dry-bean.csv.gz").read_bytes())
                temp.replace(target)
                self.p.write("evaluation/beans-protocol.json",{"sha256":beans.dataset()["sha256"],"seed":602,
                             "baseline":beans.BASELINE,"split":["train","validation","test"]})
                self.p.commit("Lock UCI Dry Bean data and evaluation protocol", "data/dry-bean.csv.gz", "evaluation/beans-protocol.json")
            if ntl and not (self.p.repo/"evaluation/name-llm-protocol.json").exists():
                self.p.write("evaluation/name-llm-protocol.json",task["environment"]["manifest"])
                self.p.commit("Lock Name That LLM prompt split protocol", "evaluation/name-llm-protocol.json")
            feedback = []
            for item in self.p.all(db, "inbox"):
                if item["task"] == key and not item["consumed"]:
                    if "conservative" in item["message"].lower() or "保守" in item["message"]:
                        task["conservative"] = True
                    feedback.append(item)
            if task["pending_job"]:
                job = self.p.get(db, "job", task["pending_job"])
                result = job["result"]
                floor = task["constraints"]["overall_auc_floor"]
                previous_best = task["best"][primary]
                passed = result[guardrail] >= floor
                accepted = passed and result[primary] > previous_best
                reference = task.get("baseline_metrics", {}).get(primary)
                assessment = {
                    "objective":task["goal"],
                    "primary_metric":primary,
                    "previous_best":previous_best,
                    "guardrail_metric":guardrail,
                    "guardrail_floor":floor,
                }
                report = f"reports/{job['id']}.md"
                disposition = ("Promote for review" if accepted else
                            "Rejected by guardrail" if not passed else "Did not beat the current best")
                report_text = (f"# Round {task['round']}\n\n## Research objective\n{task['goal']}\n\n"
                             f"Configuration: {job.get('config',job['strength'])}\n\n## Analysis\n"
                             f"{primary}: {result[primary]:.6f} vs previous best {previous_best:.6f}.\n"
                             f"{guardrail}: {result[guardrail]:.6f} vs minimum {floor:.6f}.\n"
                             f"Decision: {disposition}.\n\n## Evidence\nRevision: {job['revision']}\nMetrics: {result}\n")
                if job.get("research_proposal") and ntl:
                    hypothesis = job["research_proposal"]
                    report_text += ("\n## Experiment decision\n"
                                    f"- Hypothesis: {hypothesis['hypothesis']}\n"
                                    f"- Goal alignment: {hypothesis['objective_alignment']}\n"
                                    f"- Expected: {hypothesis['expected']}\n"
                                    f"- Disconfirming result: {hypothesis['disconfirming_result']}\n"
                                    f"- Evidence: {', '.join(hypothesis['history_refs']) or 'Initial hypothesis'}\n"
                                    f"- Rationale: {hypothesis['rationale']}\n")
                if job.get("diagnostics"):
                    evidence = planner.evidence(job)
                    report_text += "\n## Validation diagnostics\n" + json.dumps(
                        {k:evidence[k] for k in ("recalls","sample_counts","largest_confusions","elapsed_seconds")},
                        ensure_ascii=False, indent=2) + "\nFull confusion matrix: result.json.\n"
                if decision is not None:
                    report_text += "\n## Agent research analysis\n" + json.dumps(
                        decision["analysis"], ensure_ascii=False, indent=2) + "\n"
                self.p.write(report, report_text)
                record = {**job, "task": key, "round": task["round"], "accepted": accepted,
                          "guardrail_passed": passed, "assessment":assessment,
                          "baseline_delta": round(result[primary]-reference, 6) if reference is not None else None,
                          "report": report, "report_commit": self.p.commit(f"Record {job['id']}", report)}
                if decision is not None:
                    record["research_analysis"] = decision["analysis"]
                    record["research_evidence"] = [job["id"]]
                self.p.put(db, "experiment", job["id"], record)
                completed.append((record, report_text))
                if accepted:
                    task["best"] = {**result, "strength": job["strength"], "revision": job["revision"]}
                    if real: task["best"].update(k=job["k"],scale=job["scale"])
                    if bean or ntl: task["best"]["config"] = job["config"]
                task["pending_job"] = None
                self.manager.save(db, task, f"Analyzed {job['id']}: {'adopted' if accepted else 'rejected'}")
            if not task.get("continuous") and task["round"] >= task["max_experiments"]:
                task.update(status="completed", phase="finished")
                if decision and decision.get("summary"):
                    task["research_summary"] = decision["summary"]
                for item in feedback:
                    item.update(consumed=True, disposition="已纳入本轮分析上下文" if decision is not None else "预算已用完")
                    self.p.put(db,"inbox",item["id"],item)
                self.manager.save(db, task, "Experiment budget exhausted")
                return
            if task.get("continuous") and task["round"] and not task.get("pending_job") and task.get("cooldown_round") != task["round"]:
                task.update(not_before=time.time()+task["interval"],cooldown_round=task["round"],phase="cooldown")
                self.manager.save(db,task,"Waiting for next iteration window")
                return
            slots = self.p.get(db,"settings","active").get("slots",2)
            occupied = 0
            for other in self.p.all(db,"task"):
                if other["id"] != key and other.get("pending_job") and other["status"]!="failed":
                    active = self.p.get(db,"job",other["pending_job"])
                    occupied += bool(active and not active.get("result") and (active.get("adapter") in ("beans","name-llm") or MockTraining.poll(active,time.time()) is None))
            if occupied >= slots:
                if not task.get("queued"):
                    task.update(queued=True, phase="queued")
                    self.manager.save(db,task,"Waiting for a training slot")
                return
            task.pop("queued",None)
            tried = [e["strength"] for e in self.p.all(db, "experiment") if e["task"] == key]
            conservative = task.get("conservative", False) or "wide-search" not in task["settings"]["skills"]
            if decision is not None:
                if ntl:
                    candidate = decision["proposal"]["config"]
                    strength = 0
                else:
                    strength = decision["proposal"]["strength"]
            elif ntl:
                candidate=name_llm.propose(task["strategy"],task["round"]+1,task["best"])
                strength=0
            elif bean:
                candidate=beans.propose(task["strategy"],task["round"]+1,task["best"])
                strength=0
            elif real:
                tried_pairs=[(e["k"],e["scale"]) for e in self.p.all(db,"experiment") if e["task"]==key]
                k,scale=iris.choose(tried_pairs,task["best"])
                strength=0
            else:
                strength = self.propose(task["best"], tried, conservative)
            override = None
            for item in feedback:
                message = item["message"]
                match = re.search(r"(?:强度|strength)\s*[:：]?\s*(0(?:\.\d+)?|1(?:\.0+)?)(?![.\d])",message)
                disposition = "已读取，模拟 Worker 未识别为实验指令"
                if decision is not None:
                    disposition = "已纳入 Codex 研究决策上下文"
                elif real or bean or ntl:
                    disposition = "已读取：当前使用已锁定的实验策略"
                elif match:
                    value = float(match[1])
                    if value not in tried and (not conservative or value <= .65):
                        if override:
                            override["disposition"]="已被后续强度建议替代"
                            self.p.put(db,"inbox",override["id"],override)
                        strength, override, disposition = value, item, "已应用"
                    else:
                        disposition = "未应用：重复强度或超出搜索范围"
                elif "conservative" in message.lower() or "保守" in message:
                    disposition = "已应用：限制搜索范围"
                item.update(consumed=True,disposition=disposition)
                self.p.put(db,"inbox",item["id"],item)
            task["round"] += 1
            jobid = f"{key}-{task['round']}"
            model_path = f"models/{jobid}."+("json" if bean or ntl or real else "py")
            self.p.validate_candidate_path(model_path, task["constraints"])
            if bean or ntl:
                self.p.write(model_path,candidate)
            elif real:
                self.p.write(model_path,{"k":k,"scale":scale})
            else:
                self.p.write(model_path, f"STRENGTH = {strength}\n\ndef smooth(raw, prior):\n    return (1-STRENGTH)*raw + STRENGTH*prior\n")
            revision = self.p.commit(f"Prepare {jobid}", model_path)
            task["phase"] = "submitting"
            self.manager.save(db, task, f"Submitting {jobid}")
            if bean or ntl:
                job = dict(id=jobid,revision=revision,strength=0,adapter=adapter,config=candidate,ready_at=time.time()+1)
            else:
                job = MockTraining.submit(jobid, revision, strength, task["settings"]["delay"])
            job.update(task=key,dataset=task["constraints"]["dataset"],
                       mode=task.get("environment",{}).get("mode","local"))
            if real:
                data=json.loads((self.p.repo/"data/iris.json").read_text())
                job.update(k=k,scale=scale,measured=iris.evaluate(data,k,scale))
            if decision is not None:
                job["research_proposal"] = decision["proposal"]
                job["research_context_refs"] = [row["id"] for row in context["history"]]
                job["research_feedback_refs"] = [row["id"] for row in context["feedback"]]
            job["run_path"] = prepare(self.p.root, self.p.repo, task, job, model_path)
            self.p.put(db, "job", jobid, job)
            task.update(status="waiting", pending_job=jobid, phase="waiting",last_dispatched=time.time())
            self.manager.save(db, task, f"Submitted {jobid}; worker exits")
