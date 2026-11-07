import json
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen


class NativeAPI(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.start()

    def stop(self):
        if self.proc.poll() is None:
            self.proc.kill()
        self.proc.wait()
        self.proc.stdout.close()

    def start(self):
        proc = subprocess.Popen([sys.executable,str(Path(__file__).with_name("app.py")),
                                 "--state",str(self.root),"--port","0"], stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL,text=True)
        self.proc = proc
        self.addCleanup(proc.stdout.close)
        def cleanup():
            if proc.poll() is None: proc.kill()
            proc.wait()
        self.addCleanup(cleanup)
        self.url = proc.stdout.readline().strip()
        self.assertTrue(self.url.startswith("http://"))

    def api(self, action=None, **args):
        req = Request(self.url+("/v1/action" if action else "/v1/state"),
                      data=json.dumps(dict(args,op=action)).encode() if action else None,
                      headers={"Content-Type":"application/json"})
        with urlopen(req,timeout=8) as response:
            return json.load(response)

    def wait(self, predicate):
        end=time.monotonic()+15
        while time.monotonic()<end:
            state=self.api()
            if predicate(state): return state
            time.sleep(.07)
        self.fail("condition timed out")

    def workspace(self, mode="local", **opts):
        params=dict(name="CTR",repo="example",baseline="v1",dataset="sim-v2",train="train.py",
                    evaluate="eval.py",floor=.73,mode=mode)
        params.update(opts)
        return self.api("workspace",**params)

    def test_modes_chat_and_contracts(self):
        draft=self.api("plan",title="低频研究",direction="验证平滑")
        with self.assertRaises(HTTPError):
            self.api("start",id=draft["id"],budget=3)
        for mode, opts in [("local",{}),("hybrid",{"training_host":"gpu","delivery":"git"}),
                           ("remote",{"agent_host":"worker","remote_dir":"/scratch"})]:
            env=self.workspace(mode,**opts)
            self.assertEqual(env["adapter"],"mock")
            self.assertEqual(env["mode"],mode)
        with self.assertRaises(HTTPError):
            self.workspace("hybrid")
        chat=self.api("message",text="项目进度")
        chat=self.api("message",thread=chat["id"],text="生成 Skill")
        self.assertEqual(len(chat["messages"]),4)
        plan=self.api("plan",title="From chat",direction="复验 CTR",source=chat["id"])
        self.assertIn("来源聊天",plan["messages"][0]["text"])
        self.api("message",plan=plan["id"],text="请解释下一轮怎么跑")
        self.assertFalse(self.api()["inbox"])
        agent=self.api("agent",name="专用 Worker",instructions="初版")
        self.assertEqual(len(self.api()["agent"]),2)
        remote=self.api()["workspace"][-1]
        self.api("attach",id=plan["id"],workspace=remote["id"])
        started=self.api("start",id=plan["id"],budget=1,agent=agent["id"],baseline="override")
        self.api("agent",id=agent["id"],name=agent["name"],instructions="新版")
        self.workspace("remote",id=remote["id"],agent_host="other",remote_dir="/new",floor=.1)
        out=self.wait(lambda d: bool(d["experiment"]))
        task=next(t for t in out["task"] if t["id"]==started["task"])
        self.assertEqual(task["baseline"],"override")
        self.assertEqual(task["agent"]["instructions"],"初版")
        self.assertEqual(task["environment"]["agent_host"],"worker")
        record=out["experiment"][0]
        self.assertFalse(record["accepted"])
        self.assertFalse(record["guardrail_passed"])
        self.assertEqual(record["dataset"],"sim-v2")
        self.assertTrue((self.root/"projects"/remote["id"]/record["report"]).exists())
        with self.assertRaises(HTTPError):
            self.api("decision",id=plan["id"],value="保留候选")
        self.assertEqual(self.api("decision",id=plan["id"],value="不采用")["decision"],"不采用")

    def test_feedback_pause_restart_and_no_duplicates(self):
        self.api("settings",delay=1.5,slots=1)
        env=self.workspace("hybrid",training_host="gpu",delivery="git",floor=.715)
        plan=self.api("plan",workspace=env["id"],title="CTR",direction="平滑")
        self.api("start",id=plan["id"],budget=3)
        original=self.wait(lambda d: bool(d["job"]))["job"][0]["id"]
        self.api("pause",id=plan["id"])
        self.api("feedback",id=plan["id"],text="强度 0.55")
        self.api("feedback",id=plan["id"],text="保守")
        self.stop()
        self.start()
        self.assertEqual(self.api()["task"][0]["status"],"paused")
        self.assertEqual(self.api()["task"][0]["pending_job"],original)
        paused = self.wait(lambda d: bool(d["job"][0].get("result")))
        self.assertEqual(paused["task"][0]["status"],"paused")
        self.assertFalse(paused["experiment"])
        self.api("resume",id=plan["id"])
        out=self.wait(lambda d:d["task"][0]["status"]=="completed")
        self.assertEqual([e["round"] for e in out["experiment"]],[1,2,3])
        self.assertEqual(out["experiment"][0]["id"],original)
        self.assertEqual(out["experiment"][1]["strength"],.55)
        self.assertTrue(all(x["consumed"] for x in out["inbox"]))
        self.assertTrue(all(e["mode"]=="hybrid" for e in out["experiment"]))
