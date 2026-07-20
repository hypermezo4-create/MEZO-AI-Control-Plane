from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from mezo_control_plane.github.errors import GitHubError, GitHubFailureType


class GitHubTransport(Protocol):
    async def request(
        self,
        method: str,
        path: str,
        *,
        token: str,
        json_body: dict[str, Any] | None = None,
    ) -> tuple[int, dict[str, Any], dict[str, str]]: ...


class HttpxGitHubTransport:
    def __init__(self, base_url: str = "https://api.github.com", timeout: float = 20) -> None:
        self._client = httpx.AsyncClient(base_url=base_url, timeout=timeout, follow_redirects=False)

    async def request(
        self,
        method: str,
        path: str,
        *,
        token: str,
        json_body: dict[str, Any] | None = None,
    ) -> tuple[int, dict[str, Any], dict[str, str]]:
        try:
            response = await self._client.request(
                method,
                path,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
                json=json_body,
            )
        except httpx.HTTPError as error:
            raise GitHubError(
                GitHubFailureType.NETWORK, "GitHub request failed", retryable=True
            ) from error
        payload: dict[str, Any] = response.json() if response.content else {}
        return response.status_code, payload, dict(response.headers)


@dataclass(frozen=True)
class PermissionDecision:
    allowed: bool
    reason: str


class GitHubClient:
    def __init__(
        self,
        transport: GitHubTransport,
        *,
        allowed_repositories: frozenset[str],
        protected_branches: frozenset[str] = frozenset({"main", "master"}),
    ) -> None:
        self._transport = transport
        self._repositories = allowed_repositories
        self._protected = protected_branches

    def authorize(
        self, repository: str, branch: str, permissions: frozenset[str], required: str
    ) -> PermissionDecision:
        if repository not in self._repositories:
            return PermissionDecision(False, "repository_not_allowed")
        if branch in self._protected:
            return PermissionDecision(False, "protected_branch_write_denied")
        if required not in permissions:
            return PermissionDecision(False, f"missing_permission:{required}")
        return PermissionDecision(True, "allowed")

    async def create_branch(
        self,
        repository: str,
        base_sha: str,
        task_id: str,
        slug: str,
        token: str,
    ) -> str:
        branch = f"agent/{task_id}-{_slug(slug)}"
        status, payload, headers = await self._transport.request(
            "POST",
            f"/repos/{repository}/git/refs",
            token=token,
            json_body={"ref": f"refs/heads/{branch}", "sha": base_sha},
        )
        if status == 422 and payload.get("message") == "Reference already exists":
            return branch
        _raise_for_status(status, headers)
        return branch

    async def create_commit(
        self,
        repository: str,
        branch: str,
        expected_base: str,
        files: dict[str, str],
        token: str,
        expected_blob_shas: dict[str, str] | None = None,
    ) -> str:
        if branch in self._protected:
            raise GitHubError(
                GitHubFailureType.PERMISSION, "Protected branch writes are denied", retryable=False
            )
        if (
            not files
            or len(files) > 100
            or sum(len(value.encode()) for value in files.values()) > 5_000_000
        ):
            raise GitHubError(
                GitHubFailureType.VALIDATION, "Commit file or byte limit exceeded", retryable=False
            )
        for path in files:
            _validate_path(path)
        status, ref, headers = await self._transport.request(
            "GET", f"/repos/{repository}/git/ref/heads/{branch}", token=token
        )
        _raise_for_status(status, headers)
        if ref.get("object", {}).get("sha") != expected_base:
            raise GitHubError(GitHubFailureType.CONFLICT, "Base branch moved", retryable=False)
        for path, expected_sha in (expected_blob_shas or {}).items():
            _validate_path(path)
            status, current, headers = await self._transport.request(
                "GET",
                f"/repos/{repository}/contents/{path}?ref={expected_base}",
                token=token,
            )
            _raise_for_status(status, headers)
            if current.get("sha") != expected_sha:
                raise GitHubError(
                    GitHubFailureType.CONFLICT,
                    f"Blob changed before commit: {path}",
                    retryable=False,
                )
        status, base_commit, headers = await self._transport.request(
            "GET", f"/repos/{repository}/git/commits/{expected_base}", token=token
        )
        _raise_for_status(status, headers)
        base_tree = str(base_commit.get("tree", {}).get("sha", ""))
        if not base_tree:
            raise GitHubError(
                GitHubFailureType.SERVER, "GitHub base tree response is invalid", retryable=True
            )
        tree_entries: list[dict[str, object]] = []
        for path, content in sorted(files.items()):
            status, blob, headers = await self._transport.request(
                "POST",
                f"/repos/{repository}/git/blobs",
                token=token,
                json_body={"content": content, "encoding": "utf-8"},
            )
            _raise_for_status(status, headers)
            tree_entries.append(
                {"path": path, "mode": "100644", "type": "blob", "sha": str(blob["sha"])}
            )
        status, tree, headers = await self._transport.request(
            "POST",
            f"/repos/{repository}/git/trees",
            token=token,
            json_body={"base_tree": base_tree, "tree": tree_entries},
        )
        _raise_for_status(status, headers)
        status, result, headers = await self._transport.request(
            "POST",
            f"/repos/{repository}/git/commits",
            token=token,
            json_body={
                "message": "MEZO controlled change",
                "tree": str(tree["sha"]),
                "parents": [expected_base],
            },
        )
        _raise_for_status(status, headers)
        commit_sha = str(result["sha"])
        status, _, headers = await self._transport.request(
            "PATCH",
            f"/repos/{repository}/git/refs/heads/{branch}",
            token=token,
            json_body={"sha": commit_sha, "force": False},
        )
        _raise_for_status(status, headers)
        return commit_sha

    async def create_draft_pull_request(
        self,
        repository: str,
        base: str,
        head: str,
        title: str,
        body: str,
        token: str,
    ) -> tuple[int, str]:
        status, payload, headers = await self._transport.request(
            "POST",
            f"/repos/{repository}/pulls",
            token=token,
            json_body={"base": base, "head": head, "title": title, "body": body, "draft": True},
        )
        _raise_for_status(status, headers)
        return int(payload["number"]), str(payload["html_url"])

    async def approve_pull_request(self, *_args: object, **_kwargs: object) -> None:
        raise GitHubError(
            GitHubFailureType.PERMISSION,
            "The agent cannot approve its own pull request",
            retryable=False,
        )


def _raise_for_status(status: int, headers: dict[str, str]) -> None:
    if status < 400:
        return
    mapping = {
        401: (GitHubFailureType.AUTHENTICATION, False),
        403: (GitHubFailureType.PERMISSION, False),
        404: (GitHubFailureType.NOT_FOUND, False),
        409: (GitHubFailureType.CONFLICT, False),
        422: (GitHubFailureType.VALIDATION, False),
    }
    failure, retryable = mapping.get(status, (GitHubFailureType.SERVER, status >= 500))
    retry_after = headers.get("retry-after")
    raise GitHubError(
        failure,
        f"GitHub operation failed with status {status}",
        retryable=retryable,
        retry_after_seconds=float(retry_after) if retry_after else None,
    )


def _validate_path(path: str) -> None:
    normalized = path.replace("\\", "/")
    if normalized.startswith("/") or ".." in normalized.split("/") or normalized == ".git":
        raise GitHubError(GitHubFailureType.VALIDATION, "Invalid repository path", retryable=False)
    if normalized.startswith(".github/workflows/"):
        raise GitHubError(
            GitHubFailureType.PERMISSION,
            "Workflow changes require explicit approval",
            retryable=False,
        )


def _slug(value: str) -> str:
    result = "".join(character.lower() if character.isalnum() else "-" for character in value)
    return "-".join(part for part in result.split("-") if part)[:48] or "task"
