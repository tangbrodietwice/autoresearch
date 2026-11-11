"""Deterministic research scheduling and training recovery."""
from compat.mock_training import MockTraining
from run_artifacts import attempt_dir
from research.project_runner import valid_metrics
from execution.attempts import append_attempt
from execution.local_process import TRAINING_TIMEOUT
from storage import CONSTRAINTS
from storage import SEED
import json
import math
import subprocess
import time
import uuid


PROCESS_ADAPTERS = {"beans", "name-llm", "local-project"}


class TaskManager:
    def __init__(self, project):
        self.p = project

    def create(self, db, goal, budget, cap=10, *, constraints=None, baseline=None):
        if not isinstance(goal, str) or not goal.strip() or len(goal)>500 or type(budget) is not int or not 1<=budget<=cap:
            raise ValueError("Provide a goal and a valid experiment budget.")
        key = uuid.uuid4().hex[:12]
        task = {"id": key, "goal": goal.strip(), "max_experiments": budget,
                "constraints": dict(CONSTRAINTS if constraints is None else constraints), "settings": self.p.get(db, "settings", "active"),
                "status": "ready", "round": 0, "best": dict(SEED if baseline is None else baseline), "pending_job": None, "phase": "scheduled"}
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
    training_timeout = TRAINING_TIMEOUT
    training_retry_delay = 1

    def training_failure(self, db, task, job, attempt, code, now, detail=None):
        attempt.update(state="failed", ended_at=now, error_code=code)
        if detail is not None:
            attempt["detail"] = detail
        count = len(job["attempts"]) - job.get("retry_from", 0)
        terminal = count >= self.max_training_attempts
        if terminal and task["status"] != "paused":
            reason = {"training_error":"训练返回错误","invalid_receipt":"结果文件无效",
                      "missing_receipt":"训练退出但未写入结果","timeout":"训练超时",
                      "launch_failed":"无法启动训练进程"}[code]
            task.update(status="failed", phase="failed", failure_stage="training",
                        failure=f"本机训练失败：{reason}（已尝试 {count} 次）",
                        failure_info=dict(attempt))
        elif not terminal:
            job["retry_at"] = now + self.training_retry_delay * 2**(count-1)
            task["phase"] = "training_retry"
        self.p.put(db, "job", job["id"], job)
        self.save(db, task, f"Training attempt {attempt['number']}: {code}")

    def training_result(self, db, task, job, runtime, now, launches):
        attempts = job.setdefault("attempts", [])
        if not attempts and "retry_from" not in job and job["adapter"] != "local-project":
            attempts.append({"number":0,"state":"running","started_at":now})
        attempt = attempts[-1] if attempts else None
        if attempt and attempt["state"] == "dispatch_pending":
            number = attempt["number"]
            directory = attempt_dir(self.p.root,job["id"],number)
            if (directory/"result.json").exists() or runtime.attempt_lock_held(directory):
                attempt.update(state="running",started_at=attempt.get("requested_at",now))
                self.p.put(db,"job",job["id"],job)
            else:
                if task["status"] == "waiting":
                    launches.append((task["id"],task["workspace"],job["id"],job["adapter"],number))
                return None
        if attempt and attempt["state"] == "running":
            number = attempt["number"]
            directory = attempt_dir(self.p.root,job["id"],number)
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
                    primary = task["constraints"]["primary_metric"]
                    if job.get("adapter") == "local-project":
                        if not valid_metrics(metrics, primary):
                            raise ValueError("Invalid metrics")
                    else:
                        keys = {primary, task["constraints"]["guardrail_metric"]}
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
                if payload.get("diagnostics"):
                    job["diagnostics"] = payload["diagnostics"]
                return metrics
            exit_code = runtime.training_exit(job["id"],number)
            if exit_code is not None:
                self.training_failure(db,task,job,attempt,"missing_receipt",now,exit_code)
                return None
            locked = runtime.attempt_lock_held(directory)
            if job.get("adapter") != "local-project" and now-attempt["started_at"] >= self.training_timeout:
                runtime.stop_training(job["id"],number)
                self.training_failure(db,task,job,attempt,"timeout",now)
                return None
            if number != 0:
                if not locked and not runtime.owns_training(job["id"],number) and now-attempt["started_at"] >= 2:
                    self.training_failure(db,task,job,attempt,"missing_receipt",now)
                return None
            if locked:
                self.p.put(db,"job",job["id"],job)
                return None
            # Old jobs had no durable launch record. Reuse a receipt or a held lock if present.
            attempts.pop()
        if (attempt and attempt["state"] == "failed"
                and len(attempts) - job.get("retry_from", 0) >= self.max_training_attempts
                and task["status"] == "waiting"):
            self.training_failure(db, task, job, attempt, attempt["error_code"], now)
            return None
        if task["status"] != "waiting" or now < job.get("retry_at",0):
            return None
        attempt = append_attempt(job, "dispatch_pending", requested_at=now)
        number = attempt["number"]
        attempt["log"] = str(attempt_dir(self.p.root, job["id"], number).relative_to(self.p.root) / "worker.log")
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
                        if job.get("adapter") in PROCESS_ADAPTERS:
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
            with self.p.tx() as db:
                task = self.p.get(db,"task",key)
                job = self.p.get(db,"job",job_id)
                attempt = job["attempts"][-1]
                if (task["status"] != "waiting" or task["pending_job"] != job_id
                        or attempt["number"] != number or attempt["state"] != "dispatch_pending"):
                    continue
                slots = (self.p.get(db, "settings", "active") or {}).get("slots", 2)
                occupied = sum(
                    other.get("adapter") in PROCESS_ADAPTERS
                    and "result" not in other and other.get("attempts")
                    and other["attempts"][-1]["state"] == "running"
                    for other in self.p.all(db, "job") if other.get("attempts")
                )
                if occupied >= slots:
                    if task["phase"] != "queued":
                        task["phase"] = "queued"
                        self.save(db, task, "Waiting for a training slot")
                    continue
                try:
                    runtime.launch_training(workspace,job_id,adapter,number)
                except OSError as exc:
                    self.training_failure(db,task,job,attempt,"launch_failed",time.time(),exc.errno)
                else:
                    attempt.update(state="running",started_at=time.time())
                    self.p.put(db,"job",job_id,job)
                    task["phase"] = "training"
                    self.save(db, task, "Training attempt started")
        for _, key in sorted(ready):
            try:
                with self.p.tx() as db:
                    task = self.p.get(db, "task", key)
                    if task["status"] != "ready":
                        continue
                    research = task.get("research_mode") in ("agent", "codex")
                    if research and runtime.research_active(key):
                        continue
                    if not task.get("queued") or task.get("pending_job"):
                        task["phase"] = "research_decision" if research else "analyzing" if task["pending_job"] else "preparing"
                        self.save(db, task, "Worker is deciding from research history" if research else
                                  "Worker is analyzing results" if task["pending_job"] else "Worker is preparing code")
                if research:
                    runtime.start_research(key)
                else:
                    runtime.run(key)
            except (OSError, subprocess.SubprocessError):
                with self.p.tx() as db:
                    task = self.p.get(db, "task", key)
                    if task["status"] == "ready":
                        task.update(status="failed", phase="failed",failure_stage="worker",
                                    failure="Worker 未能完成当前步骤。请检查执行环境后重试。",
                                    failure_info={"log":f"decisions/{key}/worker.log"} if task.get("research_mode") in ("agent", "codex") else {})
                        self.save(db, task, "Worker execution failed")
