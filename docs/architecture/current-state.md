# Current state

Baseline recorded on 2026-07-20 from commit `35d8f1d59726b36c382aebc7ef1c902d14ac5eab`.

The initial package provides a small FastAPI task-submission endpoint, a Redis list queue,
an in-memory task state machine, basic policy routing, provider contracts, and a worker entry
point. It has no durable task repository, migration system, lease recovery, Telegram adapter,
GitHub App implementation, sandbox runner, tool executor, dashboard, or evidence ledger.

`src/mezo_control_plane` is the only importable runtime package. Operational configuration is at
the repository root. The original test suite contains six focused tests for routing, policy,
skills, and state transitions.

Baseline commands after installing the declared editable development dependencies:

```text
ruff check .  -> All checks passed!
mypy src      -> Success: no issues found in 42 source files
pytest -q     -> 6 passed in 0.20s
```

Docker was not available in this environment (`docker` was not recognized), so image and Compose
verification cannot be recorded here.
