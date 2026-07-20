# MEZO AI Control Plane

Cloud-native control plane for orchestrating coding agents across GitHub repositories using two independent Gemini projects, a self-hosted Qwen endpoint, versioned agent skills, isolated execution workers, evidence-based reviews, and protected pull-request delivery.

## Purpose

This is the central repository of the MEZO agent platform. It receives coding tasks, builds repository context, routes work to the appropriate model, enforces permissions and risk policy, coordinates worker execution, stores evidence, runs review gates, and prepares GitHub pull requests.

Model inference does not run on the user's computer. Gemini is called through two independent API projects, while Qwen is exposed through an OpenAI-compatible GPU endpoint managed by the separate `MEZO-Model-Server` repository.

## Architecture

```text
Telegram / Dashboard / GitHub Webhooks
                 |
                 v
        Fly.io Control Plane
 API + Authentication + Task Queue
                 |
        Agent Orchestrator
                 |
   +-------------+--------------+
   |             |              |
Gemini A     Gemini B       Qwen Endpoint
Planner      Blind Review   Executor/Fallback
   |             |              |
   +-------------+--------------+
                 |
        Policy-gated Worker
                 |
 Repository Context + Sandbox + Tests
                 |
 Skills Guards + Independent Review
                 |
          GitHub Pull Request
```

## Implemented foundation

- FastAPI service with authenticated task submission.
- Liveness and readiness endpoints.
- Redis-backed task queue.
- PostgreSQL-compatible SQLAlchemy task model and async session factory.
- Explicit task state machine with guarded transitions.
- Risk and approval policy engine.
- Dual-Gemini routing with retry and project failover.
- OpenAI-compatible Qwen provider.
- Role-based model routing for planning, execution, review, fast work, and fallback.
- Repository-context data contract.
- Scoped GitHub App authentication, webhook, branch, commit, checks, and Draft PR boundaries.
- Targeted repository analysis with immutable source citations and sensitive-content exclusion.
- Resumable bounded planner, executor, review, security-review, and final-verification workflow.
- Non-root Docker sandbox, Fly Machines boundary, typed tool registry, and transactional patch application.
- Versioned integrity-checked skills plus deterministic risk and approval policy enforcement.
- Structured JSON logging.
- Docker and Docker Compose configuration.
- Fly.io web and worker process groups.
- CI, CodeQL, secret scanning, and manual Fly deployment workflows.
- Strict Ruff, MyPy, and Pytest checks.

## Safety principles

- Models never receive unrestricted infrastructure credentials.
- Model output and tool calls are treated as untrusted input.
- No direct push to protected branches.
- Every write is scoped to a task branch.
- Workflow, migration, production infrastructure, secret, and destructive changes require approval.
- Tests cannot be weakened or skipped to manufacture success.
- Every completion claim must be backed by command output or provider evidence.
- Secrets must be stored in Fly secrets or another secret manager, never in Git.

## Repository structure

```text
MEZO-AI-Control-Plane/
├── src/mezo_control_plane/
│   ├── agents/                  Agent instructions and output contracts
│   ├── api/                     FastAPI application and routes
│   ├── core/                    Settings, domain models, and errors
│   ├── database/                SQLAlchemy models and sessions
│   ├── github/                  GitHub gateway contracts
│   ├── model_router/            Routing, retries, and failover
│   ├── observability/           Structured logging
│   ├── orchestrator/            State machine and workflow engine
│   ├── policies/                Runtime policy evaluation
│   ├── providers/               Gemini and Qwen clients
│   ├── queue/                   Redis task queue
│   ├── repository_intelligence/ Repository context contracts
│   ├── sandbox/                 Isolated execution contracts
│   ├── skills/                  Skill routing
│   └── worker/                  Queue consumer
├── policies/                    Declarative permissions and model routing
├── tests/                       State, routing, policy, and skill tests
├── .github/workflows/           CI, security, and deployment automation
├── Dockerfile
├── docker-compose.yml
└── fly.toml
```

## Model roles

| Role | Primary route | Fallback routes |
| --- | --- | --- |
| Fast analysis | Gemini Project A Flash | Gemini Project B Flash |
| Planning | Gemini Project A Pro | Qwen, then Gemini Project B Pro |
| Execution | Qwen | Gemini Project A Flash, then Project B Flash |
| Blind review | Gemini Project B Pro | Qwen |
| Emergency fallback | Qwen | Gemini Project B Flash |

The exact model IDs are configuration values. Stable production aliases should be pinned deliberately and updated through reviewed changes.

## Local development

Requirements:

- Python 3.12+
- Docker with Compose
- PostgreSQL and Redis, or the included Compose services

```bash
cp .env.example .env
docker compose up --build
```

The API will be available at:

```text
http://localhost:8080/health/live
http://localhost:8080/health/ready
```

Submit a dry-run task:

```bash
export CONTROL_PLANE_API_KEY='set-a-local-development-key'
curl -X POST http://localhost:8080/v1/tasks \
  -H 'Content-Type: application/json' \
  -H "X-API-Key: ${CONTROL_PLANE_API_KEY}" \
  -d '{
    "repository": "owner/repository",
    "instruction": "Analyze the failure and prepare a safe fix",
    "base_branch": "main",
    "dry_run": true
  }'
```

## Required configuration

```text
CONTROL_PLANE_API_KEY
DATABASE_URL
REDIS_URL
GEMINI_API_KEY_PRIMARY
GEMINI_API_KEY_SECONDARY
GEMINI_PRIMARY_MODEL
GEMINI_REVIEW_MODEL
QWEN_BASE_URL
QWEN_API_KEY
QWEN_MODEL
GITHUB_APP_ID
GITHUB_APP_PRIVATE_KEY
GITHUB_WEBHOOK_SECRET
SKILLS_REPOSITORY
```

Do not commit real values. Configure production values with `fly secrets set` or a dedicated secret manager.

## Quality checks

```bash
python -m pip install -e '.[dev]'
ruff check .
mypy src
pytest -q
```

Current verified local result for the initial scaffold:

```text
Ruff: passed
MyPy: passed across 42 source files
Pytest: the full test suite
```

## Fly.io deployment

The included `fly.toml` defines two process groups:

- `web`: API and control-plane endpoints.
- `worker`: background task consumption and orchestration.

The deployment workflow is manual by design and requires the protected `production` environment plus `FLY_API_TOKEN`.

Before the first deployment:

1. Confirm or change the Fly app name and primary region in `fly.toml`.
2. Provision PostgreSQL and Redis.
3. Add all required secrets.
4. Configure the GitHub App and install it only on approved repositories.
5. Connect `MEZO-Agent-Skills`.
6. Connect the Qwen endpoint from `MEZO-Model-Server`.
7. Protect `main` and require CI, security checks, and pull-request approval.

## Integration boundaries

This repository intentionally owns orchestration and policy. It does not contain model weights or the full skill library.

- `MEZO-Agent-Skills` owns versioned skills, guard references, validation, and project profiles.
- `MEZO-Model-Server` owns Qwen serving, GPU configuration, health, benchmarks, and model deployment.
- Target repositories remain separate and are accessed through a narrowly scoped GitHub App.

The runtime includes typed GitHub App token exchange, repository acquisition, sandbox provisioning,
patch validation, Draft Pull Request preparation, and persistent workflow evidence. Default tests use
controlled transports and do not perform external writes. Live GitHub App, model-server, Telegram, and
Fly verification remain owner-triggered and require deployment secrets.

## Branch and delivery policy

- `main` is the release branch.
- Agent tasks must use `agent/<task-id>-<slug>` branches.
- Production code reaches `main` through pull requests only.
- Changes to workflows, migrations, secrets, production infrastructure, or destructive operations require explicit approval.
- The agent cannot approve its own pull request.

## License

No open-source license has been granted. All rights are reserved unless the repository owner adds a license explicitly.
