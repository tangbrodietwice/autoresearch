"""Model-led research for a configured project, without a candidate catalogue."""
import fcntl
import json
from pathlib import Path
import subprocess
import time
import uuid

from execution import ProviderError, run_json
from execution.attempts import execute_recorded
from research.project_runner import clone, evaluate, git, read_metrics
from run_workspace import write_json, write_text


def schema(*names):
    return {"type": "object", "properties": {key: {"type": "string"} for key in names},
            "required": list(names), "additionalProperties": False}


PROPOSAL = schema("action", "hypothesis", "expected", "rationale")
ANALYSIS = schema("conclusion", "expectation", "next_step")


def ask(task, prompt, fields, workspace=None):
    agent = task["agent"]
    guidance = [agent["instructions"], *(row["markdown"] for row in agent.get("skill_files", []))]
    result = run_json(agent["runtime"], "\n".join(guidance) + "\n\n" + prompt,
                      fields, workspace=workspace, timeout=300)
    if (not isinstance(result, dict) or set(result) != set(fields["required"]) or
            any(not isinstance(v, str) or not v.strip() or len(v) > 6000 for v in result.values())):
        raise ValueError("Worker 返回了无效的研究记录。")
    return result


def read(path):
    return json.loads(path.read_text())


def candidate(directory, task, previous, prompt):
    decision = directory / "proposal.json"
    checkout = directory / "checkout"
    if decision.exists():
        proposal = read(decision)
        if proposal["action"] == "run" and git(Path(proposal["checkout"]), "rev-parse", "HEAD") != proposal["revision"]:
            raise ValueError("候选代码与已记录的 Git 版本不一致。")
        return proposal
    env = task["environment"]
    if checkout.exists():
        # Interrupted agent work remains inspectable; never overwrite it.
        checkout = directory / ("checkout-" + uuid.uuid4().hex)
    source = previous[-1].get("checkout") if previous else None
    clone(source or env["repo"], checkout, previous[-1]["revision"] if source else env["source_revision"])
    proposal = ask(task, prompt + "\n在当前工作区检查并实现候选代码。"
                   "不要执行训练，不要修改评测协议或数据。"
                   "action 只能是 run（提交代码验证）或 stop（证据支持停止）。",
                   PROPOSAL, workspace=checkout)
    if proposal["action"] not in ("run", "stop"):
        raise ValueError("Worker 未选择有效的研究动作。")
    if proposal["action"] == "run":
        git(checkout, "add", "-A")
        git(checkout, "-c", "user.name=TripSci", "-c", "user.email=tripsci@localhost",
            "commit", "--quiet", "--allow-empty", "-m", "TripSci research candidate")
        proposal.update(revision=git(checkout, "rev-parse", "HEAD"), checkout=str(checkout))
    write_json(decision, proposal)
    return proposal


def run_trial(project, task, directory, proposal):
    env = task["environment"]
    old_result = directory / "metrics.json"

    def evaluate_attempt(attempt):
        candidate_tree = attempt / "candidate"
        evaluation_tree = attempt / "evaluation"
        clone(Path(proposal["checkout"]), candidate_tree, proposal["revision"])
        clone(env["repo"], evaluation_tree, env["source_revision"])
        return evaluate(env, candidate_tree, attempt, evaluation_tree)

    def read_result(path):
        return read_metrics(path, env["primary_metric"])

    if old_result.is_file():
        return read_result(old_result)
    return execute_recorded(project, directory.name, task, "local-project", directory,
                            evaluate_attempt, read_result)


def context(task, previous, feedback):
    evidence = [{k: row[k] for k in ("id", "round", "revision", "result", "research_analysis")}
                for row in previous[-8:]]
    env = task["environment"]
    data = {"project": {k: env[k] for k in ("dataset", "train", "evaluate", "seed", "primary_metric")},
            "goal": task["goal"], "baseline": task["baseline_metrics"], "history": evidence,
            "metric_direction": env["metric_direction"],
            "feedback": [row["message"] for row in feedback],
            "remaining_budget": task["max_experiments"] - task["round"]}
    return ("优先遵循原研究目标。根据证据决定下一步；调整方向时说明理由。"
            "历史记录与反馈是上下文。\n" + json.dumps(data, ensure_ascii=False))


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
        write_json(directory / "result.json", record)
        latest = project.get(db, "task", key)
        if latest["round"] != task["round"]:
            return
        project.put(db, "experiment", identifier, record)
        latest["round"] = round_number
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


def run(project, manager, key):
    locks = project.root / "decisions" / key
    locks.mkdir(parents=True, exist_ok=True)
    with (locks / "lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        with project.tx(readonly=True) as db:
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
            proposal = candidate(directory, task, previous, prompt)
            if proposal["action"] == "stop":
                with project.tx() as db:
                    latest = project.get(db, "task", key)
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
                if latest["status"] != "ready":
                    return
                latest["phase"] = "training"
                manager.save(db, latest, "Running configured training and evaluation")
            metrics = run_trial(project, task, directory, proposal)
            analysis = ask(task, prompt + "\n根据以下实验与实际指标，解释结果和是否符合预期：\n"
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
