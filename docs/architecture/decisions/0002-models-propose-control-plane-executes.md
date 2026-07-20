# ADR 0002: Models propose; the control plane executes

Status: accepted

Models and repository/skill text are untrusted. Agents may return typed proposals, but only the tool
registry, policy engine, approval store, sandbox, and GitHub adapter can authorize or perform effects.
Credentials are injected only inside the infrastructure adapter and are excluded from agent inputs and
evidence. This preserves one enforcement path for API, Telegram, workers, and future dashboard callers.
