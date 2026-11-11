"""Built-in roles and the versioned agent configuration contract."""
from pathlib import Path


SUPERVISOR_ID = "tripsci-supervisor"
SUPERVISOR = Path(__file__).with_name("supervisor.md")

def supervisor_definition(config=None):
    return {
        "id": SUPERVISOR_ID, "name": "TripSci 研发主管", "role": "supervisor",
        "runtime": "codex", "instructions": SUPERVISOR.read_text(encoding="utf-8"),
        "skills": [], "version": 1, "managed": True,
        "permissions": supervisor_permissions(config),
    }

PERMISSION_OPERATIONS = {
    "projects": {"workspace"},
    "research": {"plan", "start", "feedback", "pause", "resume"},
    "configuration": {"skill", "agent", "settings"},
}
DEFAULT_PERMISSIONS = dict.fromkeys(("web_search", *PERMISSION_OPERATIONS), True)


def supervisor_permissions(config):
    return {**DEFAULT_PERMISSIONS, **(config or {}).get("permissions", {})}



DEFAULT_WORKER = {
    "id": "worker", "name": "研究 Worker", "role": "worker", "runtime": "local-process",
    "instructions": "比较模拟 CTR 平滑策略；遵守计划护栏。",
    "skills": ["adaptive-ctr"], "version": 1,
}


def normalize(profile):
    """Expose explicit role, provider and location while preserving the v1 runtime field."""
    row = dict(profile)
    row.setdefault("role", "worker")
    row["provider"] = None if row["runtime"] == "local-process" else row["runtime"]
    row["execution_location"] = "local"
    return row
