"""UCI Dry Bean benchmark, with fixed splits and independent CPU training jobs."""
import argparse
import csv
import fcntl
import gzip
import hashlib
import json
import math
import random
import time
from collections import Counter, defaultdict
from functools import lru_cache
from pathlib import Path

SOURCE = "https://doi.org/10.24432/C50S4B"
BASELINE = {"family": "centroid", "prior": 0.0, "weights": [1.0] * 16}
STRATEGIES = {"centroid": "质心与特征消融", "bayes": "高斯朴素贝叶斯", "adaptive": "自适应特征权重"}


@lru_cache(maxsize=2)
def dataset(path=None):
    path = Path(path) if path else Path(__file__).with_name("datasets") / "dry-bean.csv.gz"
    raw = gzip.decompress(path.read_bytes())
    rows = list(csv.reader(raw.decode().splitlines()))[1:]
    if len(rows) != 13611 or any(len(row) != 17 for row in rows) or len({row[-1] for row in rows}) != 7:
        raise ValueError("Dry Bean 数据不完整")
    raw_count = len(rows)
    groups, unique = defaultdict(list), defaultdict(set)
    for row in rows:
        unique[tuple(map(float,row[:-1]))].add(row[-1])
    for x, labels in unique.items():
        if len(labels) == 1:
            label, = labels
            groups[label].append([x,label])
    rng = random.Random(602)
    out = {k: [] for k in ("train", "validation", "test")}
    for label in sorted(groups):
        rows = groups[label]
        rng.shuffle(rows)
        a, b = int(len(rows) * .7), int(len(rows) * .85)
        for key, part in zip(out, (rows[:a], rows[a:b], rows[b:])):
            out[key].extend(part)
    return dict(out, sha256=hashlib.sha256(raw).hexdigest(), source=SOURCE, seed=602, raw_rows=raw_count, unique_rows=sum(map(len,groups.values())))


def propose(strategy, ordinal, best=None):
    best = best or {}
    if strategy == "centroid":
        patterns = [[1] * 16, [1] * 8 + [0] * 8, [0] * 8 + [1] * 8, [1] * 8 + [2] * 8]
        return {"family":"centroid", "prior":.1 + .07*ordinal, "weights":patterns[(ordinal-1)%4]}
    if strategy == "bayes":
        return {"family":"bayes", "prior":.14*ordinal, "shrinkage":.02*ordinal, "weights":[1]*16}
    rng = random.Random(602_000 + ordinal)
    parent = best.get("config", {})
    weights = parent.get("weights", [1]*16)
    return {"family":"bayes", "prior":round(rng.uniform(.02,.8),6),
            "shrinkage":round(rng.uniform(.01,.3),6),
            "weights":[round(min(5,max(.05,w*math.exp(rng.uniform(-.45,.45)))),6) for w in weights]}


def evaluate(data, cfg, split="validation"):
    train = data["train"]
    dims = tuple(zip(*(x for x, _ in train)))
    avg = [sum(d)/len(d) for d in dims]
    variance = [sum((v-m)**2 for v in d)/len(d) or 1 for d,m in zip(dims,avg)]
    classes = defaultdict(list)
    for x,label in train:
        classes[label].append(x)
    models = []
    for label in sorted(classes):
        rows=classes[label]
        ds=tuple(zip(*rows))
        mu=[sum(d)/len(d) for d in ds]
        if cfg["family"]=="bayes":
            shrink=cfg["shrinkage"]
            var=[max(g*1e-9, (1-shrink)*sum((v-m)**2 for v in d)/len(d)+shrink*g)
                 for d,m,g in zip(ds,mu,variance)]
        else:
            var=variance
        coefficients=[w/v for w,v in zip(cfg["weights"],var)]
        offset=2*cfg["prior"]*math.log(len(rows)/len(train))
        if cfg["family"]=="bayes":
            offset-=sum(w*math.log(v) for w,v in zip(cfg["weights"],var))
        models.append((label,mu,coefficients,offset))
    confusion=Counter()
    for x,target in data[split]:
        chosen=max(models,key=lambda m:m[3]-sum(w*(v-u)**2 for v,u,w in zip(x,m[1],m[2])))[0]
        confusion[target,chosen]+=1
    labels=sorted(classes)
    f1=[2*confusion[c,c]/max(1,sum(confusion[c,k]+confusion[k,c] for k in labels)) for c in labels]
    return {"macro_f1":round(sum(f1)/len(f1),6),
            "accuracy":round(sum(confusion[c,c] for c in labels)/len(data[split]),6)}


@lru_cache(maxsize=1)
def baseline():
    return evaluate(dataset(), BASELINE)


def train_job(root, workspace, job_id, adapter="beans"):
    job = root/"training"/job_id
    job.mkdir(parents=True,exist_ok=True)
    receipt = job/"result.json"
    with (job/"lock").open("a") as lock:
        try:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            return
        if receipt.exists():
            return
        started=time.time()
        try:
            repo=root/"projects"/workspace
            candidate=json.loads((repo/"models"/f"{job_id}.json").read_text())
            if adapter=="name-llm":
                from name_llm import train
                result=train(root,repo,job_id)
            else:
                result=evaluate(dataset(str(repo/"data"/"dry-bean.csv.gz")),candidate)
            payload={"metrics":result,"started_at":started,"ended_at":time.time()}
        except Exception as exc:
            payload={"error":type(exc).__name__,"started_at":started,"ended_at":time.time()}
        temp=receipt.with_suffix(".tmp")
        temp.write_text(json.dumps(payload),encoding="utf-8")
        temp.replace(receipt)


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("root",type=Path)
    parser.add_argument("workspace")
    parser.add_argument("job")
    parser.add_argument("adapter",choices=("beans","name-llm"),nargs="?",default="beans")
    args=parser.parse_args()
    train_job(args.root,args.workspace,args.job,args.adapter)
