"""Fixed, reproducible Iris classification protocol (stdlib only)."""
import csv
import hashlib
import io
import random
from collections import Counter
from pathlib import Path

SOURCE = "https://archive.ics.uci.edu/dataset/53/iris"
CANDIDATES = [(1, False),(3, False),(5, False),(7, False),(9, False),
              (1, True),(3, True),(5, True),(7, True),(9, True)]
BASELINE = (11, False)


def dataset():
    raw = (Path(__file__).with_name("datasets")/"iris.csv").read_bytes()
    groups = {}
    for row in csv.reader(io.StringIO(raw.decode())):
        if row:
            groups.setdefault(row[-1], []).append(list(map(float,row[:4])))
    if len(groups)!=3 or any(len(g)!=50 for g in groups.values()):
        raise ValueError("Iris 数据不完整。")
    out={key:[] for key in ("train","validation","test")}
    rng=random.Random(53)
    for label, group in sorted(groups.items()):
        rng.shuffle(group)
        for key, part in zip(out, (group[:28],group[28:39],group[39:])):
            out[key].extend([[x,label] for x in part])
    return dict(out,source=SOURCE,license="CC BY 4.0",sha256=hashlib.sha256(raw).hexdigest(),seed=53)


def evaluate(data,k,scale,split="validation"):
    train=data["train"]
    ranges=[max(x[0][i] for x in train)-min(x[0][i] for x in train) or 1 for i in range(4)] if scale else [1]*4
    expected,predicted=[],[]
    for x,y in data[split]:
        neighbors=sorted(train,key=lambda pair:sum(((a-b)/r)**2 for a,b,r in zip(x,pair[0],ranges)))[:k]
        expected.append(y)
        counts=Counter(z for _,z in neighbors)
        predicted.append(min(counts,key=lambda c:(-counts[c],c)))
    pairs=list(zip(expected,predicted))
    f1=[]
    for label in sorted(set(expected)):
        tp=sum(a==b==label for a,b in pairs)
        den=sum(a==label for a,b in pairs)+sum(b==label for a,b in pairs)
        f1.append(2*tp/den)
    return {"macro_f1":round(sum(f1)/len(f1),6),"accuracy":round(sum(a==b for a,b in pairs)/len(pairs),6)}


def choose(tried,best):
    available=[v for v in CANDIDATES if v not in tried]
    if not tried: return available[0]
    k=best.get("k",BASELINE[0])
    return min(available,key=lambda x:(x[1]==best.get("scale",False),abs(x[0]-k),x[0]))
