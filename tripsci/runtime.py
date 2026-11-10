"""Launch local Workers and train immutable candidate configurations."""
import argparse
import fcntl
import hashlib
import json
import signal
import subprocess
import sys
import time
from pathlib import Path

from legacy.benchmarks import beans
from run_workspace import attempt_dir, run_dir

TRAINING_TIMEOUT = 120
BASE = Path(__file__).resolve().parent


class RuntimeAdapter:
    def __init__(self, root):
        self.root = root
        self.training = {}
        self.research = {}

    def launch_training(self, workspace, job_id, adapter, number):
        self.training = {key:proc for key,proc in self.training.items() if proc.poll() is None}
        directory = attempt_dir(self.root,job_id,number)
        directory.mkdir(parents=True,exist_ok=True)
        with (directory/"worker.log").open("ab") as log:
            self.training[job_id,number] = subprocess.Popen(
                [sys.executable,str(BASE/"runtime.py"),str(self.root),workspace,job_id,adapter,str(number)],
                stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True)

    def owns_training(self, job_id, number):
        return (job_id,number) in self.training

    def training_exit(self, job_id, number):
        proc = self.training.get((job_id,number))
        return proc.poll() if proc else None

    def stop_training(self, job_id, number):
        proc = self.training.get((job_id,number))
        if proc and proc.poll() is None:
            try:
                proc.kill()
            except ProcessLookupError:
                pass

    @staticmethod
    def training_locked(directory):
        path = directory/"lock"
        if not path.exists():
            return False
        with path.open("rb") as lock:
            try:
                fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:
                return True
        return False

    def research_active(self, key):
        proc = self.research.get(key)
        if proc is not None:
            status = proc.poll()
            if status is None:
                return True
            del self.research[key]
            if status:
                raise subprocess.CalledProcessError(status, "research worker")
        return self.training_locked(self.root / "decisions" / key)

    def start_research(self, key):
        directory = self.root / "decisions" / key
        directory.mkdir(parents=True, exist_ok=True)
        with (directory / "worker.log").open("ab") as log:
            self.research[key] = subprocess.Popen(
                [sys.executable, str(BASE/"app.py"), "--state", str(self.root), "--worker", key],
                stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True,
            )

    def run(self, key):
        subprocess.run([sys.executable, str(BASE/"app.py"), "--state", str(self.root), "--worker", key],
                       check=True, timeout=30)


def train_job(root, workspace, job_id, adapter="beans", number=0):
    job = attempt_dir(root,job_id,number)
    job.mkdir(parents=True,exist_ok=True)
    receipt = job/"result.json"
    with (job/"lock").open("a") as lock:
        try:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            return
        if receipt.exists():
            return
        started=time.time()
        try:
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
                from legacy.benchmarks import name_llm
                if manifest is None:
                    manifest=json.loads((repo/"evaluation/name-llm-protocol.json").read_text())
                diagnostics = {}
                result=name_llm.evaluate(root,manifest,candidate,diagnostics=diagnostics)
            else:
                data=beans.dataset(str(repo/"data"/"dry-bean.csv.gz"))
                if manifest and data["sha256"]!=manifest["sha256"]:
                    raise ValueError("Dataset hash does not match the run protocol")
                result=beans.evaluate(data,candidate)
            payload={"metrics":result,"started_at":started,"ended_at":time.time()}
            if adapter == "name-llm":
                payload["diagnostics"] = diagnostics
        except Exception as exc:
            print(type(exc).__name__,flush=True)
            payload={"error":type(exc).__name__,"started_at":started,"ended_at":time.time()}
        temp=receipt.with_suffix(".tmp")
        temp.write_text(json.dumps(payload),encoding="utf-8")
        temp.replace(receipt)


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("root",type=Path)
    parser.add_argument("workspace")
    parser.add_argument("job")
    parser.add_argument("adapter",choices=("beans","name-llm"),nargs="?",default="beans")
    parser.add_argument("number",type=int,nargs="?",default=0)
    args=parser.parse_args()
    signal.alarm(TRAINING_TIMEOUT)
    train_job(args.root,args.workspace,args.job,args.adapter,args.number)
