import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from app import MockTraining, Project, ResearchWorker, RuntimeAdapter, TaskManager

ROOT = Path(__file__).resolve().parent


class ResearchTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)

    def test_worker_failure_stops_until_retry(self):
        from native_api import WorkspaceAPI
        p = Project(self.root)
        manager = TaskManager(p)
        api = WorkspaceAPI(p, manager)

        class BrokenRuntime:
            def run(self, key):
                raise subprocess.CalledProcessError(1, "worker")

        with p.tx() as db:
            key = manager.create(db, "验证失败后恢复", 1)
            api.put(db, "plan", {"id": "test-plan", "task": key})
        manager.tick(BrokenRuntime())
        with p.tx() as db:
            task = p.get(db, "task", key)
            self.assertEqual((task["status"], task["round"]), ("failed", 0))
        manager.tick(RuntimeAdapter(self.root))
        with p.tx() as db:
            self.assertEqual(p.get(db, "task", key)["status"], "failed")
            api.action(db, {"op": "retry", "id": "test-plan"})
        manager.tick(RuntimeAdapter(self.root))
        with p.tx() as db:
            task = p.get(db, "task", key)
            self.assertEqual((task["status"], task["round"]), ("waiting", 1))
            self.assertNotIn("failure", task)

    def test_rollback_recovers_revision_after_other_plan_advances_head(self):
        project = Project(self.root)
        worker = ResearchWorker(project)
        with project.tx() as db:
            first = worker.manager.create(db,"first plan",1)
            second = worker.manager.create(db,"second plan",1)
        project.write("unrelated.txt","Keep this out of the artifact commit")
        project.git("add","unrelated.txt")
        with patch.object(MockTraining,"submit",side_effect=OSError("injected submit failure")):
            with self.assertRaises(OSError):
                worker.run(first)
        prepared = project.git("rev-parse","HEAD")
        worker.run(second)
        worker.run(first)
        with project.tx() as db:
            job = project.get(db,"job",first+"-1")
        self.assertEqual(job["revision"],prepared)
        self.assertEqual(project.git("show","--format=","--name-only",prepared),f"models/{first}-1.py")
        self.assertEqual(project.git("diff","--cached","--name-only"),"unrelated.txt")

    def test_report_commit_recovers_after_database_rollback(self):
        project = Project(self.root)
        worker = ResearchWorker(project)
        with project.tx() as db:
            first = worker.manager.create(db,"first plan",1)
            second = worker.manager.create(db,"second plan",1)
        for key in (first,second):
            worker.run(key)
        with project.tx() as db:
            for key in (first,second):
                task = project.get(db,"task",key)
                job = project.get(db,"job",task["pending_job"])
                job["result"] = MockTraining.poll(job,job["ready_at"])
                project.put(db,"job",job["id"],job)
                task["status"] = "ready"
                project.put(db,"task",key,task)
        original_put = project.put

        def fail_experiment(db,kind,key,value):
            if kind=="experiment":
                raise OSError("injected database write failure")
            original_put(db,kind,key,value)

        with patch.object(project,"put",side_effect=fail_experiment):
            with self.assertRaises(OSError):
                worker.run(first)
        revision = project.git("rev-parse","HEAD")
        worker.run(second)
        worker.run(first)
        with project.tx() as db:
            record = project.get(db,"experiment",first+"-1")
        self.assertEqual(record["report_commit"],revision)
        self.assertIn(record["revision"],project.git("show",revision+":"+record["report"]))
        from run_workspace import recover_results
        directory = self.root / record["run_path"]
        (directory / "result.json").unlink()
        (directory / "report.md").unlink()
        recover_results(project)
        self.assertEqual(json.loads((directory / "result.json").read_text()), record)
        self.assertIn(record["revision"], (directory / "report.md").read_text())

    def test_training_attempt_failures_are_isolated_and_bounded(self):
        from run_workspace import attempt_dir
        project = Project(self.root)
        manager = TaskManager(project)
        manager.training_retry_delay = 0
        manager.training_timeout = .1
        manager.max_training_attempts = 4

        class BrokenRuntime(RuntimeAdapter):
            def launch_training(self, workspace, job_id, adapter, number):
                if number==1:
                    raise OSError(2,"injected launch failure")
                directory=attempt_dir(self.root,job_id,number)
                directory.mkdir(parents=True)
                if number==2:
                    (directory/"result.json").write_text("{broken")
                else:
                    command = ("import time; time.sleep(30)" if number==3 else
                               "import os, signal; os.kill(os.getpid(),signal.SIGKILL)")
                    self.training[job_id,number]=subprocess.Popen([sys.executable,"-c",command])

        with project.tx() as db:
            failed = manager.create(db,"local training",1)
            healthy = manager.create(db,"unrelated mock",1)
            task = project.get(db,"task",failed)
            task.update(status="waiting",workspace="test",pending_job="broken-1")
            task["constraints"].update(primary_metric="macro_f1",guardrail_metric="accuracy")
            manager.save(db,task,"Test job")
            project.put(db,"job","broken-1",{"id":"broken-1","adapter":"beans","ready_at":0})
        runtime=BrokenRuntime(self.root)
        try:
            for _ in range(10):
                manager.tick(runtime)
                time.sleep(.12)
        finally:
            runtime.stop_training("broken-1",3)
        with project.tx() as db:
            task=project.get(db,"task",failed)
            self.assertEqual(task["status"],"failed")
            self.assertEqual(task["failure_stage"],"training")
            self.assertEqual([a["error_code"] for a in project.get(db,"job","broken-1")["attempts"]],
                             ["launch_failed","invalid_receipt","timeout","missing_receipt"])
            self.assertIn(project.get(db,"task",healthy)["status"],("waiting","completed"))
        self.assertTrue((attempt_dir(self.root,"broken-1",2)/"result.json").exists())

    def test_research_uses_history_and_records_agent_analysis(self):
        from research import planner
        project = Project(self.root)
        worker = ResearchWorker(project)
        with project.tx() as db:
            key = worker.manager.create(db,"Study smoothing",2)
            task = project.get(db,"task",key)
            task["research_mode"] = "codex"
            project.put(db,"task",key,task)

        seen = []
        def fake_decision(root, context):
            seen.append(context)
            result = context["result"]
            proposal = None
            if context["round"] < context["budget"]:
                proposal = dict(strength=.25 + .1*context["round"],hypothesis="Smoothing helps",
                                expected="Higher low-frequency AUC",disconfirming_result="No improvement",
                                rationale="Compare against the previous run",history_refs=[result["id"]] if result else [])
            analysis = dict(observations="Measured change",alternative_explanation="Synthetic metric response",
                            next_step="Check neighboring strength",level="inconclusive") if result else None
            decision = dict(proposal=proposal,analysis=analysis)
            planner.validate(decision,context)
            return decision

        with patch.object(planner,"decide",side_effect=fake_decision):
            for round_no in range(3):
                worker.run(key)
                if round_no < 2:
                    with project.tx() as db:
                        task = project.get(db,"task",key)
                        job = project.get(db,"job",task["pending_job"])
                        job["result"] = MockTraining.poll(job,job["ready_at"])
                        project.put(db,"job",job["id"],job)
                        task["status"] = "ready"
                        project.put(db,"task",key,task)
                        if round_no==0:
                            worker.manager.feedback(db,key,"请检查替代解释")
        with project.tx(readonly=True) as db:
            experiments = project.all(db,"experiment")
            self.assertEqual(project.get(db,"task",key)["status"],"completed")
        self.assertEqual(len(experiments),2)
        self.assertEqual(experiments[1]["research_proposal"]["history_refs"],[experiments[0]["id"]])
        self.assertEqual(experiments[1]["research_analysis"]["level"],"inconclusive")
        self.assertEqual(seen[1]["feedback"][0]["message"],"请检查替代解释")
        invalid = fake_decision(self.root,seen[1])
        invalid["proposal"]["strength"] = .25
        with self.assertRaises(ValueError):
            planner.validate(invalid,seen[1])

    def test_paused_task_defers_pending_dispatch_and_reuses_attempt(self):
        project = Project(self.root)
        manager = TaskManager(project)
        launched = []

        class RecordingRuntime(RuntimeAdapter):
            def launch_training(self, workspace, job_id, adapter, number):
                launched.append((job_id, number))

        with project.tx() as db:
            key = manager.create(db, "Verify dispatch recovery", 1)
            task = project.get(db, "task", key)
            task.update(status="paused", workspace="local", pending_job="job-1")
            manager.save(db, task, "Paused before dispatch")
            project.put(db, "job", "job-1", {"id":"job-1", "adapter":"beans", "ready_at":0,
                        "attempts":[{"number":1,"state":"dispatch_pending","requested_at":0}]})
        manager.tick(RecordingRuntime(self.root))
        self.assertEqual(launched, [])
        with project.tx() as db:
            manager.feedback(db, key, "resume")
        manager.tick(RecordingRuntime(self.root))
        self.assertEqual(launched, [("job-1", 1)])
        with project.tx(readonly=True) as db:
            attempts = project.get(db, "job", "job-1")["attempts"]
        self.assertEqual(len(attempts), 1)
        self.assertEqual(attempts[0]["state"], "running")

    def test_candidate_paths_reject_protected_files_and_symlink_escape(self):
        from storage import CONSTRAINTS
        project = Project(self.root)
        outside = self.root / "outside"
        outside.mkdir()
        (project.repo / "models").symlink_to(outside, target_is_directory=True)
        for path in ("models/run.py", "models/../outside.py", "evaluation/protocol.json"):
            with self.assertRaises(ValueError):
                project.validate_candidate_path(path, CONSTRAINTS)
        self.assertFalse(any(outside.iterdir()))

    def test_contract_and_mock(self):
        p = Project(self.root)
        with p.tx() as db:
            for budget in [0, 11, True, '3']:
                with self.assertRaises(ValueError):
                    TaskManager(p).create(db, 'CTR', budget)
        job = MockTraining.submit('job', 'revision', .5, 1)
        self.assertIsNone(MockTraining.poll(job, job['ready_at']-.1))
        self.assertEqual(MockTraining.poll(job, job['ready_at']), MockTraining.poll(job, job['ready_at']+10))
        self.assertNotEqual(ResearchWorker.propose({'strength': .2}, [.2,.5], False),
                            ResearchWorker.propose({'strength': .5}, [.2,.5], False))

    def test_worker_and_repository(self):
        p = Project(self.root)
        m = TaskManager(p)
        with p.tx() as db:
            p.put(db,'settings','active',{'runtime':'local-process','skills':['adaptive-ctr','wide-search'],'delay':.1})
            key = m.create(db, 'CTR', 10)
        m.tick(RuntimeAdapter(self.root))
        with p.tx() as db:
            self.assertEqual(p.get(db,'task',key)['status'],'waiting')
            m.feedback(db, key, '保守')
        for _ in range(10):
            time.sleep(.12)
            m.tick(RuntimeAdapter(self.root))
        with p.tx() as db:
            records = p.all(db,'experiment')
            self.assertEqual(len(records),10)
            self.assertEqual(len({r['strength'] for r in records}),10)
            self.assertTrue(all(r['strength']<=.65 for r in records))
            self.assertTrue(p.all(db,'inbox')[0]['consumed'])
            self.assertEqual(p.get(db,'task',key)['status'],'completed')
        for e in records:
            self.assertIn('Decision',p.git('show',f"{e['report_commit']}:{e['report']}"))
            self.assertIn('def smooth',p.git('show',f"{e['revision']}:models/{e['id']}.py"))
        self.assertEqual(p.git('status','--porcelain'),'')

    def test_http_and_restart(self):
        def stop(proc):
            if proc.poll() is None:
                proc.kill()
            proc.wait()
            proc.stdout.close()

        def start():
            proc = subprocess.Popen([sys.executable,str(ROOT.parent/'chat_fixture_server.py'),'--state',str(self.root),'--port','0'],
                                    stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True)
            self.addCleanup(stop,proc)
            address = proc.stdout.readline().strip()
            self.assertTrue(address.startswith('http://'), 'Local HTTP server did not start')
            def api(path, data=None):
                req = Request(address+path, data=None if data is None else json.dumps(data).encode(),
                              headers={'Content-Type':'application/json'})
                with urlopen(req,timeout=5) as response:
                    return json.load(response)
            return proc, api

        def until(fn):
            for _ in range(150):
                value = fn()
                if value:
                    return value
                time.sleep(.1)
            self.fail('Timed out waiting for expected state')

        proc, api = start()
        with self.assertRaises(HTTPError) as legacy:
            api('/api/chat', {'action':'delegate','message':'提升低频 CTR','budget':3})
        self.assertEqual(legacy.exception.code, 410)
        with self.assertRaises(HTTPError) as legacy:
            api('/api/settings', {'delay':.1})
        self.assertEqual(legacy.exception.code, 410)
        workspace = api('/v1/action', dict(op='workspace', name='CTR', repo='fixture', baseline='v1',
                                          dataset='synthetic-v1', train='train.py', evaluate='eval.py',
                                          mode='local', floor=.715))
        plan = api('/v1/action', dict(op='plan', title='CTR', direction='提升低频 CTR', workspace=workspace['id']))
        api('/v1/action', dict(op='start', id=plan['id'], budget=3))
        state = lambda: api('/v1/state')
        current = lambda: state()['task'][0]
        job = until(lambda: current()['pending_job'])
        api('/v1/action', dict(op='pause', id=plan['id']))
        self.assertEqual(current()['status'],'paused')
        reply = api('/v1/action', dict(op='message', plan=plan['id'], text='进展？'))
        self.assertIn('paused', reply['messages'][-1]['text'])
        api('/v1/action', dict(op='resume', id=plan['id']))
        self.assertEqual(current()['pending_job'],job)
        stop(proc)
        _, api = start()
        until(lambda: current()['status']=='completed')
        result = state()
        self.assertEqual([x['round'] for x in result['experiment']],[1,2,3])
        self.assertEqual(result['experiment'][0]['id'],job)
        self.assertEqual([m['role'] for m in result['plan'][0]['messages'] if m['role'] in ('user','agent')], ['user','agent'])
        self.assertTrue(all(x['consumed'] for x in result['inbox']))
