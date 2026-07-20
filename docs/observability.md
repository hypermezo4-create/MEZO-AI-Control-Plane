# Observability and Evidence

MEZO exposes operational signals without treating model output as trusted telemetry.

## Metrics

`GET /metrics` requires the control-plane API key and emits Prometheus text. The export includes bounded HTTP labels, queue depth by priority, in-flight work, leases, delayed retries, dead letters, worker availability, and queue latency. UUID and numeric URL segments are normalized before becoming labels to prevent cardinality growth.

`GET /v1/observability/snapshot` returns the same application and queue state as structured JSON for the dashboard and operators.

## Alerts

`GET /v1/observability/alerts` evaluates deterministic rules for:

- queue backlog and stale ready work;
- dead letters and expired leases;
- workers unavailable while a backlog exists;
- provider outage, repeated failures, and cost anomaly inputs.

Provider health, repeated-failure, and hourly cost rules remain explicitly unavailable until their owning adapters publish measurements. The API returns those metric names in `unavailable_metrics`; it never substitutes zero or infers health from model prose.

## Tracing

`tracing_boundary` creates process-local trace and span identifiers for API and agent boundaries. Attribute names containing token, secret, credential, authorization, private, prompt, or password are redacted before logging. Prompts, repository contents, credentials, and raw model responses are not trace attributes.

## Evidence integrity

Every durable evidence append writes the normal task evidence record and a hash-chained `evidence_ledger` entry in the same PostgreSQL transaction. Appends lock the task row, assign a monotonic task-local sequence, reference the previous entry hash, and compute a canonical SHA-256 digest. The `EvidenceLedgerRepository.verify` method reconstructs and verifies the chain.

The API report at `GET /v1/tasks/{task_id}/report` includes the task, evidence, a deterministic evidence digest, and generation time. A digest proves report consistency; it does not replace the persistent ledger verification.
