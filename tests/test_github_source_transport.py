from __future__ import annotations

from dataclasses import dataclass

import pytest

from vera_assurance import EffectState
from vera_core import (
    GitHubCommitState,
    GitHubPathState,
    GitHubSourceCASMismatch,
    GitHubSourceMutationTransport,
    GitHubTreeUpdate,
    HmacProviderAuthority,
    QualifiedVeraRuntime,
    SourceMutationRequest,
    TaskPacket,
    VeraStateDirectory,
    source_provider_id,
)
from vera_memory import AdmissionRequest, MemoryClass


REPOSITORY = "thebrazenbeard/vera-mono"
REF = "main"
PROJECT = "vera-mono"
IDENTITY = "vera"
HEAD = "head-before"
TREE = "tree-before"


@dataclass
class FakeGitHubGitDataClient:
    initial_paths: dict[str, GitHubPathState]
    race_on_update: bool = False

    def __post_init__(self):
        self.refs = {(REPOSITORY, REF): HEAD}
        self.commits = {
            HEAD: GitHubCommitState(commit_sha=HEAD, tree_sha=TREE)
        }
        self.trees = {TREE: dict(self.initial_paths)}
        self.parents = {}
        self.blob_calls = []
        self.tree_calls = []
        self.commit_calls = []
        self.ref_updates = []

    def get_ref_head(self, repository, ref):
        return self.refs[(repository, ref)]

    def get_commit(self, repository, commit_sha):
        return self.commits[commit_sha]

    def get_path(self, repository, path, commit_sha):
        tree_sha = self.commits[commit_sha].tree_sha
        return self.trees[tree_sha].get(path)

    def create_blob(self, repository, content):
        blob_sha = "blob-new-" + str(len(self.blob_calls) + 1)
        self.blob_calls.append((repository, bytes(content), blob_sha))
        return blob_sha

    def create_tree(self, repository, *, base_tree_sha, updates):
        next_tree = dict(self.trees[base_tree_sha])
        for update in updates:
            if update.sha is None:
                next_tree.pop(update.path, None)
            else:
                next_tree[update.path] = GitHubPathState(
                    blob_sha=update.sha,
                    mode=update.mode,
                    object_type=update.object_type,
                )
        tree_sha = f"tree-new-{len(self.tree_calls) + 1}"
        self.trees[tree_sha] = next_tree
        self.tree_calls.append(
            (repository, base_tree_sha, tuple(updates), tree_sha)
        )
        return tree_sha

    def create_commit(
        self,
        repository,
        *,
        message,
        tree_sha,
        parent_sha,
    ):
        commit_sha = f"commit-new-{len(self.commit_calls) + 1}"
        self.commits[commit_sha] = GitHubCommitState(
            commit_sha=commit_sha,
            tree_sha=tree_sha,
        )
        self.parents[commit_sha] = parent_sha
        self.commit_calls.append(
            (repository, message, tree_sha, parent_sha, commit_sha)
        )
        return commit_sha

    def compare_and_swap_ref(
        self,
        repository,
        ref,
        *,
        expected_old_sha,
        new_sha,
    ):
        if self.race_on_update:
            self.refs[(repository, ref)] = "concurrent-head"
            self.commits["concurrent-head"] = GitHubCommitState(
                commit_sha="concurrent-head",
                tree_sha=TREE,
            )
        current = self.refs[(repository, ref)]
        if current != expected_old_sha:
            raise GitHubSourceCASMismatch(
                "exact beforeOid ref compare-and-swap rejected"
            )
        if self.parents[new_sha] != expected_old_sha:
            raise GitHubSourceCASMismatch(
                "new commit is not parented by expected ref head"
            )
        self.refs[(repository, ref)] = new_sha
        self.ref_updates.append(
            (repository, ref, expected_old_sha, new_sha)
        )
        return new_sha


def transport(client):
    return GitHubSourceMutationTransport(
        repository=REPOSITORY,
        ref=REF,
        client=client,
    )


def write_request(*, expected_blob_id="blob-old"):
    return SourceMutationRequest(
        mutation_id="mutation-write",
        repository=REPOSITORY,
        ref=REF,
        subject="src/a.py",
        actor_ref="vera",
        operation="WRITE_FILE",
        path="src/a.py",
        expected_ref_head=HEAD,
        expected_blob_id=expected_blob_id,
        content="print('new')\n",
    )


def test_github_write_uses_parent_head_and_non_force_ref_update():
    client = FakeGitHubGitDataClient(
        {
            "src/a.py": GitHubPathState(
                blob_sha="blob-old",
                mode="100755",
            )
        }
    )
    result = transport(client).mutate(write_request().request_payload())

    assert result.previous_ref_head == HEAD
    assert result.new_ref_head == "commit-new-1"
    assert client.commit_calls[0][3] == HEAD
    assert client.ref_updates == [
        (REPOSITORY, REF, HEAD, "commit-new-1")
    ]
    written = client.get_path(
        REPOSITORY,
        "src/a.py",
        result.new_ref_head,
    )
    assert written is not None
    assert written.blob_sha == "blob-new-1"
    assert written.mode == "100755"


def test_github_head_movement_fails_before_any_mutating_provider_call():
    client = FakeGitHubGitDataClient({})
    client.refs[(REPOSITORY, REF)] = "other-head"
    client.commits["other-head"] = GitHubCommitState(
        commit_sha="other-head",
        tree_sha=TREE,
    )

    with pytest.raises(GitHubSourceCASMismatch):
        transport(client).mutate(
            write_request(expected_blob_id="ABSENT").request_payload()
        )

    assert client.blob_calls == []
    assert client.tree_calls == []
    assert client.commit_calls == []
    assert client.ref_updates == []


def test_github_move_rejects_destination_collision_before_tree_commit():
    client = FakeGitHubGitDataClient(
        {
            "src/a.py": GitHubPathState(blob_sha="blob-source"),
            "dst/a.py": GitHubPathState(blob_sha="blob-destination"),
        }
    )
    request = SourceMutationRequest(
        mutation_id="mutation-move",
        repository=REPOSITORY,
        ref=REF,
        subject="src/a.py",
        actor_ref="vera",
        operation="MOVE_FILE",
        path="src/a.py",
        destination_path="dst/a.py",
        expected_ref_head=HEAD,
        expected_blob_id="blob-source",
        expected_destination_blob_id="ABSENT",
    )

    with pytest.raises(GitHubSourceCASMismatch):
        transport(client).mutate(request.request_payload())

    assert client.tree_calls == []
    assert client.commit_calls == []
    assert client.ref_updates == []


def test_github_move_is_one_tree_one_commit_one_ref_update():
    client = FakeGitHubGitDataClient(
        {
            "src/a.py": GitHubPathState(
                blob_sha="blob-source",
                mode="100755",
            )
        }
    )
    request = SourceMutationRequest(
        mutation_id="mutation-move",
        repository=REPOSITORY,
        ref=REF,
        subject="src/a.py",
        actor_ref="vera",
        operation="MOVE_FILE",
        path="src/a.py",
        destination_path="dst/a.py",
        expected_ref_head=HEAD,
        expected_blob_id="blob-source",
        expected_destination_blob_id="ABSENT",
    )
    result = transport(client).mutate(request.request_payload())

    assert len(client.tree_calls) == 1
    updates = client.tree_calls[0][2]
    assert updates == (
        GitHubTreeUpdate(
            path="src/a.py",
            mode="100755",
            object_type="blob",
            sha=None,
        ),
        GitHubTreeUpdate(
            path="dst/a.py",
            mode="100755",
            object_type="blob",
            sha="blob-source",
        ),
    )
    assert len(client.commit_calls) == 1
    assert len(client.ref_updates) == 1
    assert client.get_path(REPOSITORY, "src/a.py", result.new_ref_head) is None
    moved = client.get_path(
        REPOSITORY,
        "dst/a.py",
        result.new_ref_head,
    )
    assert moved is not None
    assert moved.blob_sha == "blob-source"
    assert moved.mode == "100755"


def accepted_state(tmp_path):
    state = VeraStateDirectory(
        tmp_path / "state",
        project_id=PROJECT,
        identity_id=IDENTITY,
    )
    lifecycle = state.open()
    admitted = lifecycle.memory.admit(
        AdmissionRequest(
            record_id="m1",
            text="GitHub source transport state",
            memory_class=MemoryClass.WORKING_PROJECT,
            source_actor="test",
            authority_ref="authority:test",
            privacy_ref="privacy:test",
            provenance_refs=("source:test",),
            operation_id="op1",
            project_id=PROJECT,
            governed_identity_id=IDENTITY,
        ),
        expected_head=lifecycle.memory.current_head,
    )
    lifecycle.checkpoint(
        checkpoint_id="cp1",
        runtime_id="runtime-1",
        expected_memory_head=admitted["store_head"],
        expected_checkpoint_head=lifecycle.checkpoints.current_head,
        expected_currentness_generation=None,
    )
    return state


def source_packet():
    return TaskPacket(
        purpose="exercise concrete GitHub source transport",
        subject="github-source-transport",
        completion_state="mutation result verified",
        evidence_requirements=("mutation result",),
        writable_scope=(
            "SOURCE|thebrazenbeard/vera-mono|main|src/**",
        ),
        non_targets=("deployment", "merge"),
        forbidden_shortcuts_or_effects=("force push",),
        priority_order=("scope", "CAS", "write"),
        unknowns=(),
        return_shape=("result",),
        relevant_surfaces=("source",),
    )


def test_github_ref_race_becomes_attempted_unknown_through_qualified_gate(tmp_path):
    state = accepted_state(tmp_path)
    provider_id = source_provider_id(REPOSITORY)
    verifier = HmacProviderAuthority(
        "github-source-authority",
        provider_id,
        b"g" * 32,
        key_id="github-source-v1",
    )
    trust = state.outbound_trust_registry()
    trust.register(
        authority_id=verifier.authority_id,
        role="PROVIDER",
        provider_id=provider_id,
        key_id=verifier.key_id,
        key_digest=verifier.key_digest,
        expected_registry_generation=0,
    )

    client = FakeGitHubGitDataClient(
        {
            "src/a.py": GitHubPathState(blob_sha="blob-old"),
        },
        race_on_update=True,
    )
    github = transport(client)
    runtime = QualifiedVeraRuntime.from_state_directory(
        state,
        provider_authority_verifiers={provider_id: verifier},
        source_mutation_transports={(REPOSITORY, REF): github},
    )
    runtime.start_task("task-github", source_packet())
    adapter = runtime.source_mutation_adapter()
    prepared = adapter.prepare(
        "task-github",
        "dep-github",
        write_request(),
    )
    dispatch = prepared.provider_dispatch
    authority = verifier.issue(
        effect_id=dispatch.effect_id,
        operation=dispatch.operation,
        request_digest=dispatch.request_digest,
        lifecycle_permit_digest=dispatch.permit.permit_digest,
    )

    with pytest.raises(GitHubSourceCASMismatch):
        adapter.execute(prepared, authority=authority)

    receipt = runtime.fence.read(
        f"provider:{provider_id}:mutation-write"
    )
    assert receipt.state is EffectState.ATTEMPTED_UNKNOWN
    assert client.refs[(REPOSITORY, REF)] == "concurrent-head"
    assert client.ref_updates == []


def test_github_move_ref_race_leaves_branch_without_partial_move():
    client = FakeGitHubGitDataClient(
        {
            "src/a.py": GitHubPathState(
                blob_sha="blob-source",
                mode="100644",
            )
        },
        race_on_update=True,
    )
    request = SourceMutationRequest(
        mutation_id="mutation-move-race",
        repository=REPOSITORY,
        ref=REF,
        subject="src/a.py",
        actor_ref="vera",
        operation="MOVE_FILE",
        path="src/a.py",
        destination_path="dst/a.py",
        expected_ref_head=HEAD,
        expected_blob_id="blob-source",
        expected_destination_blob_id="ABSENT",
    )

    with pytest.raises(GitHubSourceCASMismatch):
        transport(client).mutate(request.request_payload())

    assert len(client.tree_calls) == 1
    assert len(client.commit_calls) == 1
    assert client.ref_updates == []
    assert client.refs[(REPOSITORY, REF)] == "concurrent-head"
    assert client.get_path(
        REPOSITORY,
        "src/a.py",
        "concurrent-head",
    ).blob_sha == "blob-source"
    assert client.get_path(
        REPOSITORY,
        "dst/a.py",
        "concurrent-head",
    ) is None
