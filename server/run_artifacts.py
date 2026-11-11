"""Files that capture what a local research run was given and produced."""
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from tempfile import NamedTemporaryFile


def write_text(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as file:
        file.write(value)
    Path(file.name).replace(path)


def write_json(path, value):
    write_text(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def run_dir(root, job_id):
    return root / "runs" / job_id


def attempt_dir(root, job_id, number):
    directory = run_dir(root, job_id)
    if (directory / "run.json").is_file() or (directory / "inputs.json").is_file():
        return directory / "attempts" / str(number)
    legacy = root / "training" / job_id
    return legacy / f"attempt-{number}" if number else legacy


def prepare(root, repo, task, job, model_path):
    directory = run_dir(root, job["id"])
    agent = task.get("agent", {})
    skills = agent.get("skill_files", [])
    if agent:
        write_text(directory / "AGENTS.md", agent["instructions"] + "\n")
    if task.get("scientific_skill"):
        write_text(directory / "skills" / "scientific-research" / "SKILL.md", task["scientific_skill"])
    for skill in skills:
        write_text(directory / "skills" / skill["id"] / "SKILL.md", skill["markdown"] + "\n")
    candidate = "candidate" + Path(model_path).suffix
    candidate_text = (repo / model_path).read_text(encoding="utf-8")
    write_text(directory / candidate, candidate_text)
    environment = task.get("environment", {})
    adapter = environment.get("adapter", "mock")
    protocol = {"constraints": task["constraints"], "baseline": task.get("baseline"),
                "baseline_metrics": task.get("baseline_metrics"),
                "project_version": environment.get("version")}
    if adapter == "name-llm":
        protocol["dataset_manifest"] = environment["manifest"]
    if adapter == "beans":
        protocol["dataset_manifest"] = json.loads((repo / "evaluation/beans-protocol.json").read_text())
    write_json(directory / "protocol.json", protocol)
    write_json(directory / "run.json", {
        "job": job["id"], "task": task["id"], "plan": task.get("plan"),
        "project": task.get("workspace"), "round": task["round"], "adapter": adapter,
        "revision": job["revision"], "candidate": candidate,
        "candidate_sha256": hashlib.sha256(candidate_text.encode()).hexdigest(),
        "agent": {k: agent[k] for k in ("id", "name", "version", "runtime") if k in agent},
        "skills": task["settings"]["skills"], "custom_skill_files": [row["id"] for row in skills],
        "instruction_handling": "codex_prompt" if job.get("research_proposal") else "snapshot_only",
        "research_proposal": job.get("research_proposal"),
        "research_context_refs": job.get("research_context_refs", []),
        "research_feedback_refs": job.get("research_feedback_refs", []),
    })
    return str(directory.relative_to(root))


def publish_result(root, record, report_text):
    directory = run_dir(root, record["id"])
    if not (directory / "run.json").is_file():
        return
    write_text(directory / "report.md", report_text)
    write_json(directory / "result.json", record)

def recover_results(project):
    """Repair a crash between the SQLite commit and publication of readable files."""
    with project.tx(readonly=True) as db:
        records = project.all(db, "experiment")
        tasks = {row["id"]: row for row in project.all(db, "task")}
    for record in records:
        directory = run_dir(project.root, record["id"])
        if record.get("adapter") == "local-project":
            continue  # This runner publishes its files before committing the experiment row.
        if not record.get("run_path") or (directory / "result.json").is_file():
            continue
        task = tasks[record["task"]]
        repo = project.root / "projects" / task["workspace"] if task.get("workspace") else project.repo
        try:
            report_text = subprocess.check_output(
                ["git", "-C", str(repo), "show", f"{record['report_commit']}:{record['report']}"],
                text=True,
            )
            publish_result(project.root, record, report_text)
        except (OSError, subprocess.SubprocessError) as exc:
            print(f"Could not restore run files for {record['id']}: {exc}", file=sys.stderr)
