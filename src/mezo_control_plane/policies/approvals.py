from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from mezo_control_plane.policies.models import ApprovalDecision, ApprovalRecord


class ApprovalValidationError(RuntimeError):
    pass


class ApprovalStore:
    def __init__(self) -> None:
        self._records: dict[str, ApprovalRecord] = {}
        self._used: set[str] = set()
        self._lock = asyncio.Lock()

    async def add(self, approval: ApprovalRecord) -> None:
        async with self._lock:
            if approval.approval_id in self._records:
                raise ApprovalValidationError("Approval record is immutable")
            self._records[approval.approval_id] = approval

    async def consume(
        self,
        approval_id: str,
        *,
        task_id: str,
        scope: tuple[str, ...],
        base_sha: str,
        plan_hash: str,
        diff_hash: str | None,
        actor_role: str,
        now: datetime | None = None,
    ) -> ApprovalRecord:
        async with self._lock:
            approval = self._records.get(approval_id)
            if approval is None:
                raise ApprovalValidationError("Approval does not exist")
            current = now or datetime.now(UTC)
            if approval.decision is not ApprovalDecision.APPROVED:
                raise ApprovalValidationError("Approval was rejected")
            if approval.expires_at <= current:
                raise ApprovalValidationError("Approval expired")
            if approval.one_time and approval_id in self._used:
                raise ApprovalValidationError("Approval was already used")
            if approval.task_id != task_id or not set(scope).issubset(approval.scope):
                raise ApprovalValidationError("Approval scope mismatch")
            if approval.base_sha != base_sha or approval.plan_hash != plan_hash:
                raise ApprovalValidationError("Approval base or plan changed")
            if approval.diff_hash is not None and approval.diff_hash != diff_hash:
                raise ApprovalValidationError("Approval diff scope changed")
            if approval.actor_role not in {"owner", actor_role}:
                raise ApprovalValidationError("Approval actor role is insufficient")
            if approval.one_time:
                self._used.add(approval_id)
            return approval
