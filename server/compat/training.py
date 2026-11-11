"""Evaluate compatibility benchmark jobs from their pinned configuration."""
import hashlib
import json

from run_artifacts import run_dir
from .benchmarks import beans, name_llm


def evaluate_benchmark(root, workspace, job_id, adapter):
    diagnostics = {}
    repo=root/"projects"/workspace
    directory=run_dir(root,job_id)
    metadata=directory/"run.json"
    if metadata.is_file():
        run=json.loads(metadata.read_text())
        if (run["job"],run["project"],run["adapter"]) != (job_id,workspace,adapter):
            raise ValueError("Run metadata does not match the dispatched job")
        candidate_text=(directory/run["candidate"]).read_text()
        if hashlib.sha256(candidate_text.encode()).hexdigest()!=run["candidate_sha256"]:
            raise ValueError("Candidate hash does not match the run configuration")
        candidate=json.loads(candidate_text)
        manifest=json.loads((directory/"protocol.json").read_text())["dataset_manifest"]
    else:
        candidate=json.loads((repo/"models"/f"{job_id}.json").read_text())
        manifest=None
    if adapter=="name-llm":
        if manifest is None:
            manifest=json.loads((repo/"evaluation/name-llm-protocol.json").read_text())
        result=name_llm.evaluate(root,manifest,candidate,diagnostics=diagnostics)
    else:
        data=beans.dataset(str(repo/"data"/"dry-bean.csv.gz"))
        if manifest and data["sha256"]!=manifest["sha256"]:
            raise ValueError("Dataset hash does not match the run protocol")
        result=beans.evaluate(data,candidate)
    return result, diagnostics
