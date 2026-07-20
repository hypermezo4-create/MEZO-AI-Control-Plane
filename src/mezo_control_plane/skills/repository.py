from __future__ import annotations

from pathlib import Path

from mezo_control_plane.repository_intelligence.acquisition import RepositoryAcquirer


class SkillRepository:
    def __init__(
        self,
        acquirer: RepositoryAcquirer,
        *,
        repository: str,
        commit_sha: str,
        remote_url: str,
    ) -> None:
        self._acquirer = acquirer
        self.repository = repository
        self.commit_sha = commit_sha
        self.remote_url = remote_url

    async def checkout(self, destination: Path) -> Path:
        return await self._acquirer.acquire(
            self.repository, self.remote_url, self.commit_sha, destination
        )
