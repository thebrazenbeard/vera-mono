from __future__ import annotations

from dataclasses import dataclass
import base64
import json
from typing import Any, Mapping, Protocol, runtime_checkable
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from .github_source_transport import (
    GitHubCommitState,
    GitHubPathState,
    GitHubSourceTransportError,
    GitHubTreeUpdate,
)


class GitHubAPIError(GitHubSourceTransportError):
    pass


@dataclass(frozen=True, slots=True)
class GitHubHTTPResult:
    status: int
    payload: Any


@runtime_checkable
class GitHubJSONHTTPTransport(Protocol):
    def request_json(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        body: Mapping[str, Any] | None = None,
    ) -> GitHubHTTPResult:
        ...


class UrllibGitHubJSONHTTPTransport:
    """Standard-library HTTPS transport. Credentials stay in caller memory."""

    def request_json(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        body: Mapping[str, Any] | None = None,
    ) -> GitHubHTTPResult:
        raw = None
        request_headers = dict(headers)
        if body is not None:
            raw = json.dumps(
                body,
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
            ).encode("utf-8")
            request_headers["Content-Type"] = "application/json"
        request = Request(
            url,
            data=raw,
            headers=request_headers,
            method=method,
        )
        try:
            with urlopen(request, timeout=30) as response:
                response_body = response.read()
                payload = (
                    None
                    if not response_body
                    else json.loads(response_body.decode("utf-8"))
                )
                return GitHubHTTPResult(
                    status=int(response.status),
                    payload=payload,
                )
        except HTTPError as exc:
            body_bytes = exc.read()
            try:
                payload = (
                    None
                    if not body_bytes
                    else json.loads(body_bytes.decode("utf-8"))
                )
            except (UnicodeDecodeError, json.JSONDecodeError):
                payload = {"message": "non-JSON GitHub error response"}
            raise GitHubAPIError(
                f"GitHub HTTP {exc.code}: {payload!r}"
            ) from exc
        except URLError as exc:
            raise GitHubAPIError(
                f"GitHub network error: {exc.reason!r}"
            ) from exc


class GitHubGitDataAPIClient:
    """Concrete GitHub REST + GraphQL Git Data client.

    REST creates/reads Git objects. GraphQL updateRefs performs exact ref CAS via
    beforeOid/afterOid. The token is injected at construction and is never
    persisted by this class.
    """

    DEFAULT_API_VERSION = "2026-03-10"

    def __init__(
        self,
        *,
        token: str,
        http: GitHubJSONHTTPTransport | None = None,
        api_base: str = "https://api.github.com",
        graphql_url: str = "https://api.github.com/graphql",
        api_version: str = DEFAULT_API_VERSION,
    ):
        if type(token) is not str or not token:
            raise ValueError("GitHub token must be a non-empty exact string")
        if http is not None and not isinstance(http, GitHubJSONHTTPTransport):
            raise TypeError("http must satisfy GitHubJSONHTTPTransport")
        self._token = token
        self._http = http or UrllibGitHubJSONHTTPTransport()
        self.api_base = api_base.rstrip("/")
        self.graphql_url = graphql_url
        self.api_version = api_version
        self._repository_ids: dict[str, str] = {}

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self._token}",
            "X-GitHub-Api-Version": self.api_version,
            "User-Agent": "vera-mono-qualified-source-transport",
        }

    @staticmethod
    def _repo_parts(repository: str) -> tuple[str, str]:
        if type(repository) is not str:
            raise GitHubAPIError("repository must be an exact owner/name string")
        parts = repository.split("/")
        if (
            len(parts) != 2
            or not parts[0]
            or not parts[1]
        ):
            raise GitHubAPIError(
                "repository must use exact owner/name form"
            )
        return parts[0], parts[1]

    def _rest(
        self,
        method: str,
        repository: str,
        suffix: str,
        *,
        body: Mapping[str, Any] | None = None,
    ) -> Any:
        owner, name = self._repo_parts(repository)
        url = (
            f"{self.api_base}/repos/{quote(owner, safe='')}/"
            f"{quote(name, safe='')}/{suffix.lstrip('/')}"
        )
        result = self._http.request_json(
            method,
            url,
            headers=self._headers,
            body=body,
        )
        if not 200 <= result.status < 300:
            raise GitHubAPIError(
                f"unexpected GitHub HTTP status {result.status}"
            )
        return result.payload

    def _graphql(
        self,
        query: str,
        variables: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        result = self._http.request_json(
            "POST",
            self.graphql_url,
            headers=self._headers,
            body={
                "query": query,
                "variables": dict(variables),
            },
        )
        if not 200 <= result.status < 300:
            raise GitHubAPIError(
                f"unexpected GitHub GraphQL HTTP status {result.status}"
            )
        payload = result.payload
        if not isinstance(payload, Mapping):
            raise GitHubAPIError(
                "GitHub GraphQL response must be an object"
            )
        errors = payload.get("errors")
        if errors:
            raise GitHubAPIError(
                f"GitHub GraphQL rejected request: {errors!r}"
            )
        data = payload.get("data")
        if not isinstance(data, Mapping):
            raise GitHubAPIError(
                "GitHub GraphQL response is missing data"
            )
        return data

    def get_ref_head(self, repository: str, ref: str) -> str:
        if type(ref) is not str or not ref:
            raise GitHubAPIError("ref must be a non-empty exact string")
        branch = (
            ref[len("refs/heads/") :]
            if ref.startswith("refs/heads/")
            else ref
        )
        payload = self._rest(
            "GET",
            repository,
            "git/ref/" + quote(f"heads/{branch}", safe="/"),
        )
        try:
            value = payload["object"]["sha"]
        except (TypeError, KeyError) as exc:
            raise GitHubAPIError(
                "GitHub ref response is missing object.sha"
            ) from exc
        if type(value) is not str or not value:
            raise GitHubAPIError(
                "GitHub ref response carries invalid object.sha"
            )
        return value

    def get_commit(
        self,
        repository: str,
        commit_sha: str,
    ) -> GitHubCommitState:
        payload = self._rest(
            "GET",
            repository,
            "git/commits/" + quote(commit_sha, safe=""),
        )
        try:
            observed_sha = payload["sha"]
            tree_sha = payload["tree"]["sha"]
        except (TypeError, KeyError) as exc:
            raise GitHubAPIError(
                "GitHub commit response is incomplete"
            ) from exc
        if observed_sha != commit_sha:
            raise GitHubAPIError(
                "GitHub commit response SHA mismatch"
            )
        if type(tree_sha) is not str or not tree_sha:
            raise GitHubAPIError(
                "GitHub commit response carries invalid tree SHA"
            )
        return GitHubCommitState(
            commit_sha=observed_sha,
            tree_sha=tree_sha,
        )

    def get_path(
        self,
        repository: str,
        path: str,
        commit_sha: str,
    ) -> GitHubPathState | None:
        commit = self.get_commit(repository, commit_sha)
        payload = self._rest(
            "GET",
            repository,
            "git/trees/"
            + quote(commit.tree_sha, safe="")
            + "?recursive=1",
        )
        if not isinstance(payload, Mapping):
            raise GitHubAPIError(
                "GitHub tree response must be an object"
            )
        if payload.get("truncated") is True:
            raise GitHubAPIError(
                "GitHub recursive tree response is truncated; exact path "
                "identity cannot be established"
            )
        tree = payload.get("tree")
        if not isinstance(tree, list):
            raise GitHubAPIError(
                "GitHub tree response is missing tree entries"
            )
        matches = [
            item
            for item in tree
            if isinstance(item, Mapping)
            and item.get("path") == path
        ]
        if not matches:
            return None
        if len(matches) != 1:
            raise GitHubAPIError(
                "GitHub tree response contains duplicate exact path"
            )
        item = matches[0]
        sha = item.get("sha")
        mode = item.get("mode")
        object_type = item.get("type")
        if not all(
            type(value) is str and value
            for value in (sha, mode, object_type)
        ):
            raise GitHubAPIError(
                "GitHub tree entry is incomplete"
            )
        return GitHubPathState(
            blob_sha=sha,
            mode=mode,
            object_type=object_type,
        )

    def create_blob(
        self,
        repository: str,
        content: bytes,
    ) -> str:
        if type(content) is not bytes:
            raise TypeError("GitHub blob content must be exact bytes")
        payload = self._rest(
            "POST",
            repository,
            "git/blobs",
            body={
                "content": base64.b64encode(content).decode("ascii"),
                "encoding": "base64",
            },
        )
        try:
            sha = payload["sha"]
        except (TypeError, KeyError) as exc:
            raise GitHubAPIError(
                "GitHub create-blob response is missing sha"
            ) from exc
        if type(sha) is not str or not sha:
            raise GitHubAPIError(
                "GitHub create-blob response carries invalid sha"
            )
        return sha

    def create_tree(
        self,
        repository: str,
        *,
        base_tree_sha: str,
        updates: tuple[GitHubTreeUpdate, ...],
    ) -> str:
        payload = self._rest(
            "POST",
            repository,
            "git/trees",
            body={
                "base_tree": base_tree_sha,
                "tree": [
                    {
                        "path": update.path,
                        "mode": update.mode,
                        "type": update.object_type,
                        "sha": update.sha,
                    }
                    for update in updates
                ],
            },
        )
        try:
            sha = payload["sha"]
        except (TypeError, KeyError) as exc:
            raise GitHubAPIError(
                "GitHub create-tree response is missing sha"
            ) from exc
        if type(sha) is not str or not sha:
            raise GitHubAPIError(
                "GitHub create-tree response carries invalid sha"
            )
        return sha

    def create_commit(
        self,
        repository: str,
        *,
        message: str,
        tree_sha: str,
        parent_sha: str,
    ) -> str:
        payload = self._rest(
            "POST",
            repository,
            "git/commits",
            body={
                "message": message,
                "tree": tree_sha,
                "parents": [parent_sha],
            },
        )
        try:
            sha = payload["sha"]
        except (TypeError, KeyError) as exc:
            raise GitHubAPIError(
                "GitHub create-commit response is missing sha"
            ) from exc
        if type(sha) is not str or not sha:
            raise GitHubAPIError(
                "GitHub create-commit response carries invalid sha"
            )
        return sha

    def _repository_id(self, repository: str) -> str:
        cached = self._repository_ids.get(repository)
        if cached is not None:
            return cached
        owner, name = self._repo_parts(repository)
        data = self._graphql(
            """
            query VeraRepositoryId($owner:String!,$name:String!) {
              repository(owner:$owner,name:$name) { id }
            }
            """,
            {"owner": owner, "name": name},
        )
        repository_data = data.get("repository")
        if not isinstance(repository_data, Mapping):
            raise GitHubAPIError(
                "GitHub GraphQL repository lookup returned no repository"
            )
        repository_id = repository_data.get("id")
        if type(repository_id) is not str or not repository_id:
            raise GitHubAPIError(
                "GitHub GraphQL repository lookup returned invalid id"
            )
        self._repository_ids[repository] = repository_id
        return repository_id

    def compare_and_swap_ref(
        self,
        repository: str,
        ref: str,
        *,
        expected_old_sha: str,
        new_sha: str,
    ) -> str:
        repository_id = self._repository_id(repository)
        full_ref = ref if ref.startswith("refs/") else f"refs/heads/{ref}"
        self._graphql(
            """
            mutation VeraUpdateRefCAS($input:UpdateRefsInput!) {
              updateRefs(input:$input) { clientMutationId }
            }
            """,
            {
                "input": {
                    "repositoryId": repository_id,
                    "refUpdates": [
                        {
                            "name": full_ref,
                            "beforeOid": expected_old_sha,
                            "afterOid": new_sha,
                            "force": False,
                        }
                    ],
                    "clientMutationId": (
                        f"vera-mono:{expected_old_sha}:{new_sha}"
                    ),
                }
            },
        )
        observed = self.get_ref_head(repository, ref)
        if observed != new_sha:
            raise GitHubAPIError(
                "GitHub exact-CAS ref update readback mismatch"
            )
        return observed
