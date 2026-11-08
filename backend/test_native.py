import json
import sqlite3
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
        proc = subprocess.Popen([sys.executable,str(Path(__file__).resolve().parents[1]/"tests/chat_fixture_server.py"),
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

    def test_project_archive_preserves_files_and_linked_plan(self):
        project = self.workspace()
        plan = self.api("plan", title="保留研究", direction="验证归档", workspace=project["id"])
        self.api("archive_workspace", id=project["id"])
        state = self.api()
        self.assertEqual(state["workspace"], [])
        self.assertEqual(state["plan"], [])
        self.assertTrue((self.root / project["config_path"]).is_file())
        with sqlite3.connect(self.root / "state.sqlite") as db:
            saved = db.execute("SELECT body FROM records WHERE kind='plan' AND id=?", (plan["id"],)).fetchone()
        self.assertEqual(json.loads(saved[0])["workspace"], project["id"])
        with self.assertRaises(HTTPError):
            self.api("message", plan=plan["id"], text="继续研究")

    def test_supervisor_skill_proposal_and_reload(self):
        thread = self.api("message", text="fixture: supervisor skill")
        proposal = thread["messages"][-1]["proposal"]
        skill = self.api("confirm_supervisor", proposal_id=proposal["id"])
        supervisor = self.api()["agent"][0]
        self.assertEqual(supervisor["skills"], [skill["id"]])
        self.stop()
        self.start()
        reply = self.api("message", thread=thread["id"], text="fixture: active skills")
        self.assertEqual(reply["messages"][-1]["text"], skill["name"])
        self.api("agent_skills", id=supervisor["id"], skills=[])
        reply = self.api("message", thread=thread["id"], text="fixture: active skills")
        self.assertEqual(reply["messages"][-1]["text"], "无")

    def test_supervisor_proposal_requires_confirmation_and_is_idempotent(self):
        reply=self.api("message",text="fixture: propose project",request_key="supervisor-test-001")
        proposal=reply["messages"][-1]["proposal"]
        self.assertEqual(proposal["status"],"pending")
        self.assertEqual(self.api()["workspace"],[])
        self.assertFalse((self.root / "projects").exists())
        same=self.api("message",text="fixture: propose project",request_key="supervisor-test-001")
        self.assertEqual(same,reply)
        saved=self.api("confirm_supervisor",proposal_id=proposal["id"])
        self.assertEqual(self.api("confirm_supervisor",proposal_id=proposal["id"]),saved)
        directory = self.root / "projects" / saved["id"]
        self.assertEqual(saved["managed_dir"], str(directory.relative_to(self.root)))
        self.assertEqual(json.loads((directory / "config-v1.json").read_text()), saved)
        self.assertEqual(list(directory.parent.iterdir()), [directory])
        state=self.api()
        self.assertEqual(len(state["workspace"]),1)
        self.assertEqual(state["thread"][0]["messages"][-1]["proposal"]["status"],"applied")

    def test_manual_project_config_stays_in_the_managed_directory(self):
        project = self.workspace(name="../outside", managed_dir="../outside")
        updated = self.workspace(id=project["id"], name="New name")
        self.assertEqual(updated["managed_dir"], project["managed_dir"])
        self.assertEqual(updated["version"], 2)
        self.assertEqual(json.loads((self.root / updated["config_path"]).read_text()), updated)
        self.assertEqual(json.loads((self.root / project["config_path"]).read_text()), project)

    def test_chat_and_manual_actions_share_validation_and_plan_provenance(self):
        bad = self.api("message", text="fixture: invalid project")["messages"][-1]["proposal"]
        with self.assertRaises(HTTPError) as manual:
            self.api("workspace", **bad["payload"])
        with self.assertRaises(HTTPError) as chat:
            self.api("confirm_supervisor", proposal_id=bad["id"])
        self.assertEqual(chat.exception.read(), manual.exception.read())
        self.assertEqual(self.api()["workspace"], [])
        thread = self.api("message", text="fixture: propose plan")
        proposal = thread["messages"][-1]["proposal"]
        manual_plan = self.api("plan", source=thread["id"], **proposal["payload"])
        chat_plan = self.api("confirm_supervisor", proposal_id=proposal["id"])
        self.assertEqual({**manual_plan, "id": chat_plan["id"]}, chat_plan)

        settings = self.api("message", text="fixture: propose settings")["messages"][-1]["proposal"]
        self.assertNotEqual(self.api()["settings"]["delay"], settings["payload"]["delay"])
        manual_settings = self.api("settings", **settings["payload"])
        self.assertEqual(self.api("confirm_supervisor", proposal_id=settings["id"]), manual_settings)

    def test_legacy_supervisor_permissions_migrate(self):
        supervisor = self.api()["agent"][0]
        permissions = {**supervisor["permissions"], "web_search": False}
        self.stop()
        with sqlite3.connect(self.root / "state.sqlite") as db:
            db.execute("DELETE FROM records WHERE kind='agent' AND id=?", (supervisor["id"],))
            db.execute("INSERT INTO records VALUES (?,?,?)", ("agent_permissions", supervisor["id"],
                       json.dumps({"permissions":permissions})))
        self.start()
        self.assertEqual(self.api()["agent"][0]["permissions"], permissions)

    def test_builtin_agents_have_persisted_instructions(self):
        for agent in self.api()["agent"]:
            path = self.root / agent["instructions_path"]
            self.assertEqual(path.read_text().strip(), agent["instructions"].strip())
        before = self.api()["agent"]
        self.stop()
        self.start()
        self.assertEqual(self.api()["agent"], before)

    def test_supervisor_permissions_persist_and_revoke_pending_proposals(self):
        supervisor = self.api()["agent"][0]
        permissions = supervisor["permissions"]
        self.assertTrue(permissions["web_search"])
        response = self.api("message", text="fixture: propose project")
        proposal = response["messages"][-1]["proposal"]
        permissions.update(web_search=False, projects=False)
        self.api("agent_permissions", id=supervisor["id"], permissions={"projects":False})
        self.api("agent_permissions", id=supervisor["id"], permissions={"web_search":False})
        with self.assertRaises(HTTPError) as error:
            self.api("confirm_supervisor", proposal_id=proposal["id"])
        self.assertEqual(error.exception.code, 403)
        with self.assertRaises(HTTPError) as error:
            self.api("message", text="fixture: propose project")
        self.assertEqual(error.exception.code, 403)
        self.stop()
        self.start()
        self.assertEqual(self.api()["agent"][0]["permissions"], permissions)
        self.assertEqual(self.api()["workspace"], [])

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
        agents=self.api()["agent"]
        self.assertEqual(len(agents),3)
        supervisor=next(a for a in agents if a.get("role")=="supervisor")
        self.assertEqual((supervisor["id"],supervisor["runtime"]),("tripsci-supervisor","codex"))
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
