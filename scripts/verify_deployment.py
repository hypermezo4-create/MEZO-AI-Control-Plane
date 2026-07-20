from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from urllib.parse import urljoin

import httpx


@dataclass(frozen=True)
class Check:
    path: str
    authenticated: bool
    expected_content_type: str | None = "application/json"


def main() -> None:
    base_url = os.environ.get("MEZO_BASE_URL", "").rstrip("/") + "/"
    api_key = os.environ.get("MEZO_API_KEY", "")
    if base_url == "/":
        raise SystemExit("MEZO_BASE_URL is required")
    checks = (
        Check("health/live", False),
        Check("health/ready", False),
        Check("v1/tasks?offset=0&limit=1", True),
        Check("v1/observability/alerts", True),
        Check("metrics", True, "text/plain"),
    )
    with httpx.Client(timeout=10.0, follow_redirects=False) as client:
        for check in checks:
            headers = {"x-api-key": api_key} if check.authenticated else {}
            response = client.get(urljoin(base_url, check.path), headers=headers)
            if response.status_code != 200:
                message = f"verification failed: {check.path} returned {response.status_code}"
                raise SystemExit(message)
            content_type = response.headers.get("content-type", "")
            if check.expected_content_type and check.expected_content_type not in content_type:
                raise SystemExit(
                    f"verification failed: {check.path} returned unexpected content type"
                )
            print(f"PASS {check.path}")
    print("Deployment verification passed")


if __name__ == "__main__":
    try:
        main()
    except httpx.HTTPError as error:
        print(f"verification failed: {type(error).__name__}", file=sys.stderr)
        raise SystemExit(1) from error
