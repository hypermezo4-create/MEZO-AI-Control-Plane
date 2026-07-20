# Approval records

Approvals are immutable, scoped to one task and path/action set, actor and role, base SHA, plan hash,
optional diff hash, policy version, evidence hash, and expiry. One-time approvals are consumed with an
atomic compare inside the approval store. Reuse, expiry, denial, role mismatch, scope expansion, base
movement, plan changes, and protected diff changes invalidate an approval.

Workflow, migration, production deployment, secret, protected-path, network expansion, resource
escalation, destructive, and critical-finding exception operations require the corresponding policy
decision and owner approval.
