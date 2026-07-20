from dataclasses import dataclass


@dataclass(frozen=True)
class SkillSelection:
    names: tuple[str, ...]
    reasons: tuple[str, ...]


class SkillRouter:
    def select(self, changed_paths: list[str], instruction: str) -> SkillSelection:
        names = {"clean-code-guard", "security-guard"}
        reasons = ["Production changes require generic code and security review"]
        lowered = instruction.lower()
        if any("test" in path.lower() for path in changed_paths) or "test" in lowered:
            names.add("test-guard")
            reasons.append("Tests are in scope")
        if any(path.endswith((".md", ".rst")) for path in changed_paths):
            names.add("docs-guard")
            reasons.append("Documentation changed")
        if any(token in lowered for token in ("async", "queue", "worker", "race", "floodwait")):
            names.add("concurrency-guard")
            reasons.append("Concurrency-sensitive behavior detected")
        if any(token in lowered for token in ("database", "postgres", "migration", "sql")):
            names.add("database-guard")
            reasons.append("Database behavior detected")
        if any(path.startswith(("infra/", ".github/workflows/")) for path in changed_paths):
            names.add("deployment-guard")
            reasons.append("Deployment files changed")
        return SkillSelection(tuple(sorted(names)), tuple(reasons))
