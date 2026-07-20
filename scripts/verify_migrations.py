from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


def main() -> None:
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    script = ScriptDirectory.from_config(config)
    heads = script.get_heads()
    if len(heads) != 1:
        raise SystemExit(f"expected one migration head, found {heads}")
    revisions = list(script.walk_revisions())
    identifiers = [revision.revision for revision in revisions]
    if len(identifiers) != len(set(identifiers)):
        raise SystemExit("duplicate migration revision identifiers found")
    print(f"Migration graph valid: {len(revisions)} revisions, head={heads[0]}")


if __name__ == "__main__":
    main()
