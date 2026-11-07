"""Run against the same frontend origin as the browser."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from contextlib import ExitStack
from urllib.error import HTTPError
from urllib.request import Request, urlopen

root=Path(__file__).resolve().parents[1]

def serve(stack,*args):
    p=subprocess.Popen([sys.executable,*args],cwd=root,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True)
    def stop():
        p.terminate()
        p.wait(timeout=8)
        p.stdout.close()
    stack.callback(stop)
    url=p.stdout.readline().strip()
    assert url.startswith("http://"),args
    return url

with ExitStack() as stack:
    state=stack.enter_context(tempfile.TemporaryDirectory())
    backend=serve(stack,"backend/app.py","--state",state,"--port","0")
    web=serve(stack,"frontend/serve.py","--port","0","--backend-port",backend.rsplit(":",1)[1])
    def fetch(path,data=None):
        req=Request(web+path,data=json.dumps(data).encode() if data is not None else None,
                    headers={"Content-Type":"application/json"})
        with urlopen(req,timeout=8) as r:
            return r.read(),r.headers.get_content_type()
    def post(op,**data): return json.loads(fetch("/v1/action",dict(data,op=op))[0])
    assert b'/workspace.js' in fetch("/")[0]
    assert b'/v1/action' in fetch("/workspace.js")[0]
    assert fetch("/TripSci-icon.png")[1]=="image/png"
    assert json.loads(fetch("/v1/state")[0])["workspace"]==[]
    post("settings",delay=.3,slots=1)
    tool=post("tool",name="Iris docs",kind="link",target="https://archive.ics.uci.edu/dataset/53/iris")
    skill=post("skill",name="Accuracy guard",markdown="# Review accuracy")
    agent=post("agent",name="Reviewer",instructions="# Reviewer",skills=["adaptive-ctr",skill["id"]])
    data=json.loads(fetch("/v1/state")[0])
    assert data["tool"][0]["id"]==tool["id"]
    assert any(r["id"]=="local-process" and r["executable"] for r in data["runtimes"])
    assert agent["skill_files"][0]["markdown"]=="# Review accuracy"
    assert (Path(state)/agent["instructions_path"]).read_text().strip()=="# Reviewer"
    chat=post("message",text="讨论低频 CTR")
    plan=post("plan",title="低频 CTR",direction="验证平滑",source=chat["id"])
    assert plan["workspace"]==""
    project=post("workspace",name="CTR",repo="mock",baseline="v1",dataset="mock-v1",train="mock",evaluate="mock",mode="hybrid",training_host="gpu",delivery="git",floor=.715)
    post("attach",id=plan["id"],workspace=project["id"])
    post("start",id=plan["id"],budget=2)
    for _ in range(100):
        data=json.loads(fetch("/v1/state")[0])
        if data["task"][0]["status"]=="completed": break
        time.sleep(.1)
    assert len(data["experiment"])==2
    assert post("decision",id=plan["id"],value="保留候选")["decision"]=="保留候选"
    assert json.loads(fetch("/v1/state")[0])["plan"][0]["decision"]=="保留候选"
    print("PASS Web origin: assets, chat → unassigned draft → project → two experiments → decision")

    assert not json.loads(fetch("/v1/state")[0])["integration"]
    other=post("plan",title="补充 CTR 研究",direction="对照另一组设定",workspace=project["id"])
    post("start",id=other["id"],budget=1)
    for _ in range(100):
        data=json.loads(fetch("/v1/state")[0])
        item=next(t for t in data["task"] if t["plan"]==other["id"])
        if item["status"]=="completed": break
        time.sleep(.1)
    post("decision",id=other["id"],value="保留候选")
    payload=dict(workspace=project["id"],revision="a"*40,plans=[plan["id"],other["id"]],
                 metrics={"low_freq_auc":.68,"overall_auc":.72},summary="合并版本的固定协议评测")
    combined=post("integration",**payload)
    assert combined["ordinal"]==1 and len(combined["plans"])==2 and combined["metrics"]==payload["metrics"]
    for attempt in (payload,{**payload,"revision":"b"*40,"metrics":{"overall_auc":.72}}):
        try: post("integration",**attempt)
        except HTTPError as e: assert e.code==400
        else: raise AssertionError("invalid integration accepted")
    assert len(json.loads(fetch("/v1/state")[0])["integration"])==1
    print("PASS Project integration: candidate runs do not affect the trend; combined evaluation is recorded once with both sources")

    subprocess.run([sys.executable,"scripts/run-iris.py","--url",web],cwd=root,check=True,stdout=subprocess.DEVNULL)
    result=json.loads(fetch("/v1/state")[0])
    iris=next(p for p in result["plan"] if p["title"]=="改进 Iris 分类器")
    assert iris["decision"]=="不采用" and iris["holdout"]["baseline"]["accuracy"]<1
    assert len([x for x in result["experiment"] if x["task"]==iris["task"]])==6
    print("PASS Web origin: tool, Skill, runtime discovery, agent Markdown, and six actual Iris experiments")
