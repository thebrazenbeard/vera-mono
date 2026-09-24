from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from .source_verification import (
    SourceCheckObservation,
    SourceVerificationError,
    SourceVerificationTransportResult,
)


@dataclass(frozen=True, slots=True)
class GitHubCheckContextState:
    name: str
    kind: str
    status: str
    conclusion: str | None
    external_id: str | None
    details_ref: str | None

    def validate(self) -> None:
        if type(self.name) is not str or not self.name:
            raise SourceVerificationError(
                "GitHub check context name must be non-empty"
            )
        if self.kind not in {"CHECK_RUN", "STATUS_CONTEXT"}:
            raise SourceVerificationError(
                f"unsupported GitHub check context kind: {self.kind!r}"
            )
        if type(self.status) is not str or not self.status:
            raise SourceVerificationError(
                "GitHub check context status must be non-empty"
            )
        if self.conclusion is not None and (
            type(self.conclusion) is not str or not self.conclusion
        ):
            raise SourceVerificationError(
                "GitHub check conclusion must be None or non-empty string"
            )


@runtime_checkable
class GitHubSourceVerificationClient(Protocol):
    def get_ref_head(self, repository: str, ref: str) -> str:
        ...

    def get_commit_check_contexts(
        self,
        repository: str,
        commit_sha: str,
    ) -> tuple[GitHubCheckContextState, ...]:
        ...


class GitHubSourceVerificationTransport:
    """Exact-commit GitHub check/status verification with exhaustive pagination."""

    def __init__(
        self,
        *,
        repository: str,
        ref: str,
        client: GitHubSourceVerificationClient,
    ):
        if type(repository) is not str or not repository:
            raise ValueError("repository must be a non-empty exact string")
        if type(ref) is not str or not ref:
            raise ValueError("ref must be a non-empty exact string")
        if not isinstance(client, GitHubSourceVerificationClient):
            raise TypeError(
                "client must satisfy GitHubSourceVerificationClient"
            )
        self.repository = repository
        self.ref = ref
        self.client = client

    @classmethod
    def from_token(
        cls,
        *,
        repository: str,
        ref: str,
        token: str,
        http: Any | None = None,
        api_base: str = "https://api.github.com",
        graphql_url: str = "https://api.github.com/graphql",
        api_version: str = "2026-03-10",
    ) -> "GitHubSourceVerificationTransport":
        from .github_api_client import GitHubGitDataAPIClient

        return cls(
            repository=repository,
            ref=ref,
            client=GitHubGitDataAPIClient(
                token=token,
                http=http,
                api_base=api_base,
                graphql_url=graphql_url,
                api_version=api_version,
            ),
        )

    @staticmethod
    def _context_status(
        context: GitHubCheckContextState,
    ) -> str:
        context.validate()
        status = context.status.upper()
        conclusion = (
            None
            if context.conclusion is None
            else context.conclusion.upper()
        )
        if context.kind == "STATUS_CONTEXT":
            if status == "SUCCESS":
                return "PASS"
            if status in {"PENDING", "EXPECTED"}:
                return "PENDING"
            if status in {"FAILURE", "ERROR"}:
                return "FAIL"
            return "UNAVAILABLE"

        if status != "COMPLETED":
            return "PENDING"
        if conclusion == "SUCCESS":
            return "PASS"
        if conclusion is None:
            return "UNAVAILABLE"
        return "FAIL"

    @classmethod
    def _aggregate_named_contexts(
        cls,
        check_name: str,
        contexts: tuple[GitHubCheckContextState, ...],
    ) -> SourceCheckObservation:
        matches = tuple(
            item for item in contexts if item.name == check_name
        )
        if not matches:
            return SourceCheckObservation(
                check_name=check_name,
                status="UNAVAILABLE",
                external_id=None,
                details_ref=None,
            )

        statuses = {cls._context_status(item) for item in matches}
        if "FAIL" in statuses:
            status = "FAIL"
        elif "UNAVAILABLE" in statuses:
            status = "UNAVAILABLE"
        elif "PENDING" in statuses:
            status = "PENDING"
        else:
            status = "PASS"

        external_ids = tuple(
            item.external_id
            for item in matches
            if item.external_id is not None
        )
        details = tuple(
            item.details_ref
            for item in matches
            if item.details_ref is not None
        )
        return SourceCheckObservation(
            check_name=check_name,
            status=status,
            external_id=(
                external_ids[0]
                if len(external_ids) == 1
                else (
                    None
                    if not external_ids
                    else "github-contexts:" + ",".join(external_ids)
                )
            ),
            details_ref=details[0] if len(set(details)) == 1 else None,
        )

    def verify(
        self,
        commit_sha: str,
        required_checks: tuple[str, ...],
    ) -> SourceVerificationTransportResult:
        if type(commit_sha) is not str or not commit_sha:
            raise SourceVerificationError(
                "commit_sha must be a non-empty exact string"
            )
        if (
            not required_checks
            or not all(
                type(item) is str and item
                for item in required_checks
            )
            or len(set(required_checks)) != len(required_checks)
        ):
            raise SourceVerificationError(
                "required_checks must be unique non-empty exact strings"
            )

        # Read the branch head separately from exact-commit checks. The
        # SourceVerificationStore will classify a moved ref as STALE_HEAD.
        observed_ref_head = self.client.get_ref_head(
            self.repository,
            self.ref,
        )
        contexts = self.client.get_commit_check_contexts(
            self.repository,
            commit_sha,
        )
        for context in contexts:
            if type(context) is not GitHubCheckContextState:
                raise SourceVerificationError(
                    "GitHub verification client returned invalid context type"
                )
            context.validate()

        return SourceVerificationTransportResult(
            repository=self.repository,
            ref=self.ref,
            commit_sha=commit_sha,
            observed_ref_head=observed_ref_head,
            checks=tuple(
                self._aggregate_named_contexts(name, contexts)
                for name in required_checks
            ),
        )
