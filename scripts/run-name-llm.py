"""Run the competition experiment matrix through the TripSci API."""
import argparse
import json
from pathlib import Path
import time
from urllib.request import Request, urlopen


def run(url):
    def request(path,payload=None):
        req=Request(url.rstrip("/")+path,data=json.dumps(payload).encode() if payload is not None else None,
                    headers={"Content-Type":"application/json"})
        with urlopen(req,timeout=35) as res:
            return json.load(res)
    def post(op,**data):
        return request("/v1/action",{"op":op,**data})
    project=post("import_name_llm")
    specs=[("字符 n-gram","在隔离提示上比较 2–5 元字符片段。","char",4),
           ("文体与标点","比较文体特征与不同词频占比。","style",4),
           ("自由迭代 · 20 轮","根据上一轮和当前最优验证成绩，继续搜索词频、字符和文体权重。","adaptive",20)]
    existing={p["title"]:p for p in request("/v1/state")["plan"] if p["workspace"]==project["id"]}
    plans=[]
    for title,design,strategy,budget in specs:
        p=existing.get(title) or post("plan",title=title,direction=design,workspace=project["id"])
        plans.append(p)
    start=[dict(id=p["id"],strategy=spec[2],budget=spec[3],design=spec[1]) for p,spec in zip(plans,specs) if not p["task"]]
    if len(start)>1: post("start_batch",plans=start)
    elif start: post("start",**start[0])
    ids={p["id"] for p in plans}
    parallel=False
    deadline=time.monotonic()+600
    while time.monotonic()<deadline:
        state=request("/v1/state")
        tasks={t["plan"]:t for t in state["task"] if t.get("plan") in ids}
        parallel |= sum(t["status"]=="waiting" for t in tasks.values())>=2
        if any(t["status"]=="failed" for t in tasks.values()):
            raise RuntimeError([(t["plan"],t.get("failure")) for t in tasks.values() if t["status"]=="failed"])
        if len(tasks)==3 and all(t["status"]=="completed" for t in tasks.values()): break
        time.sleep(.35)
    else:
        raise TimeoutError("Plans are still running in TripSci.")
    out={"project":project,"parallel_observed":parallel,"plans":[]}
    for spec,p in zip(specs,plans):
        task=tasks[p["id"]]
        records=sorted((e for e in state["experiment"] if e["task"]==task["id"]),key=lambda e:e["round"])
        assert [r["round"] for r in records]==list(range(1,spec[3]+1))
        assert len({json.dumps(r["config"],sort_keys=True) for r in records})==len(records)
        plan=next(x for x in state["plan"] if x["id"]==p["id"])
        if not plan["decision"]:
            plan=post("decision",id=p["id"],value="保留候选" if task["best"].get("revision") else "不采用")
        out["plans"].append(dict(id=p["id"],title=p["title"],runs=records,holdout=plan.get("holdout"),decision=plan["decision"]))
    return out


if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--url",default="http://127.0.0.1:8776")
    p.add_argument("--output",type=Path)
    a=p.parse_args()
    out=json.dumps(run(a.url),ensure_ascii=False,indent=2)
    if a.output: a.output.write_text(out+"\n")
    else: print(out)
