"""Drive the Dry Bean scenario through TripSci's own HTTP API."""
import argparse
import itertools
import json
from pathlib import Path
import time
from urllib.request import Request, urlopen


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--url",default="http://127.0.0.1:8766")
    ap.add_argument("--project",default="",help="Use a separately named benchmark project")
    ap.add_argument("--interval",type=int,default=20)
    ap.add_argument("--output",type=Path)
    ap.add_argument("--finish",action="store_true",help="Finish the continuous plan after testing, for disposable runs")
    args=ap.parse_args()

    def request(path,payload=None):
        req=Request(args.url+path,data=json.dumps(payload).encode() if payload is not None else None,
                    headers={"Content-Type":"application/json"})
        with urlopen(req,timeout=20) as res:
            return json.load(res)

    def post(op,**d):
        return request("/v1/action",dict(op=op,**d))

    def snapshot():
        return request("/v1/state")

    def wait_until(predicate,seconds=100):
        deadline=time.monotonic()+seconds
        while time.monotonic()<deadline:
            data=snapshot()
            if predicate(data):
                return data
            time.sleep(.25)
        raise RuntimeError("Timed out waiting for plans: "+json.dumps(tasks(data),ensure_ascii=False))

    project=post("import_beans",name=args.project)
    specs=[("质心与特征消融","比较尺寸、形状两组特征与完整输入。","centroid",4),
           ("高斯朴素贝叶斯","比较不同方差收缩与类别先验配置。","bayes",4),
           ("持续迭代 · 自适应特征权重","按验证集 macro F1 保留最优参数，继续搜索新权重。","adaptive",1)]
    ids=[]
    for name,design,strategy,budget in specs:
        p=post("plan",title=name,direction=design,workspace=project["id"])
        ids.append(p["id"])
        post("message",plan=p["id"],text=f"{design} 固定数据划分；准确率是护栏。")
    post("start_batch",plans=[
        dict(id=pid,design=design,strategy=strategy,budget=budget,
             run_mode="continuous" if strategy=="adaptive" else "bounded",interval=args.interval)
        for pid, (_,design,strategy,budget) in zip(ids,specs)])
    print("已通过 TripSci 启动计划："+", ".join(ids),flush=True)

    def tasks(data):
        return {t["plan"]:t for t in data["task"] if t.get("plan") in ids}

    def records(data,pid):
        return sorted((x for x in data["experiment"] if x["task"]==tasks(data)[pid]["id"]),key=lambda e:e["round"])

    loop=ids[-1]
    seen=wait_until(lambda d: sum(t["status"]=="waiting" for t in tasks(d).values())>=2)
    assert len(tasks(seen))==3
    data=wait_until(lambda d: len(records(d,loop))>=1)
    post("pause",id=loop)
    paused=tasks(snapshot())[loop]
    time.sleep(args.interval+1)
    assert tasks(snapshot())[loop]["round"]==paused["round"]
    post("resume",id=loop)
    data=wait_until(lambda d: all(tasks(d)[i]["status"]=="completed" for i in ids[:2]) and len(records(d,loop))>=3,
                    max(100,args.interval*4))
    for pid in ids[:2]:
        t=tasks(data)[pid]
        post("decision",id=pid,value="保留候选" if "revision" in t["best"] else "不采用")
    assert len(records(data,ids[0]))==len(records(data,ids[1]))==4
    assert tasks(data)[loop]["continuous"] and tasks(data)[loop]["status"] in ("waiting","ready")
    observed=[(pid,e) for pid in ids for e in records(data,pid)]
    overlaps=[(a["id"],b["id"]) for (p,a),(q,b) in itertools.combinations(observed,2) if p!=q
              and max(a["training_started_at"],b["training_started_at"])<min(a["training_ended_at"],b["training_ended_at"])]
    assert overlaps,"No overlapping CPU training intervals"
    for pid in ids:
        es=records(data,pid)
        assert len({e["id"] for e in es})==len(es) and all(e["revision"] and e["report_commit"] for e in es)
    if args.finish:
        post("finish",id=loop)
        wait_until(lambda d:tasks(d)[loop]["status"]=="completed")
    data=snapshot()
    result={"project":project,"training_overlaps":overlaps,"pause_resume_verified":True,"plans":[]}
    for pid in ids:
        plan=next(p for p in data["plan"] if p["id"]==pid)
        t=tasks(data)[pid]
        result["plans"].append({"id":pid,"title":plan["title"],"status":t["status"],"continuous":t.get("continuous",False),
                                "baseline":t["baseline_metrics"],"holdout":plan.get("holdout"),"decision":plan["decision"],
                                "experiments":[{k:e[k] for k in ("round","id","result","accepted","guardrail_passed","revision","config","training_started_at","training_ended_at")} for e in records(data,pid)]})
    text=json.dumps(result,ensure_ascii=False,indent=2)
    if args.output:
        args.output.write_text(text+"\n")
    print(text)


if __name__=="__main__":
    main()
