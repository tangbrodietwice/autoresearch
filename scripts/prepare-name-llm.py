import runpy
from pathlib import Path
import sys

backend=Path(__file__).resolve().parents[1]/"server"
sys.path.insert(0,str(backend))
runpy.run_module("compat.benchmarks.name_llm",run_name="__main__")
