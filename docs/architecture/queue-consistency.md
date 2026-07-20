# Queue and durable-state consistency

PostgreSQL is the source of task state, attempts, decisions, and immutable evidence. Redis is
only the delivery coordinator. Queue envelopes therefore never authorize execution by
themselves.

## Ordering contract

On claim, a worker locks the task row, rejects durable terminal state, inserts the numbered
attempt and claim evidence, and commits before invoking a handler. If that transaction fails,
the worker does not execute or acknowledge the delivery; its lease remains recoverable.

On success, output evidence and the completed transition commit in one PostgreSQL transaction.
Only then does the worker acknowledge Redis. If acknowledgement fails, lease recovery reads the
durable completed state and removes Redis inflight, lease, and expiry records without executing
the task again.

On failure, failure evidence and the retry-or-terminal state commit before Redis is changed.
If retry scheduling or DLQ finalization then fails, the unacknowledged delivery remains indexed
by its lease and can be reconciled using the durable decision.

Recovery uses the bounded lease-expiry sorted set; it never uses `KEYS`. It rechecks the current
score and lease metadata atomically, so a concurrent renewal wins. Before requeue, recovery reads
durable state. Completed, failed, or cancelled tasks are cleaned without re-execution. Every
recovery records the previous owner, deadline, and reason.

## Evidence canonicalization

Evidence hashes are SHA-256 over UTF-8 JSON containing `kind`, `summary`, and canonical string
`task_id`, with keys sorted, compact separators, and ASCII escaping. Evidence rows have no update
or delete repository operation. The unique hash makes repeated identical evidence idempotently
detectable and any mutation externally evident.

## Cancellation

The durable cancellation transaction precedes creation of the Redis tombstone. Claims,
renewals, acknowledgements, retry promotion, recovery, and DLQ replay consult that tombstone.
Tombstones remain until a reconciliation job has verified durable terminal state and removed
every delivery record.
