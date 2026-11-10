"""Export a readable, local snapshot of TripSci's workspace state."""
import argparse
import json
import os
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tripsci"))
from workspace_api import DEFAULT_AGENT


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as tmp:
        tmp.write(text)
    Path(tmp.name).replace(path)


def dump(path, value):
    write(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def link(path, directory):
    return quote(os.path.relpath(path, directory))


def export(state, output):
    database = state / "state.sqlite"
    with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True) as conn:
        records = defaultdict(list)
        for kind, body in conn.execute(
            "SELECT kind, body FROM records WHERE kind IN ('agent','skill','workspace','plan','task','experiment') ORDER BY rowid"
        ):
            records[kind].append(json.loads(body))

    agents = records["agent"]
    if not any(row["id"] == DEFAULT_AGENT["id"] for row in agents):
        agents = [DEFAULT_AGENT, *agents]
    index = ["# TripSci 工作区快照", "", f"导出时间：{datetime.now().astimezone().isoformat(timespec='seconds')}",
             f"来源：[SQLite 状态]({link(database, output)})", "",
             "此目录由导出脚本生成。运行时状态仍写入 SQLite，修改快照不会改变执行配置。", "", "## 智能体"]
    for agent in agents:
        directory = output / "agents" / agent["id"]
        write(directory / "AGENTS.md", agent["instructions"] + "\n")
        dump(directory / "agent.json", {k: v for k, v in agent.items() if k not in {"instructions", "skill_files"}})
        index.append(f"- [{agent['name']}](agents/{agent['id']}/AGENTS.md) · v{agent['version']}")
    index.extend(["", "## Skills"])
    for skill in records["skill"]:
        write(output / "skills" / skill["id"] / "SKILL.md", skill["markdown"] + "\n")
        index.append(f"- [{skill['name']}](skills/{skill['id']}/SKILL.md)")
    if not records["skill"]:
        index.append("- 当前工作区没有保存自定义 Skill。")
    index.append("- `adaptive-ctr` 和 `wide-search` 是 Worker 代码识别的内置策略标识。")
    index.extend(["", "## 项目和研究计划"])
    tasks = {row["id"]: row for row in records["task"]}
    runs = defaultdict(list)
    for experiment in records["experiment"]:
        runs[experiment["task"]].append(experiment)
    for project in records["workspace"]:
        key = project["id"]
        directory = output / "projects" / key
        repo = state / "projects" / key
        dump(directory / "project.json", project)
        index.append(f"- [{project['name']}](projects/{key}/project.json)")
        if repo.is_dir():
            index.append(f"  - [原始 Git 工作区]({link(repo, output)})")
    for plan in records["plan"]:
        key = plan["id"]
        directory = output / "projects" / (plan["workspace"] or "_unassigned") / "plans" / key
        task = tasks.get(plan.get("task"), {})
        experiments = sorted(runs.get(task.get("id"), []), key=lambda row: row["round"])
        dump(directory / "plan.json", plan)
        if task:
            dump(directory / "task.json", task)
        write(directory / "experiments.jsonl", "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in experiments))
        report = [f"# {plan['title']}", "", plan["direction"], "", f"已完成 {len(experiments)} 轮。",
                  "[全部实验记录](experiments.jsonl)"]
        if plan.get("decision"):
            report.append(f"评审结论：{plan['decision']}")
        report.extend(["", "## 最近实验报告"])
        for experiment in experiments[-10:][::-1]:
            artifact = state / "projects" / plan["workspace"] / experiment["report"]
            if artifact.is_file():
                entry = f"- [第 {experiment['round']} 轮]({link(artifact, directory)})"
                if experiment.get("run_path"):
                    run = state / experiment["run_path"] / "run.json"
                    if run.is_file():
                        entry += f" · [运行配置]({link(run, directory)})"
                report.append(entry)
        write(directory / "README.md", "\n".join(report) + "\n")
        index.append(f"- [{plan['title']}]({link(directory / 'README.md', output)}) · {len(experiments)} 轮")
    write(output / "README.md", "\n".join(index) + "\n")
    return len(agents), len(records["skill"]), len(records["plan"]), len(records["experiment"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", type=Path, default=os.environ.get("TRIPSCI_STATE", ROOT / ".state/web"))
    parser.add_argument("--output", type=Path, default=ROOT / "workspace-data")
    args = parser.parse_args()
    target = args.output.resolve()
    print(f"{target}: agents, skills, plans, experiments = {export(args.state.resolve(), target)}")
