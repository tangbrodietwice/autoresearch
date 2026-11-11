"""Local Name That LLM experiment protocol; no Kaggle credentials or data in Git."""
import argparse
import csv
import hashlib
import io
import json
import math
import random
import re
from collections import Counter, defaultdict
from functools import lru_cache
from pathlib import Path
from zipfile import ZipFile

SOURCE = "https://www.kaggle.com/competitions/name-that-llm"
STRATEGIES = {"char":"字符 n-gram","style":"文体与标点","adaptive":"自由迭代"}
BASELINE = {"word":1.0,"char":0.0,"style":0.0,"grams":3,"normalize":True}


def inspect(raw, fixture=False):
    reader=csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
    if not {"id","prompt_id","text","model"}<=set(reader.fieldnames or []):
        raise ValueError("训练文件须含 id、prompt_id、text、model。")
    rows=[tuple(r[k].strip() for k in ("id","prompt_id","text","model")) for r in reader]
    prompts, labels={r[1] for r in rows},{r[3] for r in rows}
    if any(not all(r) for r in rows) or len({r[0] for r in rows})!=len(rows):
        raise ValueError("训练文件包含空字段或重复 ID。")
    if fixture:
        if len(prompts)<9 or len(labels)<2:
            raise ValueError("测试样本不足。")
    elif (len(rows),len(prompts),len(labels))!=(2699,150,18):
        raise ValueError("文件与 Kaggle 公布的 2699 行、150 个提示、18 个类别不符。")
    return rows,prompts,labels


def prepare(source, root, fixture=False):
    if source.suffix.lower()==".zip":
        with ZipFile(source) as z:
            matches=[item for item in z.infolist() if Path(item.filename).name=="train.csv"]
            if len(matches)!=1 or matches[0].file_size>20_000_000:
                raise ValueError("ZIP 中须有且仅有一个训练 CSV。")
            raw=z.read(matches[0])
    else:
        if source.stat().st_size>20_000_000:
            raise ValueError("训练 CSV 过大。")
        raw=source.read_bytes()
    rows,prompts,labels=inspect(raw,fixture)
    key=hashlib.sha256(raw).hexdigest()
    directory=root/"imports"/"name-that-llm"
    directory.mkdir(parents=True,exist_ok=True)
    manifest=dict(sha256=key,rows=len(rows),prompts=len(prompts),labels=len(labels),fixture=fixture)
    (directory/(key+".csv")).write_bytes(raw)
    temp=directory/"latest.tmp"
    temp.write_text(json.dumps(manifest))
    temp.replace(directory/"latest.json")
    return manifest


def latest(root):
    p=root/"imports/name-that-llm/latest.json"
    if not p.exists():
        raise ValueError("未导入 Kaggle 训练数据。请先下载 train.csv，再用 scripts/prepare-name-llm.py 导入。")
    return json.loads(p.read_text())


@lru_cache(maxsize=2)
def dataset(root, key, fixture=False):
    raw=(root/"imports"/"name-that-llm"/(key+".csv")).read_bytes()
    if hashlib.sha256(raw).hexdigest()!=key:
        raise ValueError("训练文件的哈希与项目协议不符。")
    rows,prompts,labels=inspect(raw,fixture)
    order=sorted(prompts)
    random.Random(173).shuffle(order)
    n=max(2,len(order)//5)
    partitions={"validation":set(order[:n]),"holdout":set(order[n:2*n]),"train":set(order[2*n:])}
    result={k:[(text,label) for _,prompt,text,label in rows if prompt in ids] for k,ids in partitions.items()}
    if any({label for _,label in split}!=labels for split in result.values()):
        raise ValueError("提示分组后有类别缺失。")
    return result


def propose(strategy, ordinal, best):
    group, offset=divmod(ordinal-1,4)
    if strategy=="char":
        return dict(BASELINE,word=round(.15+.1*group,3),char=1.,grams=(2,3,4,5)[offset])
    if strategy=="style":
        return dict(BASELINE,word=(0.,.3,.7,1.)[offset],style=round(1.+.2*group,3))
    rnd=random.Random(2718+ordinal)
    parent=best.get("config",dict(BASELINE,char=.7,style=.4))
    return dict(word=round(min(2,max(.05,parent["word"]+rnd.uniform(-.6,.6))),4),
                char=round(min(2,max(.05,parent["char"]+rnd.uniform(-.6,.6))),4),
                style=round(min(2,max(.05,parent["style"]+rnd.uniform(-.6,.6))),4),
                grams=rnd.choice([2,3,4,5]),normalize=rnd.choice([True,True,False]))


def features(text,cfg):
    words=re.findall(r"[^\W_]+(?:['’][^\W_]+)?",text.casefold())
    lower=" ".join(text.casefold().split())
    result={}
    for prefix, weight, tokens in (("w",cfg["word"],words),
            ("c",cfg["char"],(lower[i:i+cfg["grams"]] for i in range(max(0,len(lower)-cfg["grams"]+1))))):
        if weight:
            counts=Counter(tokens)
            values={prefix+k:1+math.log(v) for k,v in counts.items()}
            norm=math.sqrt(sum(v*v for v in values.values())) or 1
            result.update((k,weight*v/(norm if cfg["normalize"] else math.sqrt(norm))) for k,v in values.items())
    if cfg["style"]:
        n=max(1,len(text))
        style=[min(1,len(words)/220),min(1,sum(map(len,words))/max(1,len(words))/10),
               len(set(words))/max(1,len(words)),sum(c.isupper() for c in text)/n,
               sum(c.isdigit() for c in text)/n,*[min(1,text.count(c)*30/n) for c in "—–-,:;!?()“”’\n"]]
        result.update(("s"+str(i),cfg["style"]*v) for i,v in enumerate(style))
    return result


def evaluate(root, manifest, cfg, split="validation", diagnostics=None):
    data=dataset(root,manifest["sha256"],manifest.get("fixture",False))
    centroid=defaultdict(Counter)
    for text,label in data["train"]:
        centroid[label].update(features(text,cfg))
    labels=sorted(centroid)
    inverse=defaultdict(list)
    classifier=cfg.get("classifier","centroid")
    if classifier=="multinomial_nb":
        vocabulary=set().union(*(row.keys() for row in centroid.values()))
        denominators=[sum(centroid[label].values())+len(vocabulary) for label in labels]
        offsets=[-math.log(value) for value in denominators]
        for i,label in enumerate(labels):
            for key,value in centroid[label].items():
                inverse[key].append((i,math.log1p(value)))
    else:
        for i,label in enumerate(labels):
            row=centroid[label]
            norm=math.sqrt(sum(v*v for v in row.values())) or 1
            for k,v in row.items():
                inverse[k].append((i,v/norm))
    totals, hits, confusion=Counter(),Counter(),Counter()
    for text,target in data[split]:
        values=features(text,cfg)
        if classifier=="multinomial_nb":
            mass=sum(v for k,v in values.items() if k in vocabulary)
            scores=[mass*offset for offset in offsets]
        else:
            scores=[0.0]*len(labels)
        for k,v in values.items():
            for i,w in inverse.get(k,()):
                scores[i]+=v*w
        chosen=labels[max(range(len(labels)),key=scores.__getitem__)]
        totals[target]+=1
        hits[target]+=chosen==target
        confusion[target,chosen]+=1
    if diagnostics is not None:
        diagnostics.update(split=split, sample_counts={name:len(rows) for name,rows in data.items()},
                           split_seed=173, group_key="prompt_id",
                           recalls={label:{"correct":hits[label],"total":totals[label]} for label in labels},
                           confusion={label:{guess:confusion[label,guess] for guess in labels} for label in labels})
    return {"balanced_accuracy":round(sum(hits[k]/totals[k] for k in labels)/len(labels),6),
            "accuracy":round(sum(hits.values())/sum(totals.values()),6)}


if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("source",type=Path)
    p.add_argument("--state",type=Path,default=Path(".state/web"))
    p.add_argument("--fixture",action="store_true")
    a=p.parse_args()
    print(json.dumps(prepare(a.source,a.state,a.fixture)))
