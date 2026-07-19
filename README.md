# MEZO AI Control Plane

Cloud-native control plane for orchestrating coding agents across GitHub repositories using two independent Gemini projects, a self-hosted Qwen endpoint, versioned agent skills, isolated execution workers, evidence-based reviews, and protected pull-request delivery.

## Status

This repository contains the first production-oriented scaffold of the platform. It is designed to run on Fly.io as a control plane and worker service. Model inference is external: Gemini through Google APIs and Qwen through an OpenAI-compatible GPU endpoint.

## Core principles

- No direct changes to protected branches.
- Every coding task runs through a state machine.
- Plans, patches, tests, guard reports, and reviews are stored as evidence.
- Gemini Project A plans and executes; Gemini Project B reviews independently and provides failover.
- Qwen provides an independent open-weight coding and review path.
- Shell execution is isolated and policy-gated.
- Secrets never live in Git.
- A task is not successful until mechanical checks pass.

## Architecture

```text
Telegram / Web / GitHub Webhooks
              |
              v
      Fly.io Control Plane
 API + Orchestrator + Model Router
              |
     +--------+---------+
     |                  |
 Gemini A/B       Qwen GPU Endpoint
     |                  |
     +--------+---------+
              |
       Isolated Worker
              |
 Tests + Skills + Blind Review
              |
       GitHub Pull Request
```

## Services

- `web`: FastAPI API, health checks, task submission and approvals.
- `worker`: claims queued tasks, runs the workflow and stores evidence.
- PostgreSQL: persistent task, execution, review and audit state.
- Redis: queue, deduplication and short-lived coordination.
- External model providers: Gemini A, Gemini B and Qwen.

## Quick start

```bash
cp .env.example .env
docker compose up --build
```

Then open `http://localhost:8080/health`.

## Required secrets

- `DATABASE_URL`
- `REDIS_URL`
- `GEMINI_API_KEY_PRIMARY`
- `GEMINI_API_KEY_SECONDARY`
- `QWEN_BASE_URL`
- `QWEN_API_KEY`
- `GITHUB_APP_ID`
- `GITHUB_APP_PRIVATE_KEY`
- `GITHUB_WEBHOOK_SECRET`
- `CONTROL_PLANE_API_KEY`

## Local checks

```bash
python -m pip install -e '.[dev]'
ruff check .
mypy src
pytest
```

## Repository map

```text
src/mezo_control_plane/
├── api/                 FastAPI routes and authentication
├── agents/              Planner, executor, reviewer and verifier contracts
├── core/                Settings, errors and shared domain types
├── database/            SQLAlchemy models and sessions
├── github/              GitHub provider contracts
├── model_router/        Routing, failover and circuit breakers
├── observability/       Structured logging and health
├── orchestrator/        Task state machine and workflow engine
├── policies/            Risk, approval and command policy
├── providers/           Gemini and Qwen clients
├── queue/               Redis-backed task queue
├── repository_intelligence/ Repository context construction
├── sandbox/             Isolated command execution contracts
├── skills/              Skill selection and receipts
└── worker/              Task consumer
```

## Safety model

The model never receives unrestricted infrastructure credentials. It proposes tool calls; the control plane validates them against policy, repository scope, protected paths, command allowlists and approval rules before execution.

## Deployment

Fly configuration is included in `fly.toml`. The initial deployment uses two process groups:

- `web`: one control-plane machine.
- `worker`: one task worker machine.

Scale either group independently as traffic grows.

## Development state

The included integrations are intentionally interface-first. API, workflow state, provider routing, queueing, policy checks, health checks, testing and deployment scaffolding are implemented. GitHub App installation-token exchange and remote sandbox provisioning are explicit extension points and must be configured before production repository writes are enabled.

## License

Private project. All rights reserved unless a license is added explicitly.
