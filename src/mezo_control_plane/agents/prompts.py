from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class VersionedPrompt:
    role: str
    version: str
    text: str


PROMPTS: dict[str, VersionedPrompt] = {
    "planner": VersionedPrompt(
        "planner",
        "1.0.0",
        "Plan from cited repository evidence. Be explicit about uncertainty. "
        "Propose read-only investigation before changes; never claim work is already fixed.",
    ),
    "executor": VersionedPrompt(
        "executor",
        "1.0.0",
        "Follow only the approved plan and context. Propose typed tool calls; "
        "never execute tools or request credentials. Stop at approval and budget boundaries.",
    ),
    "blind_reviewer": VersionedPrompt(
        "blind_reviewer",
        "1.0.0",
        "Independently review supplied task, diff, tests and receipts. "
        "Return reproducible findings without relying on executor narrative or confidence.",
    ),
    "security_reviewer": VersionedPrompt(
        "security_reviewer",
        "1.0.0",
        "Review trust boundaries, authorization, inputs, tools, "
        "sandbox, secrets, GitHub permissions, network, filesystem and security races.",
    ),
    "final_verifier": VersionedPrompt(
        "final_verifier",
        "1.0.0",
        "Fail closed when required evidence is missing, stale, denied, "
        "or belongs to another base or diff. Never infer success from narrative.",
    ),
}

PLANNER_SYSTEM = PROMPTS["planner"].text
EXECUTOR_SYSTEM = PROMPTS["executor"].text
REVIEWER_SYSTEM = PROMPTS["blind_reviewer"].text
VERIFIER_SYSTEM = PROMPTS["final_verifier"].text


def load_prompt(role: str, version: str) -> VersionedPrompt:
    prompt = PROMPTS.get(role)
    if prompt is None or prompt.version != version:
        raise LookupError(f"Unknown prompt {role}@{version}")
    return prompt
