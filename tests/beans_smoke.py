"""Exercise real concurrent CPU jobs and continuous-plan completion in disposable state."""
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]

with tempfile.TemporaryDirectory() as state:
    with subprocess.Popen([sys.executable,"backend/app.py","--state",state,"--port","0"],
                          cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True) as server:
        try:
            address=server.stdout.readline().strip()
            assert address.startswith("http://"),address
            subprocess.run([sys.executable,"scripts/run-beans.py","--url",address,"--interval","2","--finish"],
                           cwd=ROOT,check=True,stdout=subprocess.DEVNULL)
            print("PASS Dry Bean: overlapping CPU training, bounded-plan review, continuous pause/resume and finish")
        finally:
            server.terminate()
            server.wait(timeout=10)
