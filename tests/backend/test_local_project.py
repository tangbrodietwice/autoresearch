"""Unseen regression repository, real train/evaluate commands, fixture model."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app import Project, ResearchWorker, TaskManager
from workspace_api import WorkspaceAPI
from research.project_runner import git
from run_workspace import recover_results


class LocalRegression(unittest.TestCase):
    def test_two_model_led_rounds_survive_reopening_the_workspace(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "unseen"
            repo.mkdir()
            git(repo, "init", "-q")
            (repo / "model.py").write_text("prediction = 0\n")
            (repo / "train.py").write_text(
                "import os\nfrom pathlib import Path\nfrom model import prediction\n"
                "Path(os.environ['TRIPSCI_RUN_DIR'], 'prediction').write_text(str(prediction))\n")
            (repo / "score.py").write_text(
                "import json, os\nfrom pathlib import Path\n"
                "prediction = float(Path(os.environ['TRIPSCI_RUN_DIR'], 'prediction').read_text())\n"
                "target = float(Path(os.environ['TRIPSCI_DATASET']).read_text())\n"
                "Path(os.environ['TRIPSCI_METRICS_PATH']).write_text(json.dumps({'rmse': abs(target - prediction)}))\n")
            data = root / "dataset.txt"
            data.write_text("10")
            git(repo, "add", ".")
            git(repo, "-c", "user.name=Test", "-c", "user.email=test@localhost", "commit", "-qm", "baseline")
            source_revision = git(repo, "rev-parse", "HEAD")
            project = Project(root / "state")
            api = WorkspaceAPI(project, TaskManager(project))

            def action(op, **data):
                with project.tx() as db:
                    return api.action(db, dict(op=op, **data))

            env = action("workspace", kind="local-project", name="Unseen regression", repo=str(repo),
                         dataset=str(data), baseline="v1", train="python3 train.py", evaluate="python3 score.py",
                         mode="local", primary_metric="rmse", metric_direction="min", baseline_value=10, seed=42)
            plan = action("plan", title="Reduce RMSE", direction="Test revised predictions", workspace=env["id"])
            with patch("execution.providers.codex.detect", return_value="/fixture/codex"):
                agent = action("agent", name="Regression worker", instructions="Choose from evidence", runtime="codex")
                plan = action("start", id=plan["id"], agent=agent["id"], budget=2)
            key = plan["task"]
            calls = []
            analysis_calls = 0
            def model(provider, prompt, schema, **options):
                nonlocal analysis_calls
                self.assertEqual(provider, "codex")
                checkout = options["workspace"]
                if checkout:
                    calls.append(prompt)
                    (checkout / "model.py").write_text(f"prediction = {len(calls) * 3}\n")
                    # The trusted evaluator must come from the baseline, not the candidate.
                    (checkout / "score.py").write_text("raise RuntimeError('candidate evaluator ran')\n")
                    return dict(action="run", hypothesis="Closer prediction", expected="lower RMSE", rationale="evidence")
                analysis_calls += 1
                if analysis_calls == 1:
                    raise ValueError("temporary analysis failure")
                return dict(conclusion="Error decreased", expectation="met", next_step="refine prediction")

            with patch("research.local_worker.run_json", side_effect=model):
                ResearchWorker(project).run(key)
                project = Project(root / "state")
                recover_results(project)
                action("retry", id=plan["id"])
                ResearchWorker(project).run(key)
                recover_results(project)
                ResearchWorker(project).run(key)
            self.assertEqual(len(calls), 2)
            self.assertIn('"rmse": 7.0', calls[1])
            self.assertEqual(git(repo, "rev-parse", "HEAD"), source_revision)
            self.assertEqual((repo / "model.py").read_text(), "prediction = 0\n")
            with project.tx(readonly=True) as db:
                experiments = sorted(project.all(db, "experiment"), key=lambda r: r["round"])
                state = api.state(db)
                jobs = [project.get(db, "job", row["job"]) for row in experiments]
            self.assertEqual([len(job["attempts"]) for job in jobs], [1, 1])
            self.assertEqual([job["attempts"][0]["state"] for job in jobs], ["succeeded", "succeeded"])
            self.assertEqual([job["result"]["rmse"] for job in jobs], [7.0, 4.0])
            self.assertEqual([r["result"]["rmse"] for r in experiments], [7.0, 4.0])
            self.assertTrue(all(r["accepted"] for r in experiments))
            self.assertEqual(state["plan"][0]["report"]["candidate"]["result"], {"rmse": 4.0})
            inputs = json.loads((project.root / experiments[0]["run_path"] / "inputs.json").read_text())
            self.assertEqual(inputs["seed"], 42)
            self.assertEqual(inputs["source_revision"], source_revision)
            self.assertEqual(inputs["data_sha256"], env["data_sha256"])
            action("decision", id=plan["id"], value="保留候选")
            integration = action("integration", workspace=env["id"], plans=[plan["id"]],
                                 revision=experiments[1]["revision"], metrics={"rmse": 4.0}, summary="merged evaluation")
            self.assertEqual(integration["metrics"], {"rmse": 4.0})
