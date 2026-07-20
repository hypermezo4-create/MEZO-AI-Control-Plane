# ADR 0001: Canonical runtime layout

## Context

Issue #1 describes a capability map that includes `apps`, `agents`, `database`, `queue`, and
other domains. The scaffold already exposes `src/mezo_control_plane` as its package.

## Decision

Runtime implementations live exactly once below `src/mezo_control_plane`. The `api`, `worker`,
and future Telegram and dashboard adapters are package modules, while root-level directories are
reserved for operational configuration, documentation, tests, and static assets. Consumer-facing
contracts are defined in `core` and infrastructure adapters implement those contracts without
being imported by domain models.

## Consequences

This avoids parallel root-level and package implementations, keeps import paths stable, and allows
tests to substitute infrastructure at explicit interfaces. Database migrations and deploy changes
remain approval-gated because they have cross-release effects.
