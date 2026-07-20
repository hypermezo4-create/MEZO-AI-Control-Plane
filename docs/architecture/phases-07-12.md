# Architecture: Phases 7–12

The canonical runtime remains `src/mezo_control_plane`. Agents consume cited repository context and
produce structured outputs. The workflow persists hashes and evidence between every bounded stage.
GitHub, sandbox, tools, skills, and policies are enforcement ports outside model authority.

The dependency direction is:

```text
workflow -> agent/context/policy contracts
workflow -> tool and delivery ports
GitHub/sandbox/skills -> external or filesystem boundaries
database -> append-only checkpoint/evidence records
```

Migration `0002_workflow_delivery_records` adds checkpoints, invocations, prompt/model/tool records,
sandboxes, analysis/citations, GitHub installation references without tokens, branch/PR deliveries,
review findings, guard receipts, policy decisions, and approval records. Its downgrade removes only
these tables and leaves the Phase 2 task/evidence schema intact.

No live GitHub, model, Telegram, or Fly write is part of deterministic CI. Mock transports exercise
the same typed contracts. Docker sandbox properties are verified by the CI Docker job.
