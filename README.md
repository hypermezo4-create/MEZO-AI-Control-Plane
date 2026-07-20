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

## Quick start

```bash
cp .env.example .env
docker compose up --build
```

Open `http://localhost:8080/health/live`.

## Checks

```bash
python -m pip install -e '.[dev]'
ruff check .
mypy src
pytest
```
