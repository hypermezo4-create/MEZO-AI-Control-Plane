from mezo_control_plane.queue.deduplication import normalize_idempotency_key


def test_idempotency_key_rejects_control_whitespace_only_value() -> None:
    try:
        normalize_idempotency_key("\t\n")
    except ValueError:
        return
    raise AssertionError("Whitespace-only idempotency keys must be rejected")
