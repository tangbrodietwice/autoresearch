"""Unseen regression repository, real train/evaluate commands, fixture model."""
import json
import os
from pathlib import Path
import tempfile
import time
from execution.isolation import isolation_available
from execution.local_process import LocalProcessRunner
import unittest
from unittest.mock import patch

from execution.scheduler import TaskManager
from storage import WorkspaceStore
from worker_entrypoint import ResearchWorker
from workspace import WorkspaceAPI
from research.project_runner import git
from run_artifacts import recover_results, write_json


class LocalRegression(unittest.TestCase):
    @unittest.skipUnless(isolation_available(), "requires macOS isolated execution")
    def test_two_model_led_rounds_survive_reopening_the_workspace(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "unseen"
            repo.mkdir()
            git(repo, "init", "-q")
            (repo / "model.py").write_text("prediction = 0\n")
            host_file = root / "host-only.txt"
            host_file.write_text("host data")
            (repo / "train.py").write_text(
                "import os, time\nfrom pathlib import Path\nfrom model import prediction\n"
                "assert 'TRIPSCI_TEST_HOST_SECRET' not in os.environ\n"
                f"host_file = Path({str(host_file)!r})\n"
                "for op in (host_file.read_text, lambda: host_file.write_text('bad')):\n"
                "    try: op()\n"
                "    except PermissionError: pass\n"
                "    else: raise AssertionError('host file accessible')\n"
                "time.sleep(.25)\n"
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
            project = WorkspaceStore(root / "state")
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
            recovered_running = False
            launched_processes = []
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

            def tick_until(status):
                nonlocal recovered_running
                manager = TaskManager(project)
                runtime = LocalProcessRunner(project.root)
                for _ in range(200):
                    with patch.object(runtime, "start_research", side_effect=ResearchWorker(project).run):
                        manager.tick(runtime)
                    with project.tx(readonly=True) as db:
                        task = project.get(db, "task", key)
                        if task["status"] == status:
                            return
                        if task["status"] == "failed":
                            break
                    if runtime.training and not recovered_running:
                        # A new scheduler has no Popen handles and must honor the on-disk lease.
                        launched_processes.extend(runtime.training.values())
                        recovered_running = True
                        runtime = LocalProcessRunner(project.root)
                    for process in runtime.training.values():
                        if process not in launched_processes:
                            launched_processes.append(process)
                    time.sleep(.05)
                for log in project.root.glob("runs/*/attempts/*/*.log"):
                    print(log, log.read_text(errors="replace"))
                self.fail(f"Plan did not reach {status}: {task.get('failure')}")

            with patch("agents.worker.run_json", side_effect=model), patch.dict(os.environ, TRIPSCI_TEST_HOST_SECRET="test only"):
                tick_until("failed")
                project = WorkspaceStore(root / "state")
                recover_results(project)
                action("retry", id=plan["id"])
                tick_until("completed")
            for process in launched_processes:
                process.wait(timeout=5)
            self.assertTrue(recovered_running)
            self.assertEqual(host_file.read_text(), "host data")
            self.assertEqual(len(calls), 2)
            self.assertIn('"rmse": 7.0', calls[1])
            self.assertEqual(git(repo, "rev-parse", "HEAD"), source_revision)
            self.assertEqual((repo / "model.py").read_text(), "prediction = 0\n")
            with project.tx(readonly=True) as db:
                experiments = sorted(project.all(db, "experiment"), key=lambda r: r["round"])
                state = api.state(db)
                jobs = [project.get(db, "job", row["job"]) for row in experiments]
                agent_runs = project.all(db, "agent_run")
            self.assertEqual([r["status"] for r in agent_runs],
                             ["completed", "failed", "completed", "completed", "completed"])
            self.assertTrue(all(r["profile_version"] == agent["version"] for r in agent_runs))
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

    def test_pause_wins_over_in_flight_stop_proposal(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = WorkspaceStore(Path(tmp))
            manager = TaskManager(store)
            with store.tx() as db:
                task_id = manager.create(db, "Pause a proposal", 2)
                task = store.get(db, "task", task_id)
                task.update(environment={"adapter": "local-project"}, workspace="project")
                store.put(db, "task", task_id, task)

            def propose_stop(*_):
                with store.tx() as db:
                    manager.feedback(db, task_id, "pause")
                return {"action": "stop", "rationale": "fixture", "expected": "fixture"}

            with patch("research.workflow.context"), patch("research.workflow.candidate", side_effect=propose_stop):
                ResearchWorker(store).run(task_id)
            with store.tx(readonly=True) as db:
                self.assertEqual(store.get(db, "task", task_id)["status"], "paused")

    def test_configured_and_benchmark_jobs_share_slots(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = WorkspaceStore(Path(tmp))
            manager = TaskManager(store)
            runtime = LocalProcessRunner(store.root)
            launched = []
            with store.tx() as db:
                store.put(db, "settings", "active", {"slots": 1})
                for adapter in ("local-project", "beans"):
                    task_id = manager.create(db, adapter, 1)
                    task = store.get(db, "task", task_id)
                    task.update(status="waiting", workspace="project", pending_job=adapter)
                    store.put(db, "task", task_id, task)
                    store.put(db, "job", adapter, {"id": adapter, "adapter": adapter, "attempts": [],
                                                  "ready_at": 0, "retry_from": 0})
            with patch.object(runtime, "launch_training", side_effect=lambda *args: launched.append(args)):
                manager.tick(runtime)
            self.assertEqual([row[2] for row in launched], ["local-project"])
            with store.tx(readonly=True) as db:
                self.assertEqual(store.get(db, "job", "beans")["attempts"][0]["state"], "dispatch_pending")

    def test_legacy_receipt_is_imported_without_retraining(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = WorkspaceStore(Path(tmp))
            manager = TaskManager(store)
            with store.tx() as db:
                task_id = manager.create(db, "Resume old result", 1, baseline={"rmse": 10},
                                         constraints={"primary_metric": "rmse"})
                task = store.get(db, "task", task_id)
                env = {"adapter": "local-project", "source_revision": "original", "data_sha256": "hash",
                       "commands": {}, "seed": 1, "primary_metric": "rmse", "metric_direction": "min", "version": 1}
                task.update(environment=env, workspace="project", plan="plan", baseline_metrics={"rmse": 10})
                store.put(db, "task", task_id, task)
                job_id = f"{task_id}-1"
                receipt = f"runs/{job_id}/attempts/1/receipt.json"
                store.put(db, "job", job_id, {"id": job_id, "adapter": "local-project",
                                             "attempts": [{"number": 1, "state": "running", "receipt": receipt}]})
            write_json(store.root / receipt, {"rmse": 7})
            proposal = {"action": "run", "revision": "candidate", "checkout": "/fixture",
                        "hypothesis": "smaller error", "expected": "lower RMSE"}
            analysis = {"conclusion": "smaller error", "expectation": "met", "next_step": "stop"}
            with patch("research.workflow.context"), patch("research.workflow.candidate", return_value=proposal), \
                    patch("research.workflow.ask", return_value=analysis):
                ResearchWorker(store).run(task_id)
            with store.tx(readonly=True) as db:
                job = store.get(db, "job", job_id)
                self.assertEqual([(a["number"], a["state"]) for a in job["attempts"]], [(1, "succeeded")])
                self.assertEqual(store.get(db, "experiment", job_id)["result"], {"rmse": 7})
