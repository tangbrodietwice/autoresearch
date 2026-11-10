"""Durable execution records shared by local research and benchmark jobs."""
import time

from run_workspace import write_json


def append_attempt(job, state, **fields):
    attempts = job.setdefault("attempts", [])
    number = attempts[-1]["number"] + 1 if attempts else 1
    attempt = dict(number=number, state=state, **fields)
    attempts.append(attempt)
    return attempt


def execute_recorded(project, job_id, task, adapter, directory, execute, read_result):
    """Resume from a receipt, or record and execute a new attempt.

    The caller holds the research task lock for the entire operation.
    """
    with project.tx() as db:
        job = project.get(db, "job", job_id) or dict(
            id=job_id, task=task["id"], workspace=task["workspace"], adapter=adapter, attempts=[]
        )
        if "result" in job:
            return job["result"]

        now = time.time()
        previous = job["attempts"][-1] if job["attempts"] else None
        if previous and previous["state"] == "running":
            receipt = project.root / previous["receipt"]
            if receipt.is_file():
                metrics = read_result(receipt)
                previous.update(state="succeeded", ended_at=receipt.stat().st_mtime)
                job["result"] = metrics
                project.put(db, "job", job_id, job)
                return metrics
            previous.update(state="failed", ended_at=now, error_code="interrupted")

        attempt = append_attempt(job, "running", started_at=now)
        path = directory / "attempts" / str(attempt["number"])
        receipt = path / "receipt.json"
        attempt["receipt"] = str(receipt.relative_to(project.root))
        project.put(db, "job", job_id, job)

    try:
        path.mkdir(parents=True, exist_ok=False)
        metrics = execute(path)
        write_json(receipt, metrics)
    except Exception as exc:
        attempt.update(state="failed", ended_at=time.time(), error_code=type(exc).__name__)
        with project.tx() as db:
            project.put(db, "job", job_id, job)
        raise

    attempt.update(state="succeeded", ended_at=time.time())
    job["result"] = metrics
    with project.tx() as db:
        project.put(db, "job", job_id, job)
    return metrics
