"""Use the public TripSci HTTP API, not direct training calls."""
import argparse
import json
import time
from urllib.request import Request, urlopen

parser=argparse.ArgumentParser()
parser.add_argument("--url",default="http://127.0.0.1:8766")
args=parser.parse_args()
def request(path,body=None):
    req=Request(args.url+path,data=json.dumps(body).encode() if body else None,headers={"Content-Type":"application/json"})
    with urlopen(req,timeout=10) as r: return json.load(r)
def post(op,**kw): return request("/v1/action",dict(op=op,**kw))
plan=post("import_iris")
if not plan["task"]:
    plan=post("start",id=plan["id"],budget=6)
for _ in range(200):
    state=request("/v1/state")
    task=next(t for t in state["task"] if t["id"]==plan["task"])
    if task["status"]=="completed": break
    time.sleep(.15)
else:
    raise SystemExit("Iris plan did not complete")
if not plan["decision"]:
    plan=post("decision",id=plan["id"],value="保留候选" if "revision" in task["best"] else "不采用")
experiments=[e for e in state["experiment"] if e["task"]==task["id"]]
assert len(experiments)==6 and all("macro_f1" in e["result"] for e in experiments)
print(json.dumps({"plan":plan["id"],"workspace":plan["workspace"],"decision":plan["decision"],"holdout":plan.get("holdout"),"experiments":[{k:e[k] for k in ("round","k","scale","result","accepted","revision")} for e in experiments]},ensure_ascii=False,indent=2))
