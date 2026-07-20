# Control-plane capabilities: phases 3–6

This document describes the implemented boundaries and their failure behavior. It does not
assert deployment readiness.

## Delivery and execution

Redis delivery uses priority lists, an idempotency mapping, inflight and lease hashes, and
sorted-set indexes for lease expiry and delayed retries. Lua operations separate list, hash,
set, and sorted-set keys explicitly. Recovery and retry promotion process bounded batches and
recheck current metadata atomically. Cancellation tombstones are consulted by claim, renewal,
acknowledgement, promotion, recovery, and DLQ replay.

`WorkerRuntime` claims only while capacity is available and tracks each handler and renewal task.
It runs heartbeat and maintenance independently, treats missing leases and Redis renewal errors
as ownership loss, and drains active handlers for a configured deadline. PostgreSQL ordering is
specified in [queue-consistency.md](queue-consistency.md).

## HTTP control surface

The FastAPI gateway exposes versioned task, repository, provider, model, and GitHub webhook
routes plus liveness, readiness, and queue metrics. Middleware assigns request IDs, performs
constant-time API-key comparison, limits bodies and rates, applies request deadlines, records
write/denial logs without request bodies, and maps known errors to a stable envelope.

Readiness checks PostgreSQL, Redis, worker registration, and required configuration. Liveness
does not query model providers. The GitHub webhook uses its own HMAC-SHA256 signature instead of
the control API key.

## Telegram control surface

Telegram commands call the same `TaskApplicationService` used by HTTP. The adapter owns only
transport concerns: allowlists, roles, rate limits, update deduplication, FloodWait retry,
HTML-safe chunking, redaction, and signed expiring one-use callbacks. `/deploy` reports that the
deployment policy phase is not implemented and does not perform a deployment.

Required Telegram variables are listed in `.env.example`. Empty tokens and callback secrets do
not enable the adapter.

## Providers and routing

Gemini A and Gemini B are separate provider instances with independent credentials, project
identity, semaphore, circuit breaker, retry budget, health, latency, and usage accounting. Qwen
uses the OpenAI-compatible model and chat endpoints, parses tool calls, pins models, and keeps
streaming disabled explicitly in the request policy. Embeddings validate batch size, input size,
response count, and dimensions; no vector is synthesized on failure.

Role chains and pinned cost metadata are loaded from `model_router/routes.v1.yaml`. Startup rejects
unknown providers, models, or omitted roles. Routing propagates cancellation and deadlines,
validates optional structured output, records each attempt, and raises a typed failure when no
candidate succeeds. `BlindReviewContext` has no fields for executor confidence, self-evaluation,
or implementation narrative.

## Local and CI verification

Local integration tests skip when `REDIS_TEST_URL` or `DATABASE_TEST_URL` is absent. CI supplies
dedicated Redis and PostgreSQL service databases using immutable image digests and runs unit,
security, integration, contract, full-suite, Ruff, MyPy, compile, and Docker build steps.
