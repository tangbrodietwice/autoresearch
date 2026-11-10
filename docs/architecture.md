# TripSci architecture: refactor checkpoint

This checkpoint preserves the HTTP API, current data paths and SQLite storage. It
changes code ownership and the CLI execution boundary. It is not a migration of
live projects or a change to fixed evaluation protocols.

| Area | Entry point | Owns |
| --- | --- | --- |
| Launch | `backend/app.py` | HTTP and worker CLI compatibility |
| Transport | `backend/server.py` | Request decoding, idempotency and HTTP responses |
| Workspace operations | `backend/native_api.py`, `backend/actions/` | Shared UI and confirmed agent commands |
| Conversations | `backend/main_chat.py` | Supervisor prompt, replies and proposals |
| Research | `backend/scheduler.py`, `backend/worker.py`, `backend/research/planner.py` | Deterministic scheduling, experiment lifecycle and evidence-based decisions |
| Execution | `backend/execution/`, `backend/runtime.py`, `backend/mock_training.py` | CLI adapter discovery and invocation; worker/training processes |
| Storage | `backend/storage.py`, `backend/run_workspace.py` | SQLite, Git and file snapshots |

`execution.run_json` is the shared CLI entry point. The supervisor supplies a
conversation schema and can enable web search through its existing permissions.
The research planner supplies a decision schema and leaves web search disabled.
The Codex adapter owns process arguments, timeouts, progress and result
decoding. It does not know about plans, permission approvals or storage. It
runs read-only without shell tools; the Worker harness applies validated
decisions and runs experiments. Legacy built-in Worker configurations still
work; a Codex Worker profile can be selected for the supported local research
flows. Claude Code and Pi discovery does not imply execution support.

## Next migration boundaries

1. Store machine, Provider and Agent configuration separately. Persist AgentRun
   with its effective configuration version and link it to conversation or
   research execution. Verify a second Provider without changing domain code.
2. Make research decision, experiment input snapshot and training attempt
   explicit links. Store source fingerprints at submission and keep older
   records unchanged where provenance is unknown.
3. Rehearse storage and source-directory migrations using copies of existing
   state. Validate two parallel live research plans with interruption and
   recovery before switching the main workspace.
