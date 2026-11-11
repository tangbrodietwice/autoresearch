"""Launch the TripSci service or advance one research task."""
import argparse
from pathlib import Path

from http_api import serve
from storage import WorkspaceStore
from worker_entrypoint import ResearchWorker

BASE = Path(__file__).resolve().parent


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", type=Path, default=BASE.parent/".state")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--worker")
    args = parser.parse_args()
    project = WorkspaceStore(args.state)
    if args.worker:
        ResearchWorker(project).run(args.worker)
    else:
        serve(project, args.port)
