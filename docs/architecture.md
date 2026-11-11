# TripSci architecture

The repository has one service in `server/`, two clients in `apps/`,
and checks in `tests/`. The [Multica server layout](https://github.com/multica-ai/multica/tree/main/server)
is a reference for the top-level boundary; Project, Research Plan and
Experiment remain TripSci concepts.

| Code | Responsibility |
| --- | --- |
| `server/app.py`, `server/http_api.py` | Start the local service and translate HTTP requests. One server owns a workspace at a time. |
| `server/workspace.py`, `server/commands/` | Workspace views and commands. The UI and approved supervisor proposals use the same command inputs and handlers. |
| `server/agents/` | Supervisor conversation, Worker proposal and analysis, shared profile versions and invocation history. |
| `server/research/` | Project contract, experiment workflow, fixed evaluator, metrics and candidate selection. |
| `server/execution/` | Training dispatch, shared slots, numbered attempts, process leases and receipts. Model CLI providers are adapters here. |
| `server/storage.py`, `server/run_artifacts.py` | Workspace SQLite and Git/file artifacts. |
| `server/compat/` | Built-in search policies, benchmarks and the legacy Worker workflow used by existing examples and plans. |

## Execution and recovery

A configured Worker freezes its profile and project contract when the plan is
approved. It persists a code proposal, then submits a training Job with the
candidate revision and evaluation contract. The scheduler allocates a slot and
starts the numbered attempt. A filesystem lease identifies the live attempt
even when the server no longer has its process handle; a receipt is the durable
handoff back to the scheduler. A pause prevents pending dispatch and new
decisions from advancing the plan. An already started attempt can finish. An
analysis retry uses the saved metrics rather than starting another attempt.

The persisted keys `workspace`, `plan`, `task`, `experiment`, and `job`
remain readable by the v1 clients. New configured experiments link their
project, plan and Job. `agent_run` links a model invocation and its outcome to
a profile version and either a conversation or an experiment stage. Supervisor
turns use the current profile; Worker invocations use the frozen profile.
Abandoned invocations are closed when the corresponding lease is reacquired.

Configured training uses the macOS isolation adapter. Candidate code receives
a read-only dataset snapshot, its own checkout, a private temporary home and a
writable artifact directory. The pinned evaluator receives the artifacts
read-only and a separate writable metrics directory. Network and inherited
environment variables are unavailable. The executor expects dependencies in
the project checkout or supported system/tool directories. Other hosts cannot
run this path until a compatible isolation adapter is added.

## Upgrading an existing workspace

Stop the old service and allow its old training processes to finish before
starting the new server against the same state directory. Existing SQLite
rows, Git revisions, result paths and attempt numbers are preserved. Old
configured results and receipts can be reused. An old interrupted attempt
without a receipt requires an explicit retry because it predates the process
lease. Keep a copy of the original state before upgrading.

The Iris, Dry Bean and Name That LLM scripts still use the v1 API and the
compatibility workflow, including Dry Bean continuous mode. The generic
research workflow does not inherit from the compatibility Worker.
