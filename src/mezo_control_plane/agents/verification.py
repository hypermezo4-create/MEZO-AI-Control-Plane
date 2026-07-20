from __future__ import annotations

from datetime import timedelta

from mezo_control_plane.agents.contracts import FinalVerifierInput, FinalVerifierOutput


def verify_final_evidence(value: FinalVerifierInput, *, max_age: timedelta) -> FinalVerifierOutput:
    missing: list[str] = []
    if not value.test_evidence:
        missing.append("test_evidence")
    if not value.guard_receipts:
        missing.append("guard_receipts")
    if any(finding.severity in {"critical", "important"} for finding in value.review_findings):
        missing.append("unresolved_review_findings")
    stale: list[str] = []
    if value.verification_time - value.evidence_created_at > max_age:
        stale.append("test_and_guard_evidence")
    if value.repository_head != value.expected_base:
        stale.append("base_branch_moved")
    reasons = tuple(f"missing:{item}" for item in missing) + tuple(
        f"stale:{item}" for item in stale
    )
    return FinalVerifierOutput(
        ready=not missing and not stale,
        missing_evidence=tuple(missing),
        stale_evidence=tuple(stale),
        reasons=reasons or ("required evidence is current",),
    )
