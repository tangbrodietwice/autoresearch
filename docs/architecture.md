# TripSci architecture: refactor checkpoint

This checkpoint preserves the HTTP API, current data paths and SQLite storage. It
changes code ownership and the CLI execution boundary. It is not a migration of
live projects or a change to fixed evaluation protocols.

| Area | Entry point | Owns |
| --- | --- | --- |
| Launch | `tripsci/app.py` | HTTP and worker CLI compatibility |
| Transport | `tripsci/server.py` | Request decoding, idempotency and HTTP responses |
| Workspace operations | `tripsci/native_api.py`, `tripsci/actions/` | Shared UI and confirmed agent commands |
| Conversations | `tripsci/main_chat.py` | Supervisor prompt, replies and proposals |
| Research | `tripsci/scheduler.py`, `tripsci/worker.py`, `tripsci/research/planner.py` | Deterministic scheduling, experiment lifecycle and evidence-based decisions |
| Execution | `tripsci/execution/`, `tripsci/runtime.py`, `tripsci/mock_training.py` | CLI adapter discovery and invocation; worker/training processes |
| Storage | `tripsci/storage.py`, `tripsci/run_workspace.py` | SQLite, Git and file snapshots |

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

## Configured local research

The Web client defaults to a project contract with a local Git root, tracked
source revision, data-file fingerprint, training/evaluation argv, baseline score,
metric direction and seed. No benchmark catalogue is consulted on this path.
`research/project_runner.py` validates and executes that contract; `research/local_worker.py`
gives Codex the objective, feedback and past evidence, and records each proposal
and result. The candidate and evaluator are checked out separately. The evaluator
is pinned to the approved source revision and consumes artifacts from the run
directory. The original repository is not edited.

Round artifacts are written under `runs/<task>-<round>/`; SQLite indexes completed
experiments and progress. A restart can resume a saved proposal and reuse saved
metrics after a failed or interrupted analysis. Existing benchmark behavior is
preserved under the legacy Worker and benchmark modules; its dedicated commands
and compatibility views are not the generic execution contract. Codex remains
the only connected model provider. No separate AgentRun is introduced.
