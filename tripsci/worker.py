"""Route an approved research plan to its execution path."""
from legacy.worker import ResearchWorker as LegacyWorker
from research import local_worker


class ResearchWorker(LegacyWorker):
    def run(self, key):
        with self.p.tx(readonly=True) as db:
            task = self.p.get(db, "task", key)
        if task and task.get("research_mode") == "agent":
            return local_worker.run(self.p, self.manager, key)
        return super().run(key)
