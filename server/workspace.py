"""Versioned application operations shared by the native client and tests."""
from commands import ACTIONS, validate_fields
from pathlib import Path
from execution import runtimes
from agents.profiles import DEFAULT_WORKER, SUPERVISOR_ID, normalize, supervisor_definition
from run_artifacts import write_json, write_text


class WorkspaceAPI:
    def __init__(self, project, manager):
        self.p, self.manager = project, manager
        with self.p.tx() as db:
            supervisor = self.p.get(db, "agent", SUPERVISOR_ID)
            if not supervisor:
                previous = self.p.get(db, "agent_permissions", SUPERVISOR_ID)
                self.save_agent(db, supervisor_definition(previous))
                db.execute("DELETE FROM records WHERE kind=? AND id=?", ("agent_permissions", SUPERVISOR_ID))
            else:
                instructions = supervisor_definition()["instructions"]
                if supervisor["instructions"] != instructions:
                    self.save_agent(db, dict(supervisor, instructions=instructions, version=supervisor["version"] + 1))
            if not self.p.get(db, "agent", "worker"):
                self.save_agent(db, DEFAULT_WORKER)
            for agent in self.p.all(db, "agent"):
                if agent != normalize(agent) or not self.p.get(db, "agent_profile_version", f'{agent["id"]}:{agent["version"]}'):
                    self.save_agent(db, agent)

    def save_agent(self, db, agent):
        row = normalize(agent)
        directory = self.p.root / "agents" / row["id"] / f'v{row["version"]}'
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "AGENTS.md"
        write_text(path, row["instructions"] + "\n")
        row["instructions_path"] = str(path.relative_to(self.p.root))
        self.p.put(db, "agent_profile_version", f'{row["id"]}:{row["version"]}', row)
        return self.put(db, "agent", row)

    def save_project_config(self, db, config):
        relative = Path("projects") / config["id"]
        directory = self.p.root / relative
        if directory.resolve() != directory:
            raise ValueError("项目管理目录不能指向其他位置。")
        path = directory / f'config-v{config["version"]}.json'
        row = dict(config, managed_dir=str(relative), config_path=str(path.relative_to(self.p.root)))
        try:
            write_json(path, row)
        except OSError as exc:
            raise ValueError("无法写入 TripSci 管理的项目目录，请检查本机存储权限。") from exc
        return self.put(db, "workspace", row)

    def get(self, db, kind, key):
        row = self.p.get(db, kind, key)
        if row is None or self.p.archived(db, kind, row):
            raise ValueError(f"{kind} 不存在。")
        return row

    def put(self, db, kind, row):
        self.p.put(db, kind, row["id"], row)
        return row

    @staticmethod
    def report(plan, task, experiments):
        primary = task["constraints"]["primary_metric"]
        runs = sorted(experiments, key=lambda row: row["round"])
        winners = [r for r in runs if r.get("accepted")]
        return dict(title=plan["title"], goal=task["goal"], baseline=task["baseline"], primary=primary,
                    baseline_value=task.get("baseline_metrics", {}).get(primary), budget=task["max_experiments"],
                    runs=runs, candidate=winners[-1] if winners else None, decision=plan["decision"],
                    dataset=task["constraints"]["dataset"], agent=task["agent"], holdout=plan.get("holdout"),
                    research_summary=task.get("research_summary"))

    def state(self, db):
        data = {k: self.p.all(db, k) for k in ("workspace", "plan", "thread", "agent", "task", "job", "experiment", "progress", "inbox", "tool", "skill", "integration")}
        archived_projects = {row["id"] for row in data["workspace"] if row.get("archived")}
        data["workspace"] = [row for row in data["workspace"] if not row.get("archived")]
        data["plan"] = [row for row in data["plan"]
                        if not row.get("archived") and row.get("workspace") not in archived_projects]
        data["agent"].sort(key=lambda row: row["id"] != SUPERVISOR_ID)
        data["runtimes"] = runtimes()
        detected = {row["id"]: row["installed"] for row in data["runtimes"]}
        for agent in data["agent"]:
            if agent["id"] == SUPERVISOR_ID:
                agent["runtime_detected"] = detected.get(agent["runtime"], False)
        data["settings"] = self.p.get(db, "settings", "active")
        tasks = {x["id"]: x for x in data["task"]}
        runs = {}
        for row in data["experiment"]:
            runs.setdefault(row["task"], []).append(row)
        for plan in data["plan"]:
            task = tasks.get(plan.get("task"))
            if task and task["status"] == "completed":
                plan["report"] = self.report(plan, task, runs.get(task["id"], []))
        return data

    @staticmethod
    def string(d, key, default="", required=False):
        x = d.get(key, default)
        if not isinstance(x, str) or len(x) > 4000 or (required and not x.strip()):
            raise ValueError(f"请检查字段：{key}")
        return x.strip()

    def action(self, db, d):
        op = d.get("op")
        handler = ACTIONS.get(op) if isinstance(op, str) else None
        if handler is None:
            raise ValueError("未知操作。")
        ignored = {"op", "managed_dir", "config_path"} if op == "workspace" else {"op"}
        payload = {key: value for key, value in d.items() if key not in ignored}
        validate_fields(op, payload)
        return handler(self, db, d)
