# Fly.io Production Deployment

Production deployment is intentionally manual. Merging a branch does not deploy it.

## Required controls

1. Protect the GitHub `production` environment with required reviewers.
2. Store `FLY_API_TOKEN` and `CONTROL_PLANE_API_KEY` only as environment-scoped GitHub secrets.
3. Configure Fly secrets for `DATABASE_URL`, `REDIS_URL`, `CONTROL_PLANE_API_KEY`, provider keys, and GitHub App credentials.
4. `DATABASE_URL` may use Fly/Postgres forms such as `postgres://`, `postgresql://`, or `postgresql+asyncpg://`; the application and Alembic normalize the driver locally without logging the URL.
5. Keep web and worker process groups separately sized.

## Release procedure

1. Confirm CI, CodeQL, secret scan, dependency review, Trivy, evals, and guard receipts are green.
2. Review the migration plan and database backup status.
3. Dispatch **Deploy Fly** and type exactly `DEPLOY`.
4. Approve the protected GitHub environment.
5. Fly runs `alembic upgrade head` as the release command before the rolling deployment.
6. The workflow verifies Fly checks and public live/readiness endpoints.
7. Run the authenticated verification suite:

```bash
MEZO_BASE_URL=https://mezo-ai-control-plane.fly.dev \
MEZO_API_KEY='...' \
python scripts/verify_deployment.py
```

## Rollback

Application rollback and schema rollback are separate decisions.

1. Stop new task submissions or place the service in an operator-controlled maintenance state.
2. Inspect `fly releases --app mezo-ai-control-plane` and identify the last verified image.
3. Roll back the application image using Fly's release rollback command.
4. Do not run an Alembic downgrade automatically. Review whether the deployed migration is backward compatible and restore from the verified backup when a destructive rollback is required.
5. Re-run live, readiness, task read, alerts, and metrics verification.
6. Record the incident, release identifier, migration state, and evidence digest.

A failed release command prevents the new machines from replacing the current release. It does not authorize destructive database recovery.
