import pytest

from vera_core import (
    GitHubAPIError,
    GitHubGitDataAPIClient,
    GitHubHTTPResult,
    GitHubSourceTransportError,
    GitHubTreeUpdate,
)


REPOSITORY = "thebrazenbeard/vera-mono"


class ScriptedHTTP:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def request_json(self, method, url, *, headers, body=None):
        self.calls.append(
            {
                "method": method,
                "url": url,
                "headers": dict(headers),
                "body": body,
            }
        )
        if not self.responses:
            raise AssertionError("unexpected HTTP call")
        return self.responses.pop(0)


def client(http):
    return GitHubGitDataAPIClient(
        token="test-token",
        http=http,
    )


def test_graphql_update_refs_binds_exact_before_oid_and_after_oid():
    http = ScriptedHTTP(
        [
            GitHubHTTPResult(
                200,
                {"data": {"repository": {"id": "repo-node-id"}}},
            ),
            GitHubHTTPResult(
                200,
                {"data": {"updateRefs": {"clientMutationId": "ok"}}},
            ),
            GitHubHTTPResult(
                200,
                {"object": {"sha": "new-head"}},
            ),
        ]
    )
    api = client(http)

    observed = api.compare_and_swap_ref(
        REPOSITORY,
        "main",
        expected_old_sha="old-head",
        new_sha="new-head",
    )
    assert observed == "new-head"

    mutation = http.calls[1]
    assert mutation["url"] == "https://api.github.com/graphql"
    update = mutation["body"]["variables"]["input"]["refUpdates"][0]
    assert update == {
        "name": "refs/heads/main",
        "beforeOid": "old-head",
        "afterOid": "new-head",
        "force": False,
    }
    assert mutation["headers"]["Authorization"] == "Bearer test-token"
    assert http.calls[2]["url"].endswith(
        "/repos/thebrazenbeard/vera-mono/git/ref/heads/main"
    )


def test_graphql_error_fails_closed_without_claiming_ref_success():
    http = ScriptedHTTP(
        [
            GitHubHTTPResult(
                200,
                {"data": {"repository": {"id": "repo-node-id"}}},
            ),
            GitHubHTTPResult(
                200,
                {
                    "errors": [
                        {
                            "message": (
                                "ref no longer points to beforeOid"
                            )
                        }
                    ]
                },
            ),
        ]
    )
    api = client(http)

    with pytest.raises(GitHubAPIError):
        api.compare_and_swap_ref(
            REPOSITORY,
            "main",
            expected_old_sha="old-head",
            new_sha="new-head",
        )
    assert len(http.calls) == 2


def test_recursive_tree_truncation_fails_closed_for_blob_identity():
    http = ScriptedHTTP(
        [
            GitHubHTTPResult(
                200,
                {
                    "sha": "commit-a",
                    "tree": {"sha": "tree-a"},
                },
            ),
            GitHubHTTPResult(
                200,
                {
                    "sha": "tree-a",
                    "truncated": True,
                    "tree": [],
                },
            ),
        ]
    )
    api = client(http)

    with pytest.raises(
        GitHubAPIError,
        match="truncated",
    ):
        api.get_path(
            REPOSITORY,
            "packages/vera_core/example.py",
            "commit-a",
        )


def test_create_tree_preserves_atomic_move_delete_and_add_entries():
    http = ScriptedHTTP(
        [
            GitHubHTTPResult(
                201,
                {"sha": "tree-new"},
            )
        ]
    )
    api = client(http)
    result = api.create_tree(
        REPOSITORY,
        base_tree_sha="tree-old",
        updates=(
            GitHubTreeUpdate(
                path="src/a.py",
                mode="100644",
                object_type="blob",
                sha=None,
            ),
            GitHubTreeUpdate(
                path="dst/a.py",
                mode="100644",
                object_type="blob",
                sha="blob-a",
            ),
        ),
    )
    assert result == "tree-new"
    body = http.calls[0]["body"]
    assert body["base_tree"] == "tree-old"
    assert body["tree"] == [
        {
            "path": "src/a.py",
            "mode": "100644",
            "type": "blob",
            "sha": None,
        },
        {
            "path": "dst/a.py",
            "mode": "100644",
            "type": "blob",
            "sha": "blob-a",
        },
    ]


def test_create_blob_uses_base64_not_text_reinterpretation():
    http = ScriptedHTTP(
        [
            GitHubHTTPResult(
                201,
                {"sha": "blob-binary"},
            )
        ]
    )
    api = client(http)
    result = api.create_blob(
        REPOSITORY,
        b"\x00\xffbinary",
    )
    assert result == "blob-binary"
    body = http.calls[0]["body"]
    assert body["encoding"] == "base64"
    assert body["content"] == "AP9iaW5hcnk="


def test_repository_must_be_exact_owner_name():
    http = ScriptedHTTP([])
    api = client(http)
    with pytest.raises(GitHubSourceTransportError):
        api.get_ref_head("not-an-owner-name", "main")


def test_commit_check_contexts_are_exhaustively_paginated():
    http = ScriptedHTTP(
        [
            GitHubHTTPResult(
                200,
                {
                    "data": {
                        "repository": {
                            "object": {
                                "oid": "commit-a",
                                "statusCheckRollup": {
                                    "contexts": {
                                        "nodes": [
                                            {
                                                "__typename": "CheckRun",
                                                "name": "ci",
                                                "status": "COMPLETED",
                                                "conclusion": "SUCCESS",
                                                "databaseId": 11,
                                                "detailsUrl": "https://example/check/11",
                                            }
                                        ],
                                        "pageInfo": {
                                            "hasNextPage": True,
                                            "endCursor": "cursor-1",
                                        },
                                    }
                                },
                            }
                        }
                    }
                },
            ),
            GitHubHTTPResult(
                200,
                {
                    "data": {
                        "repository": {
                            "object": {
                                "oid": "commit-a",
                                "statusCheckRollup": {
                                    "contexts": {
                                        "nodes": [
                                            {
                                                "__typename": "StatusContext",
                                                "context": "lint",
                                                "state": "SUCCESS",
                                                "targetUrl": "https://example/status/lint",
                                            }
                                        ],
                                        "pageInfo": {
                                            "hasNextPage": False,
                                            "endCursor": None,
                                        },
                                    }
                                },
                            }
                        }
                    }
                },
            ),
        ]
    )
    api = client(http)

    contexts = api.get_commit_check_contexts(
        REPOSITORY,
        "commit-a",
    )

    assert [(item.kind, item.name, item.status) for item in contexts] == [
        ("CHECK_RUN", "ci", "COMPLETED"),
        ("STATUS_CONTEXT", "lint", "SUCCESS"),
    ]
    assert contexts[0].external_id == "check-run:11"
    assert contexts[1].details_ref == "https://example/status/lint"
    assert http.calls[0]["body"]["variables"]["after"] is None
    assert http.calls[1]["body"]["variables"]["after"] == "cursor-1"


def test_commit_check_contexts_fail_closed_on_commit_oid_mismatch():
    http = ScriptedHTTP(
        [
            GitHubHTTPResult(
                200,
                {
                    "data": {
                        "repository": {
                            "object": {
                                "oid": "different-commit",
                                "statusCheckRollup": None,
                            }
                        }
                    }
                },
            )
        ]
    )
    api = client(http)

    with pytest.raises(GitHubAPIError, match="OID mismatch"):
        api.get_commit_check_contexts(
            REPOSITORY,
            "commit-a",
        )
