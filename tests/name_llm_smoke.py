"""Synthetic protocol and scheduler test; no competition data in the checkout."""
import csv
import json
from pathlib import Path
import subprocess
import sys
import tempfile

root=Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory() as tmp:
    state=Path(tmp)
    source=state/"fixture.csv"
    with source.open("w",newline="") as f:
        writer=csv.writer(f)
        writer.writerow(["id","prompt_id","text","model"])
        for prompt in range(30):
            for i in range(3):
                writer.writerow([f"{prompt}-{i}",str(prompt),
                    f"topic {prompt}. "+["First, then, finally.","A quick note — precisely!","Summary: give an example."][i],f"fixture-{i}"])
    subprocess.run([sys.executable,"scripts/prepare-name-llm.py",str(source),"--state",str(state),"--fixture"],
                   cwd=root,check=True,stdout=subprocess.DEVNULL)
    server=subprocess.Popen([sys.executable,"tripsci/app.py","--state",str(state),"--port","0"],
                            cwd=root,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True)
    try:
        url=server.stdout.readline().strip()
        assert url.startswith("http://")
        result=state/"result.json"
        subprocess.run([sys.executable,"scripts/run-name-llm.py","--url",url,"--output",str(result)],cwd=root,check=True)
        data=json.loads(result.read_text())
        assert data["project"]["manifest"]["fixture"] is True and data["parallel_observed"]
        assert [len(p["runs"]) for p in data["plans"]]==[4,4,20]
        assert all("balanced_accuracy" in p["holdout"]["baseline"] for p in data["plans"])
        print("PASS synthetic Name That LLM: 3 plans, 4/4/20 unique configurations, grouped protocol, and holdout reports")
    finally:
        server.terminate()
        server.wait(timeout=10)
