from __future__ import annotations

import json

from mezo_control_plane.evals.cases import default_cases
from mezo_control_plane.evals.runner import run_suite


def run() -> None:
    result = run_suite(default_cases())
    print(json.dumps(result.model_dump(mode="json"), indent=2, sort_keys=True))
    if result.failed:
        raise SystemExit(1)


if __name__ == "__main__":
    run()
