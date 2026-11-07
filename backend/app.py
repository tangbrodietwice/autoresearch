import argparse
import contextlib
import hashlib
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
        for name, value in {
            "data/synthetic-v1.json": [{"user": i, "frequency": 1+i%5, "click": i%3 == 0} for i in range(30)],
            "evaluation/protocol.json": CONSTRAINTS,
            "history.json": [{"name": "baseline", **SEED},
                             {"name": "historical heavy smoothing", "low_freq_auc": .646, "overall_auc": .719}],
        }.items():
            if not (self.repo / name).exists():
                self.write(name, value)
        if not self.git("rev-list", "--all", "--max-count=1"):
            self.commit("Bootstrap synthetic CTR project")

    @contextlib.contextmanager
    def tx(self):
        db = sqlite3.connect(self.root / "state.sqlite", timeout=15)
        try:
            db.execute("BEGIN IMMEDIATE")
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

    def commit(self, label):
        self.git("add", "-A")
        if self.git("diff", "--cached", "--name-only"):
            self.git("commit", "-qm", label)
        return self.git("rev-parse", "HEAD")

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

    def create(self, db, goal, budget):
        if not isinstance(goal, str) or not goal.strip() or len(goal)>500 or type(budget) is not int or not 1<=budget<=10:
            raise ValueError("Provide a goal and an experiment budget from 1 to 10.")
        key = uuid.uuid4().hex[:12]
        task = {"id": key, "goal": goal.strip(), "max_experiments": budget,
                "constraints": dict(CONSTRAINTS), "settings": self.p.get(db, "settings", "active"),
                "status": "ready", "round": 0, "best": SEED, "pending_job": None}
        self.save(db, task, "Task contract approved")
        return key

    def save(self, db, task, event):
        self.p.put(db, "task", task["id"], task)
        key = uuid.uuid4().hex
        self.p.put(db, "progress", key, {"task": task["id"], "round": task["round"],
                   "state": task["status"], "event": event, "time": time.time()})

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

    def tick(self, runtime):
        ready = []
        with self.p.tx() as db:
            for task in self.p.all(db, "task"):
                if task["status"] in ("waiting","paused") and task.get("pending_job"):
                    job = self.p.get(db, "job", task["pending_job"])
                    result = job.get("result") or MockTraining.poll(job, time.time())
                    if result is not None and ("result" not in job or task["status"]=="waiting"):
                        job["result"] = result
                        self.p.put(db, "job", job["id"], job)
                        if task["status"]=="waiting":
                            task["status"] = "ready"
                        self.save(db, task, "Training result available")
                if task["status"] == "ready":
                    ready.append(task["id"])
        for key in ready:
            runtime.run(key)


class RuntimeAdapter:
    def __init__(self, root):
        self.root = root

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
            real = task.get("environment",{}).get("adapter")=="iris"
            primary=task["constraints"]["primary_metric"]
            guardrail=task["constraints"].get("guardrail_metric","overall_auc")
            if real and not (self.p.repo/"data/iris.json").exists():
                self.p.write("data/iris.json",iris.dataset())
                self.p.commit("Lock UCI Iris data and split")
            feedback = []
            for item in self.p.all(db, "inbox"):
                if item["task"] == key and not item["consumed"]:
                    if "conservative" in item["message"].lower() or "保守" in item["message"]:
                        task["conservative"] = True
                    feedback.append(item)
            if task["pending_job"]:
                job = self.p.get(db, "job", task["pending_job"])
                result = job["result"]
                accepted = (result[guardrail] >= task["constraints"]["overall_auc_floor"]
                            and result[primary] > task["best"][primary])
                report = f"reports/{job['id']}.md"
                self.p.write(report, f"# Round {task['round']}\n\nRevision: {job['revision']}\n\n"
                             f"Strength: {job['strength']}\n\nMetrics: {result}\n\n"
                             f"Decision: {'adopt' if accepted else 'retain prior baseline'}\n")
                record = {**job, "task": key, "round": task["round"], "accepted": accepted,
                          "guardrail_passed": result[guardrail] >= task["constraints"]["overall_auc_floor"],
                          "report": report, "report_commit": self.p.commit(f"Record {job['id']}")}
                self.p.put(db, "experiment", job["id"], record)
                if accepted:
                    task["best"] = {**result, "strength": job["strength"], "revision": job["revision"]}
                    if real: task["best"].update(k=job["k"],scale=job["scale"])
                task["pending_job"] = None
                self.manager.save(db, task, f"Analyzed {job['id']}: {'adopted' if accepted else 'rejected'}")
            if task["round"] >= task["max_experiments"]:
                task["status"] = "completed"
                for item in feedback:
                    item.update(consumed=True, disposition="预算已用完")
                    self.p.put(db,"inbox",item["id"],item)
                self.manager.save(db, task, "Experiment budget exhausted")
                return
            slots = self.p.get(db,"settings","active").get("slots",2)
            occupied = 0
            for other in self.p.all(db,"task"):
                if other["id"] != key and other.get("pending_job"):
                    active = self.p.get(db,"job",other["pending_job"])
                    occupied += bool(active and MockTraining.poll(active,time.time()) is None)
            if occupied >= slots:
                if not task.get("queued"):
                    task["queued"]=True
                    self.manager.save(db,task,"Waiting for a training slot")
                return
            task.pop("queued",None)
            tried = [e["strength"] for e in self.p.all(db, "experiment") if e["task"] == key]
            conservative = task.get("conservative", False) or "wide-search" not in task["settings"]["skills"]
            if real:
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
                if real:
                    disposition = "已读取：Iris 使用固定 kNN 搜索协议"
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
            if real:
                self.p.write(f"models/{jobid}.json",{"k":k,"scale":scale})
            else:
                self.p.write(f"models/{jobid}.py", f"STRENGTH = {strength}\n\ndef smooth(raw, prior):\n    return (1-STRENGTH)*raw + STRENGTH*prior\n")
            revision = self.p.commit(f"Prepare {jobid}")
            job = MockTraining.submit(jobid, revision, strength, task["settings"]["delay"])
            job.update(task=key,dataset=task["constraints"]["dataset"],
                       mode=task.get("environment",{}).get("mode","local"))
            if real:
                data=json.loads((self.p.repo/"data/iris.json").read_text())
                job.update(k=k,scale=scale,measured=iris.evaluate(data,k,scale))
            self.p.put(db, "job", jobid, job)
            task.update(status="waiting", pending_job=jobid)
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
                with project.tx() as db:
                    return self.send(workspace.state(db))
            if self.path != "/api/state":
                return self.send({"error": "Not found"}, 404)
            with project.tx() as db:
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
                        result = workspace.action(db,request)
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
