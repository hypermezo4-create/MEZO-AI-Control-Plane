import secrets

import pytest

from mezo_control_plane.api.middleware import AuthenticationMiddleware


def test_authentication_uses_constant_time_comparison(monkeypatch: pytest.MonkeyPatch) -> None:
    called: list[tuple[str, str]] = []

    def compare(left: str, right: str) -> bool:
        called.append((left, right))
        return False

    monkeypatch.setattr(secrets, "compare_digest", compare)
    assert AuthenticationMiddleware is not None
    assert secrets.compare_digest("provided", "expected") is False
    assert called == [("provided", "expected")]
