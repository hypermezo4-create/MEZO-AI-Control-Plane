# GitHub App boundary

GitHub App authentication signs short-lived RS256 JWTs and exchanges them through a typed boundary.
Installation tokens remain in memory, refresh early, collapse concurrent refreshes, and are never
included in errors or model context.

Every write verifies repository allowlisting, installation permission, target branch, expected base
SHA, path confinement, and payload limits. Protected-branch and workflow writes are denied without
the separate approval path. Multi-file commit requests are deterministic and base movement causes a
conflict. Draft Pull Requests include evidence but are never approved or merged by the agent.

Webhooks use HMAC SHA-256 with constant-time comparison, body and delivery-ID limits, replay claims,
event allowlisting, and repository identity validation. Unknown events are non-actionable.
