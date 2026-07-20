# Declarative policies

Policy precedence is global, repository, repository profile, then task. Matching rules are sorted
deterministically. A lower-priority allow cannot weaken any matched deny or mandatory platform deny or
approval requirement.

Risk considers changed paths/bytes, authentication and authorization, secrets, migrations, workflows,
infrastructure, deployment, network, dependencies, destructive commands, resource escalation, and
critical findings. Decisions include effect, risk, reasons, matched rules and versions, required skills
and checks, resource/network/tool limits, re-evaluation triggers, and a stable canonical hash.
