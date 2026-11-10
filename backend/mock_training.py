"""Deterministic asynchronous mock training."""
from storage import CONSTRAINTS
import hashlib
import time


class MockTraining:
    @staticmethod
    def submit(key, revision, strength, delay):
        return {"id": key, "revision": revision, "strength": strength,
                "dataset": CONSTRAINTS["dataset"], "ready_at": time.time()+delay}

    @staticmethod
    def poll(job, now):
        if "measured" in job:
            return job["measured"]
        if now < job["ready_at"]:
            return None
        x = job["strength"]
        jitter = int(hashlib.sha256(str(x).encode()).hexdigest()[:2], 16) / 100000
        return {"low_freq_auc": round(.65+.032-.07*(x-.64)**2+jitter, 5),
                "overall_auc": round(.721-.011*x*x, 5)}
