import random

import pytest

from mezo_control_plane.queue.deduplication import normalize_idempotency_key, task_deduplication_key
from mezo_control_plane.queue.leases import Lease
from mezo_control_plane.queue.retry_policy import RetryPolicy


def test_idempotency_key_is_normalized_before_hashing() -> None:
    assert task_deduplication_key(" task-1 ") == task_deduplication_key("task-1")


def test_empty_idempotency_key_is_rejected() -> None:
    with pytest.raises(ValueError):
        normalize_idempotency_key("   ")


def test_lease_has_an_owner_and_future_expiry() -> None:
    lease = Lease.new("task-1", "worker-token", 30)
    assert lease.task_id == "task-1"
    assert lease.owner_token == "worker-token"  # noqa: S105


def test_retry_policy_stops_after_budget() -> None:
    random.seed(1)
    policy = RetryPolicy(maximum_attempts=2)
    assert policy.decide(1, True).retry
    assert not policy.decide(2, True).retry
    assert not policy.decide(1, False).retry
