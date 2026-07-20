import hashlib


def normalize_idempotency_key(key: str) -> str:
    normalized = key.strip()
    if not normalized or len(normalized) > 255:
        raise ValueError("Idempotency key must contain 1 to 255 non-whitespace characters")
    return normalized


def task_deduplication_key(idempotency_key: str) -> str:
    return hashlib.sha256(normalize_idempotency_key(idempotency_key).encode()).hexdigest()
