from dataclasses import dataclass


@dataclass(frozen=True)
class RepositoryContext:
    repository: str
    base_branch: str
    file_tree: tuple[str, ...]
    project_rules: str
    relevant_files: dict[str, str]

    def render(self) -> str:
        files = "\n".join(
            f"## {path}\n{content}" for path, content in self.relevant_files.items()
        )
        return (
            f"Repository: {self.repository}\n"
            f"Base branch: {self.base_branch}\n"
            f"Rules:\n{self.project_rules}\n"
            f"Files:\n{files}"
        )
