"""Record effective agent configuration and outcome for each model invocation."""
from contextlib import contextmanager
import time
import uuid


@contextmanager
def agent_run(store, profile, purpose, **references):
    run_id = uuid.uuid4().hex
    row = {
        "id": run_id, "agent": profile.get("id"), "profile_version": profile.get("version"),
        "provider": profile["provider"], "execution_location": profile["execution_location"],
        "role": profile["role"], "purpose": purpose, "status": "running", "started_at": time.time(),
        **references,
    }
    with store.tx() as db:
        store.put(db, "agent_run", run_id, row)
    try:
        yield run_id
    except Exception as error:
        row.update(status="failed", error_code=type(error).__name__)
        raise
    else:
        row["status"] = "completed"
    finally:
        if row["status"] != "running":
            with store.tx() as db:
                store.put(db, "agent_run", run_id, dict(row, ended_at=time.time()))


def mark_interrupted(store, db, **scope):
    """Close abandoned invocations after the caller acquires the corresponding lease."""
    for row in store.all(db, "agent_run"):
        if row["status"] == "running" and all(row.get(key) == value for key, value in scope.items()):
            row.update(status="failed", error_code="interrupted", ended_at=time.time())
            store.put(db, "agent_run", row["id"], row)
