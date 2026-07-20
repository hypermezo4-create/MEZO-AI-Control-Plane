# Gap analysis

| Capability | Existing foundation | Required work |
| --- | --- | --- |
| Task lifecycle | Mutable Pydantic record and a small transition map | Audited, idempotent lifecycle with retries, cancellation, timeout, resume, and terminal rules |
| Persistence | Async session factory only | SQLAlchemy entities, repositories, Alembic migrations, immutable evidence and audit history |
| Queue | Redis list enqueue/dequeue | Priority scheduling, leases, heartbeats, visibility recovery, backpressure, retry budgets and DLQ |
| API | Task submission and health routes | Versioned resource API, idempotency, errors, audit, throttling, webhooks and contracts |
| Integrations | Provider and GitHub contracts | Telegram, GitHub App, sandbox, tools, skills integrity and operational adapters |
| Orchestration | Planning helper | Bounded agents, checkpoints, independent review, evidence gates and PR preparation |
| Operations | Basic JSON logging and compose/Fly files | Metrics, tracing, alerts, dashboard, deployment runbooks, CI and deterministic evals |

The safest migration is incremental: retain the public `TaskRequest` contract while introducing
new typed records and persistence interfaces behind the existing routes. PostgreSQL schema changes
must remain additive until a controlled migration removes legacy fields. Queue acknowledgement must
occur only after durable state transition evidence is written.
