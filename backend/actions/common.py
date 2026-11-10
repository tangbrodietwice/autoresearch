"""Shared project fields and request helpers."""
import uuid

MODES = {"local": (), "hybrid": ("training_host", "delivery"),
         "remote": ("agent_host", "remote_dir")}
COMMON = ("name", "repo", "baseline", "dataset", "train", "evaluate")

def uid():
    return uuid.uuid4().hex[:12]
