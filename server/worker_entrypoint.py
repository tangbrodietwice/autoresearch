"""Dispatch a persisted research task to its workflow."""
from compat.worker import BenchmarkWorker
from execution.scheduler import TaskManager
from research import workflow


class ResearchWorker:
    def __init__(self, store):
        self.store = store
        self.manager = TaskManager(store)

    def run(self, task_id):
        with self.store.tx(readonly=True) as db:
            task = self.store.get(db, "task", task_id)
        if not task:
            return
        if task.get("environment", {}).get("adapter") == "local-project":
            return workflow.advance(self.store, self.manager, task_id)
        return BenchmarkWorker(self.store).run(task_id)
