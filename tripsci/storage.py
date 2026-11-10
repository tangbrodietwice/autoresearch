"""Local SQLite records and path-scoped Git artifact commits."""
import contextlib
import json
from pathlib import Path
import sqlite3
import subprocess

from run_workspace import write_text


SEED = {"low_freq_auc": .65, "overall_auc": .72}
DEFAULT = {"runtime": "local-process", "skills": ["adaptive-ctr"], "delay": 1.5}
CONSTRAINTS = {"primary_metric": "low_freq_auc", "max_parallel_jobs": 1,
               "overall_auc_floor": .715, "editable_paths": ["models/"],
               "protected_paths": ["data/", "evaluation/"], "dataset": "synthetic-v1"}


class Project:
    def __init__(self, root):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.repo = self.root / "project"
        self.repo.mkdir(exist_ok=True)
        self.bootstrap()
        with self.tx() as db:
            db.execute("CREATE TABLE IF NOT EXISTS records (kind TEXT, id TEXT, body TEXT, PRIMARY KEY(kind,id))")
            if not self.get(db, "settings", "active"):
                self.put(db, "settings", "active", DEFAULT)

    def bootstrap(self):
        if (self.repo / ".git").exists() and self.git("rev-list", "--all", "--max-count=1"):
            return
        self.repo.mkdir(parents=True, exist_ok=True)
        self.git("init", "-q")
        files = {
            "data/synthetic-v1.json": [{"user": i, "frequency": 1+i%5, "click": i%3 == 0} for i in range(30)],
            "evaluation/protocol.json": CONSTRAINTS,
            "history.json": [{"name": "baseline", **SEED},
                             {"name": "historical heavy smoothing", "low_freq_auc": .646, "overall_auc": .719}],
        }
        for name, value in files.items():
            if not (self.repo / name).exists():
                self.write(name, value)
        if not self.git("rev-list", "--all", "--max-count=1"):
            self.commit("Bootstrap synthetic CTR project", *files)

    @contextlib.contextmanager
    def tx(self, readonly=False):
        db = sqlite3.connect(self.root / "state.sqlite", timeout=15)
        try:
            db.execute("BEGIN" if readonly else "BEGIN IMMEDIATE")
            with db:
                yield db
        finally:
            db.close()

    def artifact_path(self, name):
        relative = Path(name)
        root = self.repo.resolve()
        path = self.repo / relative
        if (relative.is_absolute() or not relative.parts or ".." in relative.parts
                or ".git" in relative.parts or path.resolve() != root / relative):
            raise ValueError(f"Invalid artifact path: {name}")
        return path

    def validate_candidate_path(self, name, constraints):
        self.artifact_path(name)
        path = Path(name)
        if any(path.is_relative_to(Path(prefix)) for prefix in constraints["protected_paths"]):
            raise ValueError(f"Candidate cannot modify protected path: {name}")
        if not any(path.is_relative_to(Path(prefix)) for prefix in constraints["editable_paths"]):
            raise ValueError(f"Candidate path is outside the allowed scope: {name}")

    def write(self, name, value):
        path = self.artifact_path(name)
        write_text(path, value if isinstance(value, str) else json.dumps(value, indent=2))

    def git(self, *args):
        return subprocess.check_output(["git", "-C", str(self.repo), "-c", "user.name=Research Worker",
                                        "-c", "user.email=worker@localhost", *args], text=True).strip()

    def commit(self, label, *paths):
        if not paths:
            raise ValueError("Artifact commit requires explicit paths")
        for path in paths:
            self.artifact_path(path)
        self.git("add", "--", *paths)
        if self.git("diff", "--cached", "--name-only", "--", *paths):
            self.git("commit", "--only", "-qm", label, "--", *paths)
            return self.git("rev-parse", "HEAD")
        expected = [self.git("hash-object", "--", path) for path in paths]
        for revision in self.git("log", "--format=%H", "--fixed-strings", "--grep="+label, "--", *paths).splitlines():
            if self.git("show", "-s", "--format=%s", revision) != label:
                continue
            try:
                blobs = [self.git("rev-parse", revision+":"+path) for path in paths]
            except subprocess.CalledProcessError:
                continue
            if blobs == expected:
                return revision
        raise RuntimeError(f"Cannot recover artifact revision for {label}")

    def archived(self, db, kind, row):
        if kind not in ("workspace", "plan"):
            return False
        if row.get("archived"):
            return True
        if kind == "plan" and row.get("workspace"):
            project = self.get(db, "workspace", row["workspace"])
            return bool(project and project.get("archived"))
        return False

    @staticmethod
    def put(db, kind, key, value):
        db.execute("INSERT INTO records VALUES (?,?,?) ON CONFLICT(kind,id) DO UPDATE SET body=excluded.body",
                   (kind, key, json.dumps(value, ensure_ascii=False)))

    @staticmethod
    def get(db, kind, key):
        row = db.execute("SELECT body FROM records WHERE kind=? AND id=?", (kind, key)).fetchone()
        return json.loads(row[0]) if row else None

    @staticmethod
    def all(db, kind):
        return [json.loads(row[0]) for row in db.execute("SELECT body FROM records WHERE kind=? ORDER BY rowid", (kind,))]
