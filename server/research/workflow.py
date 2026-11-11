"""Advance a configured research plan using persisted decisions and training jobs."""
import fcntl
import json
import subprocess
from pathlib import Path

from agents.runs import mark_interrupted
from agents.worker import ANALYSIS, ask, candidate, context
from execution import ProviderError
from research.project_runner import read_metrics
from run_artifacts import write_json, write_text


def record_trial(project, manager, task, feedback, directory, proposal, metrics, analysis):
    key = task["id"]
    round_number = task["round"] + 1
    primary = task["constraints"]["primary_metric"]
    env = task["environment"]
    score = metrics[primary]
    best = task["best"][primary]
    accepted = score < best if env["metric_direction"] == "min" else score > best
    identifier = f"{key}-{round_number}"
    report = directory / "report.md"
    write_text(report, f"# {proposal['hypothesis']}\n\n"
               f"预期：{proposal['expected']}\n\n结论：{analysis['conclusion']}\n\n"
               f"是否符合预期：{analysis['expectation']}\n\n下一步：{analysis['next_step']}\n\n"
               f"指标：{json.dumps(metrics, ensure_ascii=False)}\n")
    record = dict(id=identifier, task=key, round=round_number, result=metrics, accepted=accepted,
                  revision=proposal["revision"], checkout=proposal["checkout"],
                  baseline_delta=score-task["baseline_metrics"][primary],
                  research_proposal=proposal, research_analysis=analysis,
                  report=str(report.relative_to(project.root)), run_path=str(directory.relative_to(project.root)),
                  adapter="local-project")
    with project.tx() as db:
        if project.get(db, "job", identifier):
            record["job"] = identifier
        record["plan"] = task["plan"]
        record["project"] = task["workspace"]
        latest = project.get(db, "task", key)
        if latest["round"] != task["round"] or latest["status"] != "ready":
            return
        write_json(directory / "result.json", record)
        project.put(db, "experiment", identifier, record)
        latest["round"] = round_number
        latest["pending_job"] = None
        if accepted:
            latest["best"] = {**metrics, "revision": proposal["revision"]}
        if round_number >= latest["max_experiments"]:
            latest.update(status="completed", phase="finished", research_summary={
                "findings": analysis["conclusion"], "limitations": "请以各轮实验记录和评测协议为准。",
                "next_steps": analysis["next_step"]})
        elif latest["status"] == "ready":
            latest["phase"] = "scheduled"
        for item in feedback:
            project.put(db, "inbox", item["id"], dict(item, consumed=True))
        manager.save(db, latest, f"Experiment {round_number} recorded")


def advance(project, manager, key):
    locks = project.root / "decisions" / key
    locks.mkdir(parents=True, exist_ok=True)
    with (locks / "lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        with project.tx() as db:
            mark_interrupted(project, db, task=key)
            task = project.get(db, "task", key)
            if task["status"] != "ready":
                return
            previous = sorted((row for row in project.all(db, "experiment") if row["task"] == key),
                              key=lambda row: row["round"])
            feedback = [row for row in project.all(db, "inbox") if row["task"] == key and not row["consumed"]]
        directory = project.root / "runs" / f"{key}-{task['round'] + 1}"
        directory.mkdir(parents=True, exist_ok=True)
        env = task["environment"]
        prompt = context(task, previous, feedback)
        try:
            proposal = candidate(project, directory, task, previous, prompt)
            if proposal["action"] == "stop":
                with project.tx() as db:
                    latest = project.get(db, "task", key)
                    if latest["status"] != "ready" or latest["round"] != task["round"]:
                        return
                    latest.update(status="completed", phase="finished",
                                  research_summary={"findings": proposal["rationale"], "limitations": "见各轮实验记录。",
                                                    "next_steps": proposal["expected"]})
                    manager.save(db, latest, "Worker concluded the research")
                return
            write_json(directory / "inputs.json", {k: env[k] for k in
                       ("source_revision", "data_sha256", "commands", "seed", "primary_metric",
                        "metric_direction", "version")} | {"code_revision": proposal["revision"]})
            with project.tx() as db:
                latest = project.get(db, "task", key)
                if latest["status"] != "ready" or latest["round"] != task["round"]:
                    return
                job_id = directory.name
                job = project.get(db, "job", job_id) or dict(id=job_id, task=key, workspace=task["workspace"],
                          plan=task["plan"], adapter="local-project", attempts=[], ready_at=0)
                job.update(task=key, workspace=task["workspace"], plan=task["plan"],
                           candidate={"checkout":proposal["checkout"], "revision":proposal["revision"]},
                           environment=env, ready_at=0)
                # Adapt old synchronous attempts in place. Keep their IDs and receipts.
                old = job["attempts"][-1] if job["attempts"] else None
                if "result" not in job and old and old.get("receipt") and old["state"] == "running":
                    receipt = project.root / old["receipt"]
                    if receipt.is_file():
                        job["result"] = read_metrics(receipt, env["primary_metric"])
                        old.update(state="succeeded", ended_at=receipt.stat().st_mtime)
                    else:
                        old.update(state="failed", error_code="legacy_interrupted")
                        latest.update(status="failed", phase="failed", failure_stage="training",
                                      pending_job=job_id, failure="旧版训练未留下回执；确认旧训练进程结束后重试。")
                        project.put(db, "job", job_id, job)
                        manager.save(db, latest, "Legacy attempt interrupted")
                        return
                legacy = directory / "metrics.json"
                if "result" not in job and legacy.is_file():
                    job["result"] = read_metrics(legacy, env["primary_metric"])
                project.put(db, "job", job_id, job)
                if "result" not in job:
                    latest.update(status="waiting", phase="queued", pending_job=job_id)
                    manager.save(db, latest, "Configured training queued")
                    return
                metrics = job["result"]
            analysis = ask(project, task, prompt + "\n根据以下实验与实际指标，解释结果和是否符合预期：\n"
                           + json.dumps({"hypothesis": proposal["hypothesis"],
                                         "expected": proposal["expected"], "metrics": metrics},
                                        ensure_ascii=False), ANALYSIS)
            record_trial(project, manager, task, feedback, directory, proposal, metrics, analysis)
        except (OSError, ValueError, ProviderError, subprocess.SubprocessError) as exc:
            print(str(exc), flush=True)
            with project.tx() as db:
                latest = project.get(db, "task", key)
                if latest["status"] == "ready":
                    latest.update(status="failed", phase="failed", failure_stage="worker",
                                  failure=str(exc)[:240],
                                  failure_info={"log": str((locks / "worker.log").relative_to(project.root))})
                    manager.save(db, latest, "Local project research failed")
