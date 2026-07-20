from dataclasses import dataclass
from pathlib import PurePosixPath

from mezo_control_plane.core.domain import RiskLevel
from mezo_control_plane.core.errors import PolicyDenied


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    risk: RiskLevel
    approval_required: bool
    reason: str


class PolicyEngine:
    def __init__(self) -> None:
        self._blocked_commands = {"rm", "mkfs", "shutdown", "reboot", "dd"}
        self._protected_roots = {".github/workflows", "migrations", "infra/production"}

    def evaluate_command(self, command: list[str]) -> PolicyDecision:
        if not command:
            raise PolicyDenied("Empty commands are not permitted")
        executable = PurePosixPath(command[0]).name
        if executable in self._blocked_commands:
            return PolicyDecision(False, RiskLevel.CRITICAL, True, "Destructive command blocked")
        return PolicyDecision(True, RiskLevel.MEDIUM, False, "Command permitted by base policy")

    def evaluate_paths(self, paths: list[str]) -> PolicyDecision:
        normalized = {str(PurePosixPath(path)) for path in paths}
        protected = sorted(
            path
            for path in normalized
            if any(path == root or path.startswith(f"{root}/") for root in self._protected_roots)
        )
        if protected:
            return PolicyDecision(
                True,
                RiskLevel.HIGH,
                True,
                f"Protected paths require approval: {', '.join(protected)}",
            )
        return PolicyDecision(True, RiskLevel.MEDIUM, False, "No protected paths touched")
