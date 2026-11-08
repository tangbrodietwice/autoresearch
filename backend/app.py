import argparse
import contextlib
import hashlib
import fcntl
import math
import json
import re
from pathlib import Path
import sqlite3
import subprocess
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from native_api import WorkspaceAPI
import iris
import beans
import name_llm

BASE = Path(__file__).resolve().parent
SEED = {"low_freq_auc": .65, "overall_auc": .72}
DEFAULT = {"runtime": "local-process", "skills": ["adaptive-ctr"], "delay": 1.5}
CONSTRAINTS = {"primary_metric": "low_freq_auc", "max_parallel_jobs": 1,
               "overall_auc_floor": .715, "editable_paths": ["models/"],
               "protected_paths": ["data/", "evaluation/"], "dataset": "synthetic-v1"}


class Project:
    def __init__(self, root):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.repo = self.root / "project"
        self.repo.mkdir(exist_ok=True)
        self.bootstrap()
        with self.tx() as db:
            db.execute("CREATE TABLE IF NOT EXISTS records (kind TEXT, id TEXT, body TEXT, PRIMARY KEY(kind,id))")
            if not self.get(db, "settings", "active"):
                self.put(db, "settings", "active", DEFAULT)

    def bootstrap(self):
        if (self.repo / ".git").exists() and self.git("rev-list", "--all", "--max-count=1"):
            return
        self.repo.mkdir(parents=True, exist_ok=True)
        self.git("init", "-q")
        files = {
            "data/synthetic-v1.json": [{"user": i, "frequency": 1+i%5, "click": i%3 == 0} for i in range(30)],
            "evaluation/protocol.json": CONSTRAINTS,
            "history.json": [{"name": "baseline", **SEED},
                             {"name": "historical heavy smoothing", "low_freq_auc": .646, "overall_auc": .719}],
        }
        for name, value in files.items():
            if not (self.repo / name).exists():
                self.write(name, value)
        if not self.git("rev-list", "--all", "--max-count=1"):
            self.commit("Bootstrap synthetic CTR project", *files)

    @contextlib.contextmanager
    def tx(self, readonly=False):
        db = sqlite3.connect(self.root / "state.sqlite", timeout=15)
        try:
            db.execute("BEGIN" if readonly else "BEGIN IMMEDIATE")
            with db:
                yield db
        finally:
            db.close()

    def write(self, name, value):
        path = self.repo / name
        path.parent.mkdir(exist_ok=True, parents=True)
        temp = path.with_suffix(".tmp")
        temp.write_text(value if isinstance(value, str) else json.dumps(value, indent=2), encoding="utf-8")
        temp.replace(path)

    def git(self, *args):
        return subprocess.check_output(["git", "-C", str(self.repo), "-c", "user.name=Research Worker",
                                        "-c", "user.email=worker@localhost", *args], text=True).strip()

    def commit(self, label, *paths):
        if not paths:
            raise ValueError("Artifact commit requires explicit paths")
        self.git("add", "--", *paths)
        if self.git("diff", "--cached", "--name-only", "--", *paths):
            self.git("commit", "--only", "-qm", label, "--", *paths)
            return self.git("rev-parse", "HEAD")
        expected = [self.git("hash-object", "--", path) for path in paths]
        for revision in self.git("log", "--format=%H", "--fixed-strings", "--grep="+label, "--", *paths).splitlines():
            if self.git("show", "-s", "--format=%s", revision) != label:
                continue
            try:
                blobs = [self.git("rev-parse", revision+":"+path) for path in paths]
            except subprocess.CalledProcessError:
                continue
            if blobs == expected:
                return revision
        raise RuntimeError(f"Cannot recover artifact revision for {label}")

    @staticmethod
    def put(db, kind, key, value):
        db.execute("INSERT INTO records VALUES (?,?,?) ON CONFLICT(kind,id) DO UPDATE SET body=excluded.body",
                   (kind, key, json.dumps(value, ensure_ascii=False)))

    @staticmethod
    def get(db, kind, key):
        row = db.execute("SELECT body FROM records WHERE kind=? AND id=?", (kind, key)).fetchone()
        return json.loads(row[0]) if row else None

    @staticmethod
    def all(db, kind):
        return [json.loads(row[0]) for row in db.execute("SELECT body FROM records WHERE kind=? ORDER BY rowid", (kind,))]


class MockTraining:
    @staticmethod
    def submit(key, revision, strength, delay):
        return {"id": key, "revision": revision, "strength": strength,
                "dataset": CONSTRAINTS["dataset"], "ready_at": time.time()+delay}

    @staticmethod
    def poll(job, now):
        if "measured" in job:
            return job["measured"]
        if now < job["ready_at"]:
            return None
        x = job["strength"]
        jitter = int(hashlib.sha256(str(x).encode()).hexdigest()[:2], 16) / 100000
        return {"low_freq_auc": round(.65+.032-.07*(x-.64)**2+jitter, 5),
                "overall_auc": round(.721-.011*x*x, 5)}


class TaskManager:
    def __init__(self, project):
        self.p = project

    def create(self, db, goal, budget, cap=10):
        if not isinstance(goal, str) or not goal.strip() or len(goal)>500 or type(budget) is not int or not 1<=budget<=cap:
            raise ValueError("Provide a goal and a valid experiment budget.")
        key = uuid.uuid4().hex[:12]
        task = {"id": key, "goal": goal.strip(), "max_experiments": budget,
                "constraints": dict(CONSTRAINTS), "settings": self.p.get(db, "settings", "active"),
                "status": "ready", "round": 0, "best": SEED, "pending_job": None, "phase": "scheduled"}
        self.save(db, task, "Task contract approved")
        return key

    def save(self, db, task, event):
        self.p.put(db, "task", task["id"], task)
        key = uuid.uuid4().hex
        self.p.put(db, "progress", key, {"task": task["id"], "round": task["round"],
                   "state": task["status"], "phase": task.get("phase"), "event": event, "time": time.time()})

    def feedback(self, db, key, message):
        task = self.p.get(db, "task", key)
        if not task or task["status"] == "completed":
            raise ValueError("Choose an active task.")
        if not isinstance(message, str) or not message.strip() or len(message)>1000:
            raise ValueError("Provide feedback up to 1000 characters.")
        msg = uuid.uuid4().hex
        self.p.put(db, "inbox", msg, {"id": msg, "task": key, "message": message, "consumed": False})
        if message == "pause":
            task["status"] = "paused"
        if message == "resume" and task["status"] == "paused":
            task["status"] = "waiting" if task["pending_job"] else "ready"
        self.save(db, task, f"Inbox: {message}")

    max_training_attempts = 3
    training_timeout = beans.TRAINING_TIMEOUT
    training_retry_delay = 1

    def training_failure(self, db, task, job, attempt, code, now, detail=None):
        attempt.update(state="failed", ended_at=now, error_code=code)
        if detail is not None:
            attempt["detail"] = detail
        count = len(job["attempts"]) - job.get("retry_from", 0)
        terminal = count >= self.max_training_attempts
        if terminal:
            reason = {"training_error":"训练返回错误","invalid_receipt":"结果文件无效",
                      "missing_receipt":"训练退出但未写入结果","timeout":"训练超时",
                      "launch_failed":"无法启动训练进程"}[code]
            task.update(status="failed", phase="failed", failure_stage="training",
                        failure=f"本机训练失败：{reason}（已尝试 {count} 次）",
                        failure_info=dict(attempt))
        else:
            job["retry_at"] = now + self.training_retry_delay * 2**(count-1)
            task["phase"] = "training_retry"
        self.p.put(db, "job", job["id"], job)
        self.save(db, task, f"Training attempt {attempt['number']}: {code}")

    def training_result(self, db, task, job, runtime, now, launches):
        attempts = job.setdefault("attempts", [])
        if not attempts and "retry_from" not in job:
            attempts.append({"number":0,"state":"running","started_at":now})
        attempt = attempts[-1] if attempts else None
        if attempt and attempt["state"] == "running":
            number = attempt["number"]
            directory = beans.attempt_dir(self.p.root,job["id"],number)
            receipt = directory/"result.json"
            if receipt.exists():
                try:
                    payload = json.loads(receipt.read_text())
                    if not isinstance(payload,dict):
                        raise ValueError("Receipt must be an object")
                    if payload.get("error"):
                        self.training_failure(db,task,job,attempt,"training_error",now,str(payload["error"])[:80])
                        return None
                    metrics = payload["metrics"]
                    keys = {task["constraints"]["primary_metric"], task["constraints"]["guardrail_metric"]}
                    if not all(type(metrics[k]) in (int,float) and math.isfinite(metrics[k]) and 0<=metrics[k]<=1 for k in keys):
                        raise ValueError("Invalid metric")
                    started, ended = payload["started_at"],payload["ended_at"]
                    if not all(type(v) in (int,float) and math.isfinite(v) for v in (started,ended)) or started>ended:
                        raise ValueError("Invalid timing")
                except (OSError, ValueError, TypeError, KeyError):
                    self.training_failure(db,task,job,attempt,"invalid_receipt",now)
                    return None
                if now < job["ready_at"]:
                    return None
                attempt.update(state="succeeded",ended_at=ended)
                job.update(training_started_at=started,training_ended_at=ended)
                return metrics
            exit_code = runtime.training_exit(job["id"],number)
            if exit_code is not None:
                self.training_failure(db,task,job,attempt,"missing_receipt",now,exit_code)
                return None
            if now-attempt["started_at"] >= self.training_timeout:
                runtime.stop_training(job["id"],number)
                self.training_failure(db,task,job,attempt,"timeout",now)
                return None
            locked = runtime.training_locked(directory)
            if number != 0:
                if not locked and not runtime.owns_training(job["id"],number) and now-attempt["started_at"] >= 2:
                    self.training_failure(db,task,job,attempt,"missing_receipt",now)
                return None
            if locked:
                self.p.put(db,"job",job["id"],job)
                return None
            # Old jobs had no durable launch record. Reuse a receipt or a held lock if present.
            attempts.pop()
        if now < job.get("retry_at",0):
            return None
        number = attempts[-1]["number"]+1 if attempts else 1
        attempt = {"number":number,"state":"running","started_at":now,
                   "log":str(beans.attempt_dir(self.p.root,job["id"],number).relative_to(self.p.root)/"worker.log")}
        attempts.append(attempt)
        task["phase"] = "waiting"
        self.p.put(db,"job",job["id"],job)
        launches.append((task["id"],task["workspace"],job["id"],job["adapter"],number))
        return None

    def tick(self, runtime):
        ready, launches = [], []
        now = time.time()
        with self.p.tx() as db:
            for task in self.p.all(db, "task"):
                if task["status"] in ("waiting","paused") and task.get("pending_job"):
                    job = self.p.get(db, "job", task["pending_job"])
                    result = job.get("result")
                    if result is None:
                        if job.get("adapter") in ("beans","name-llm"):
                            result = self.training_result(db,task,job,runtime,now,launches)
                        else:
                            result = MockTraining.poll(job,now)
                    if result is not None and ("result" not in job or task["status"]=="waiting"):
                        job["result"] = result
                        self.p.put(db, "job", job["id"], job)
                        if task["status"]=="waiting":
                            task.update(status="ready", phase="analyzing")
                        self.save(db, task, "Training result available")
                if task["status"] == "ready" and (task.get("pending_job") or now >= task.get("not_before",0)):
                    ready.append((task.get("last_dispatched",0),task["id"]))
        for key, workspace, job_id, adapter, number in launches:
            try:
                runtime.launch_training(workspace,job_id,adapter,number)
            except OSError as exc:
                with self.p.tx() as db:
                    task = self.p.get(db,"task",key)
                    job = self.p.get(db,"job",job_id)
                    self.training_failure(db,task,job,job["attempts"][-1],"launch_failed",time.time(),exc.errno)
        for _, key in sorted(ready):
            with self.p.tx() as db:
                task = self.p.get(db, "task", key)
                if task["status"] != "ready":
                    continue
                if not task.get("queued") or task.get("pending_job"):
                    task["phase"] = "analyzing" if task["pending_job"] else "preparing"
                    self.save(db, task, "Worker is analyzing results" if task["pending_job"] else "Worker is preparing code")
            try:
                runtime.run(key)
            except (OSError, subprocess.SubprocessError):
                with self.p.tx() as db:
                    task = self.p.get(db, "task", key)
                    if task["status"] == "ready":
                        task.update(status="failed", phase="failed",failure_stage="worker",
                                    failure="Worker 未能完成当前步骤。请检查执行环境后重试。")
                        self.save(db, task, "Worker execution failed")


class RuntimeAdapter:
    def __init__(self, root):
        self.root = root
        self.training = {}

    def launch_training(self, workspace, job_id, adapter, number):
        self.training = {key:proc for key,proc in self.training.items() if proc.poll() is None}
        directory = beans.attempt_dir(self.root,job_id,number)
        directory.mkdir(parents=True,exist_ok=True)
        with (directory/"worker.log").open("ab") as log:
            self.training[job_id,number] = subprocess.Popen(
                [sys.executable,str(BASE/"beans.py"),str(self.root),workspace,job_id,adapter,str(number)],
                stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True)

    def owns_training(self, job_id, number):
        return (job_id,number) in self.training

    def training_exit(self, job_id, number):
        proc = self.training.get((job_id,number))
        return proc.poll() if proc else None

    def stop_training(self, job_id, number):
        proc = self.training.get((job_id,number))
        if proc and proc.poll() is None:
            try:
                proc.kill()
            except ProcessLookupError:
                pass

    @staticmethod
    def training_locked(directory):
        path = directory/"lock"
        if not path.exists():
            return False
        with path.open("rb") as lock:
            try:
                fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:
                return True
        return False

    def run(self, key):
        subprocess.run([sys.executable, str(BASE/"app.py"), "--state", str(self.root), "--worker", key],
                       check=True, timeout=30)


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
        with self.p.tx() as db:
            task = self.p.get(db, "task", key)
            if not task or task["status"] != "ready":
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
                temp.write_bytes((BASE/"datasets/dry-bean.csv.gz").read_bytes())
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
                decision = ("Promote for review" if accepted else
                            "Rejected by guardrail" if not passed else "Did not beat the current best")
                self.p.write(report, f"# Round {task['round']}\n\n## Research objective\n{task['goal']}\n\n"
                             f"Configuration: {job.get('config',job['strength'])}\n\n## Analysis\n"
                             f"{primary}: {result[primary]:.6f} vs previous best {previous_best:.6f}.\n"
                             f"{guardrail}: {result[guardrail]:.6f} vs minimum {floor:.6f}.\n"
                             f"Decision: {decision}.\n\n## Evidence\nRevision: {job['revision']}\nMetrics: {result}\n")
                record = {**job, "task": key, "round": task["round"], "accepted": accepted,
                          "guardrail_passed": passed, "assessment":assessment,
                          "baseline_delta": round(result[primary]-reference, 6) if reference is not None else None,
                          "report": report, "report_commit": self.p.commit(f"Record {job['id']}", report)}
                self.p.put(db, "experiment", job["id"], record)
                if accepted:
                    task["best"] = {**result, "strength": job["strength"], "revision": job["revision"]}
                    if real: task["best"].update(k=job["k"],scale=job["scale"])
                    if bean or ntl: task["best"]["config"] = job["config"]
                task["pending_job"] = None
                self.manager.save(db, task, f"Analyzed {job['id']}: {'adopted' if accepted else 'rejected'}")
            if not task.get("continuous") and task["round"] >= task["max_experiments"]:
                task.update(status="completed", phase="finished")
                for item in feedback:
                    item.update(consumed=True, disposition="预算已用完")
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
            if ntl:
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
                if real or bean or ntl:
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
            self.p.put(db, "job", jobid, job)
            task.update(status="waiting", pending_job=jobid, phase="waiting",last_dispatched=time.time())
            self.manager.save(db, task, f"Submitted {jobid}; worker exits")


class MainAgent:
    def __init__(self, manager):
        self.manager = manager

    def reply(self, db, request):
        message = request.get("message")
        if not isinstance(message, str) or not message.strip() or len(message)>1000:
            raise ValueError("Enter a message up to 1000 characters.")
        action = request.get("action", "chat")
        key = request.get("task")
        if action == "delegate":
            key = self.manager.create(db, message, request.get("budget", 3))
            reply = f"已委派 {key}。Worker 会在预算内自主选择实验。"
        elif action == "feedback":
            self.manager.feedback(db, key, message.strip())
            reply = f"已将反馈写入 {key} 的 Inbox。"
        elif action == "chat":
            tasks = self.manager.p.all(db, "task")
            task = self.manager.p.get(db, "task", key) if key else (tasks[-1] if tasks else None)
            reply = (f"{task['goal']}：{task['status']}，第 {task['round']}/{task['max_experiments']} 轮，"
                     f"最佳低频 AUC {task['best']['low_freq_auc']}。可继续提交反馈。"
                     if task else "当前项目使用固定的模拟 CTR 评测。可先确定目标和轮数，然后委派研究。")
        else:
            raise ValueError("Unknown action.")
        for role, content in (("user", message), ("main", reply)):
            self.manager.p.put(db, "chat", uuid.uuid4().hex, {"role": role, "message": content, "task": key})
        return {"task": key, "reply": reply}


def serve(project, port):
    manager = TaskManager(project)
    main = MainAgent(manager)
    workspace = WorkspaceAPI(project,manager)
    runtime = RuntimeAdapter(project.root)

    def schedule():
        while True:
            try:
                manager.tick(runtime)
            except Exception as exc:
                print(f"Scheduler retry: {exc}", file=sys.stderr)
            time.sleep(.2)

    class Handler(BaseHTTPRequestHandler):
        def send(self, value, status=200, mime="application/json"):
            body = value if isinstance(value, bytes) else json.dumps(value, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", mime+"; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path == "/v1/state":
                with project.tx(readonly=True) as db:
                    state = workspace.state(db)
                return self.send(state)
            if self.path != "/api/state":
                return self.send({"error": "Not found"}, 404)
            with project.tx(readonly=True) as db:
                state = {k: project.all(db, k) for k in ("task", "experiment", "chat", "progress", "inbox")}
                state["settings"] = project.get(db, "settings", "active")
            state["knowledge"] = {"protocol": CONSTRAINTS, "history": json.loads((project.repo/"history.json").read_text())}
            self.send(state)

        def do_POST(self):
            if self.headers.get_content_type() != "application/json":
                return self.send({"error": "Expected JSON"}, 415)
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= 8192:
                    raise ValueError("Invalid request size.")
                request = json.loads(self.rfile.read(size))
                if not isinstance(request, dict):
                    raise ValueError("Expected an object.")
                with project.tx() as db:
                    if self.path == "/v1/action":
                        request_key = request.pop("request_key",None)
                        if request_key is None:
                            result = workspace.action(db,request)
                        else:
                            if not isinstance(request_key,str) or not re.fullmatch(r"[a-zA-Z0-9_-]{16,100}",request_key):
                                raise ValueError("Invalid request key.")
                            digest = hashlib.sha256(json.dumps(request,sort_keys=True).encode()).hexdigest()
                            previous = project.get(db,"request",request_key)
                            if previous:
                                if digest != previous["digest"]:
                                    raise ValueError("Request key already used with different data.")
                                result = previous["result"]
                            else:
                                result = workspace.action(db,request)
                                project.put(db,"request",request_key,{"digest":digest,"result":result})
                    elif self.path == "/api/chat":
                        result = main.reply(db, request)
                    elif self.path == "/api/settings":
                        skills = request.get("skills")
                        delay = request.get("delay")
                        if (request.get("runtime") != "local-process" or not isinstance(skills, list)
                                or "adaptive-ctr" not in skills or any(s not in ("adaptive-ctr", "wide-search") for s in skills)
                                or type(delay) not in (int, float) or not .1 <= delay <= 60):
                            raise ValueError("Invalid runtime, skills or training delay.")
                        project.put(db, "settings", "active", request)
                        result = request
                    else:
                        return self.send({"error": "Not found"}, 404)
                self.send(result)
            except (ValueError, TypeError) as exc:
                self.send({"error": str(exc)}, 400)

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=schedule, daemon=True).start()
    print(f"http://127.0.0.1:{server.server_port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", type=Path, default=BASE.parent/".state")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--worker")
    args = parser.parse_args()
    project = Project(args.state)
    if args.worker:
        ResearchWorker(project).run(args.worker)
    else:
        serve(project, args.port)
