"""Model-led research for a configured project, without a candidate catalogue."""
import json
from pathlib import Path
import uuid

from execution import run_json
from .profiles import normalize
from .runs import agent_run
from research.project_runner import clone, git
from run_artifacts import write_json


def schema(*names):
    return {"type": "object", "properties": {key: {"type": "string"} for key in names},
            "required": list(names), "additionalProperties": False}


PROPOSAL = schema("action", "hypothesis", "expected", "rationale")
ANALYSIS = schema("conclusion", "expectation", "next_step")


def ask(store, task, prompt, fields, workspace=None):
    agent = normalize(task["agent"])
    guidance = [agent["instructions"], *(row["markdown"] for row in agent.get("skill_files", []))]
    purpose = "experiment_proposal" if fields is PROPOSAL else "experiment_analysis"
    with agent_run(store, agent, purpose, plan=task["plan"],
                   task=task["id"], experiment=f"{task['id']}-{task['round'] + 1}") as run_id:
        result = run_json(agent["provider"], "\n".join(guidance) + "\n\n" + prompt,
                          fields, workspace=workspace, timeout=300)
        if (not isinstance(result, dict) or set(result) != set(fields["required"]) or
                any(not isinstance(v, str) or not v.strip() or len(v) > 6000 for v in result.values())):
            raise ValueError("Worker 返回了无效的研究记录。")
    return dict(result, agent_run=run_id)


def read(path):
    return json.loads(path.read_text())


def candidate(store, directory, task, previous, prompt):
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
    proposal = ask(store, task, prompt + "\n在当前工作区检查并实现候选代码。"
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
