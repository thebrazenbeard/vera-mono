from dataclasses import dataclass

from vera_core import (
    GitHubCheckContextState,
    GitHubSourceVerificationTransport,
)


REPOSITORY = "thebrazenbeard/vera-mono"
REF = "main"


@dataclass
class FakeGitHubVerificationClient:
    head: str
    contexts: tuple[GitHubCheckContextState, ...]

    def __post_init__(self):
        self.calls = []

    def get_ref_head(self, repository, ref):
        self.calls.append(("head", repository, ref))
        return self.head

    def get_commit_check_contexts(self, repository, commit_sha):
        self.calls.append(("checks", repository, commit_sha))
        return self.contexts


def test_github_source_verification_aggregates_check_runs_and_status_contexts():
    client = FakeGitHubVerificationClient(
        head="commit-a",
        contexts=(
            GitHubCheckContextState(
                name="ci",
                kind="CHECK_RUN",
                status="COMPLETED",
                conclusion="SUCCESS",
                external_id="check-run:1",
                details_ref="https://example/ci/1",
            ),
            GitHubCheckContextState(
                name="lint",
                kind="STATUS_CONTEXT",
                status="SUCCESS",
                conclusion=None,
                external_id=None,
                details_ref="https://example/lint",
            ),
        ),
    )
    transport = GitHubSourceVerificationTransport(
        repository=REPOSITORY,
        ref=REF,
        client=client,
    )

    result = transport.verify(
        "commit-a",
        ("ci", "lint"),
    )

    assert result.observed_ref_head == "commit-a"
    assert [(check.check_name, check.status) for check in result.checks] == [
        ("ci", "PASS"),
        ("lint", "PASS"),
    ]
    assert client.calls == [
        ("checks", REPOSITORY, "commit-a"),
        ("head", REPOSITORY, REF),
    ]


def test_github_source_verification_fails_named_check_if_any_duplicate_fails():
    client = FakeGitHubVerificationClient(
        head="commit-a",
        contexts=(
            GitHubCheckContextState(
                name="matrix",
                kind="CHECK_RUN",
                status="COMPLETED",
                conclusion="SUCCESS",
                external_id="check-run:1",
                details_ref="https://example/matrix/1",
            ),
            GitHubCheckContextState(
                name="matrix",
                kind="CHECK_RUN",
                status="COMPLETED",
                conclusion="FAILURE",
                external_id="check-run:2",
                details_ref="https://example/matrix/2",
            ),
        ),
    )
    result = GitHubSourceVerificationTransport(
        repository=REPOSITORY,
        ref=REF,
        client=client,
    ).verify(
        "commit-a",
        ("matrix",),
    )

    assert result.checks[0].status == "FAIL"
    assert result.checks[0].external_id == (
        "github-contexts:check-run:1,check-run:2"
    )
    assert result.checks[0].details_ref is None


def test_github_source_verification_missing_required_context_is_unavailable():
    client = FakeGitHubVerificationClient(
        head="commit-a",
        contexts=(),
    )
    result = GitHubSourceVerificationTransport(
        repository=REPOSITORY,
        ref=REF,
        client=client,
    ).verify(
        "commit-a",
        ("required-ci",),
    )

    assert result.checks[0].status == "UNAVAILABLE"
    assert result.checks[0].external_id is None


def test_github_source_verification_preserves_moved_ref_for_stale_head_classification():
    client = FakeGitHubVerificationClient(
        head="newer-head",
        contexts=(
            GitHubCheckContextState(
                name="ci",
                kind="CHECK_RUN",
                status="COMPLETED",
                conclusion="SUCCESS",
                external_id="check-run:1",
                details_ref=None,
            ),
        ),
    )
    result = GitHubSourceVerificationTransport(
        repository=REPOSITORY,
        ref=REF,
        client=client,
    ).verify(
        "commit-a",
        ("ci",),
    )

    assert result.commit_sha == "commit-a"
    assert result.observed_ref_head == "newer-head"
    assert result.checks[0].status == "PASS"
