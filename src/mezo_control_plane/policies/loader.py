from __future__ import annotations

from pathlib import Path

import yaml  # type: ignore[import-untyped]
from pydantic import TypeAdapter, ValidationError

from mezo_control_plane.policies.models import PolicyRule


class PolicyLoadError(RuntimeError):
    pass


def load_policy_rules(path: Path) -> tuple[PolicyRule, ...]:
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        rules = TypeAdapter(tuple[PolicyRule, ...]).validate_python(payload)
    except (OSError, UnicodeDecodeError, yaml.YAMLError, ValidationError) as error:
        raise PolicyLoadError("Declarative policy failed validation") from error
    identifiers = [rule.rule_id for rule in rules]
    if len(set(identifiers)) != len(identifiers):
        raise PolicyLoadError("Declarative policy rule IDs must be unique")
    return tuple(sorted(rules, key=lambda rule: (-rule.priority, rule.rule_id)))
