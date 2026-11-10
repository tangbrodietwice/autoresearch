"""TripSci service and worker entrypoint; preserves legacy imports."""
import argparse
from pathlib import Path

from mock_training import MockTraining
from runtime import RuntimeAdapter
from scheduler import TaskManager
from server import serve
from storage import Project
from worker import ResearchWorker

BASE = Path(__file__).resolve().parent


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", type=Path, default=BASE.parent/".state")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--worker")
    args = parser.parse_args()
    project = Project(args.state)
    if args.worker:
        ResearchWorker(project).run(args.worker)
    else:
        serve(project, args.port)
