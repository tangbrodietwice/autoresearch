"""Allocate stable, numbered attempts on persisted training jobs."""

def append_attempt(job, state, **fields):
    attempts = job.setdefault("attempts", [])
    number = attempts[-1]["number"] + 1 if attempts else 1
    attempt = dict(number=number, state=state, **fields)
    attempts.append(attempt)
    return attempt
