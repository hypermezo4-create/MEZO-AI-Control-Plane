# Operations Runbook

## Readiness failure

Check `/health/ready`, then isolate PostgreSQL, Redis, worker heartbeat, and configuration failures. Do not mark readiness healthy by suppressing a failed dependency. Confirm the worker process group is running before increasing web capacity.

## Queue backlog

Inspect `/v1/observability/alerts` and `/metrics`. Compare ready depth, oldest ready age, active workers, active executions, delayed retries, and expired leases. Drain or scale workers only after confirming lease ownership and retry safety.

## Dead letters

Treat every dead-letter entry as unresolved work. Capture the task ID, attempts, terminal error, tool evidence, policy decisions, and repository head. Retry only after the cause is understood and the task remains idempotent.

## Provider outage

Open the circuit for the unhealthy provider, preserve task state, and allow configured fallback only for roles whose policy permits it. Never move credentials between provider adapters or log request bodies while debugging.

## Database migration failure

Keep the previous application release active. Capture Alembic output with secrets redacted, verify the current database revision, and review the migration transaction. Do not force-stamp or downgrade production without a reviewed recovery plan and owner approval.

## Evidence verification failure

Stop delivery for the affected task. Export the ledger entries, identify the first sequence whose previous hash or entry hash differs, and compare it with audit events and database backups. A broken chain is a blocking integrity event.
