import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from urllib.request import Request, urlopen

from app import MainAgent, MockTraining, Project, ResearchWorker, RuntimeAdapter, TaskManager

ROOT = Path(__file__).resolve().parent


class ResearchTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)

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
            main = MainAgent(m)
            key = main.reply(db, {'action':'delegate','message':'CTR','budget':10})['task']
        m.tick(RuntimeAdapter(self.root))
        with p.tx() as db:
            self.assertEqual(p.get(db,'task',key)['status'],'waiting')
            main.reply(db, {'action':'feedback','task':key,'message':'保守'})
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
            proc = subprocess.Popen([sys.executable,str(ROOT/'app.py'),'--state',str(self.root),'--port','0'],
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
        key = api('/api/chat',{'action':'delegate','message':'提升低频 CTR','budget':3})['task']
        state = lambda: api('/api/state')
        current = lambda: state()['task'][0]
        job = until(lambda: current()['pending_job'])
        api('/api/chat',{'action':'feedback','task':key,'message':'pause'})
        self.assertEqual(current()['status'],'paused')
        self.assertIn('paused',api('/api/chat',{'message':'进展？','task':key})['reply'])
        api('/api/chat',{'action':'feedback','task':key,'message':'resume'})
        self.assertEqual(current()['pending_job'],job)
        stop(proc)
        _, api = start()
        until(lambda: current()['status']=='completed')
        result = state()
        self.assertEqual([x['round'] for x in result['experiment']],[1,2,3])
        self.assertEqual(result['experiment'][0]['id'],job)
        self.assertEqual(len(result['chat']),8)
        self.assertTrue(all(x['consumed'] for x in result['inbox']))
