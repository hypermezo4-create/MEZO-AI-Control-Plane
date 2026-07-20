from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class PullRequestResult:
    number: int
    url: str
    head_sha: str


class GitHubGateway(Protocol):
    async def create_task_branch(self, repository: str, base: str, branch: str) -> str: ...

    async def apply_patch(self, repository: str, branch: str, patch: str) -> str: ...

    async def open_pull_request(
        self, repository: str, base: str, head: str, title: str, body: str
    ) -> PullRequestResult: ...
