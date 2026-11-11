"""Launch local Workers and train immutable candidate configurations."""
import argparse
import os
from contextlib import nullcontext
import fcntl
import signal
import subprocess
import sys
import time
from pathlib import Path

from run_artifacts import attempt_dir, write_json
from storage import WorkspaceStore
from research.project_runner import clone, evaluate

TRAINING_TIMEOUT = 120
BACKEND_DIR = Path(__file__).resolve().parents[1]


class LocalProcessRunner:
    def __init__(self, root):
        self.root = root
        self.training = {}
        self.research = {}

    def launch_training(self, workspace, job_id, adapter, number):
        self.training = {key:proc for key,proc in self.training.items() if proc.poll() is None}
        directory = attempt_dir(self.root,job_id,number)
        directory.mkdir(parents=True,exist_ok=True)
        # Keep the lease across the Popen/SQLite commit gap, including server restarts.
        with (directory / "lock").open("ab") as lock, (directory / "worker.log").open("ab") as log:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return  # A previous scheduler already launched this attempt.
            fd = lock.fileno()
            self.training[job_id, number] = subprocess.Popen(
                [sys.executable, "-m", "execution.local_process", str(self.root), workspace, job_id, adapter,
                 str(number), "--lock-fd", str(fd)], pass_fds=(fd,),
                stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True, cwd=BACKEND_DIR)

    def owns_training(self, job_id, number):
        return (job_id,number) in self.training

    def training_exit(self, job_id, number):
        proc = self.training.get((job_id,number))
        return proc.poll() if proc else None

    def stop_training(self, job_id, number):
        proc = self.training.get((job_id,number))
        if proc and proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

    @staticmethod
    def attempt_lock_held(directory):
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
        return self.attempt_lock_held(self.root / "decisions" / key)

    def start_research(self, key):
        directory = self.root / "decisions" / key
        directory.mkdir(parents=True, exist_ok=True)
        with (directory / "worker.log").open("ab") as log:
            self.research[key] = subprocess.Popen(
                [sys.executable, str(BACKEND_DIR/"app.py"), "--state", str(self.root), "--worker", key],
                stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True,
            )

    def run(self, key):
        subprocess.run([sys.executable, str(BACKEND_DIR/"app.py"), "--state", str(self.root), "--worker", key],
                       check=True, timeout=30)


def run_training_attempt(root, workspace, job_id, adapter="beans", number=0, lock_fd=None):
    job = attempt_dir(root,job_id,number)
    job.mkdir(parents=True,exist_ok=True)
    receipt = job/"result.json"
    with (job / "lock").open("a") if lock_fd is None else nullcontext() as lock:
        if lock_fd is None:
            lock_fd = lock.fileno()
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return
        if receipt.exists():
            return
        started=time.time()
        try:
            if adapter == "local-project":
                store = WorkspaceStore(root)
                with store.tx(readonly=True) as db:
                    row = store.get(db, "job", job_id)
                if not row or row["workspace"] != workspace or row["adapter"] != adapter:
                    raise ValueError("Configured job does not match the dispatched attempt")
                env, candidate = row["environment"], row["candidate"]
                candidate_tree, evaluation_tree = job / "candidate", job / "evaluation"
                clone(candidate["checkout"], candidate_tree, candidate["revision"])
                clone(env["repo"], evaluation_tree, env["source_revision"])
                result = evaluate(env, candidate_tree, job, evaluation_tree, lock_fd=lock_fd)
            else:
                from compat.training import evaluate_benchmark
                result, diagnostics = evaluate_benchmark(root, workspace, job_id, adapter)
            payload={"metrics":result,"started_at":started,"ended_at":time.time()}
            if adapter == "name-llm":
                payload["diagnostics"] = diagnostics
        except Exception as exc:
            print(type(exc).__name__,flush=True)
            payload={"error":type(exc).__name__,"started_at":started,"ended_at":time.time()}
        write_json(receipt, payload)


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("root",type=Path)
    parser.add_argument("workspace")
    parser.add_argument("job")
    parser.add_argument("adapter",choices=("beans","name-llm","local-project"),nargs="?",default="beans")
    parser.add_argument("number",type=int,nargs="?",default=0)
    parser.add_argument("--lock-fd", type=int)
    args = parser.parse_args()
    if args.adapter != "local-project":
        signal.alarm(TRAINING_TIMEOUT)
    run_training_attempt(args.root, args.workspace, args.job, args.adapter, args.number, args.lock_fd)
