from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol, runtime_checkable

from portfolio_runtime.lantern.canonical import sha256_hex

from .execution_adapters import SourceMutationTransportResult
from .source_mutation import source_provider_id


class GitHubSourceTransportError(RuntimeError):
    pass


class GitHubSourceCASMismatch(GitHubSourceTransportError):
    pass


@dataclass(frozen=True, slots=True)
class GitHubCommitState:
    commit_sha: str
    tree_sha: str


@dataclass(frozen=True, slots=True)
class GitHubPathState:
    blob_sha: str
    mode: str = "100644"
    object_type: str = "blob"


@dataclass(frozen=True, slots=True)
class GitHubTreeUpdate:
    path: str
    mode: str
    object_type: str
    sha: str | None


@runtime_checkable
class GitHubGitDataClient(Protocol):
    """Host-injected GitHub Git Data surface.

    Implementations own credentials/network I/O. update_ref MUST use non-force
    GitHub ref update semantics; the transport constructs the new commit with
    expected_ref_head as its only parent so a concurrently moved branch makes
    that update non-fast-forward and therefore fail closed.
    """

    def get_ref_head(self, repository: str, ref: str) -> str:
        ...

    def get_commit(
        self,
        repository: str,
        commit_sha: str,
    ) -> GitHubCommitState:
        ...

    def get_path(
        self,
        repository: str,
        path: str,
        commit_sha: str,
    ) -> GitHubPathState | None:
        ...

    def create_blob(
        self,
        repository: str,
        content: bytes,
    ) -> str:
        ...

    def create_tree(
        self,
        repository: str,
        *,
        base_tree_sha: str,
        updates: tuple[GitHubTreeUpdate, ...],
    ) -> str:
        ...

    def create_commit(
        self,
        repository: str,
        *,
        message: str,
        tree_sha: str,
        parent_sha: str,
    ) -> str:
        ...

    def update_ref(
        self,
        repository: str,
        ref: str,
        *,
        new_sha: str,
        force: bool,
    ) -> str:
        ...


class GitHubSourceMutationTransport:
    """Concrete GitHub Git-Data transport with exact-head/blob CAS semantics.

    No retry is performed after any provider-side mutation call. If GitHub
    returns an ambiguous network/provider outcome, the exception propagates to
    the qualified effect gateway, which records ATTEMPTED_UNKNOWN.
    """

    REQUEST_SCHEMA = "VERA_MONO_SOURCE_MUTATION_REQUEST_V1"
    OPERATIONS = frozenset({"WRITE_FILE", "DELETE_FILE", "MOVE_FILE"})
    ABSENT = "ABSENT"
    FILE_MODES = frozenset({"100644", "100755"})

    def __init__(
        self,
        *,
        repository: str,
        ref: str,
        client: GitHubGitDataClient,
    ):
        if type(repository) is not str or not repository:
            raise ValueError("repository must be a non-empty exact string")
        if type(ref) is not str or not ref:
            raise ValueError("ref must be a non-empty exact string")
        if not isinstance(client, GitHubGitDataClient):
            raise TypeError("client must satisfy GitHubGitDataClient")
        self.repository = repository
        self.ref = ref
        self.provider_id = source_provider_id(repository)
        self.client = client

    @staticmethod
    def _require_text(value: Any, label: str) -> str:
        if type(value) is not str or not value:
            raise GitHubSourceTransportError(
                f"{label} must be a non-empty exact string"
            )
        return value

    @staticmethod
    def _content_bytes(value: Any) -> bytes:
        if isinstance(value, str):
            return value.encode("utf-8")
        if isinstance(value, bytes):
            return value
        raise GitHubSourceTransportError(
            "WRITE_FILE content must be exact str or bytes"
        )

    @classmethod
    def _require_file_state(
        cls,
        state: GitHubPathState | None,
        expected_blob_id: str,
        *,
        label: str,
    ) -> GitHubPathState | None:
        if expected_blob_id == cls.ABSENT:
            if state is not None:
                raise GitHubSourceCASMismatch(
                    f"{label} expected ABSENT but path exists"
                )
            return None
        if state is None:
            raise GitHubSourceCASMismatch(
                f"{label} expected blob {expected_blob_id!r} but path is absent"
            )
        if state.object_type != "blob":
            raise GitHubSourceCASMismatch(
                f"{label} is not a Git blob"
            )
        if state.mode not in cls.FILE_MODES:
            raise GitHubSourceCASMismatch(
                f"{label} has unsupported file mode {state.mode!r}"
            )
        if state.blob_sha != expected_blob_id:
            raise GitHubSourceCASMismatch(
                f"{label} blob changed before mutation"
            )
        return state

    def _validate_request(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, Mapping):
            raise GitHubSourceTransportError(
                "source mutation request must be a mapping"
            )
        request = dict(payload)
        required = {
            "schema",
            "mutation_id",
            "repository",
            "ref",
            "subject",
            "actor_ref",
            "operation",
            "path",
            "destination_path",
            "expected_ref_head",
            "expected_blob_id",
            "expected_destination_blob_id",
            "content",
            "content_digest",
        }
        if set(request) != required:
            raise GitHubSourceTransportError(
                "source mutation request field set mismatch"
            )
        if request["schema"] != self.REQUEST_SCHEMA:
            raise GitHubSourceTransportError(
                "unsupported source mutation request schema"
            )
        if request["repository"] != self.repository:
            raise GitHubSourceTransportError(
                "source mutation repository does not match transport"
            )
        if request["ref"] != self.ref:
            raise GitHubSourceTransportError(
                "source mutation ref does not match transport"
            )
        operation = self._require_text(
            request["operation"],
            "operation",
        )
        if operation not in self.OPERATIONS:
            raise GitHubSourceTransportError(
                f"unsupported source mutation operation: {operation}"
            )
        for field in (
            "mutation_id",
            "subject",
            "actor_ref",
            "path",
            "expected_ref_head",
            "expected_blob_id",
        ):
            self._require_text(request[field], field)

        if operation == "WRITE_FILE":
            content = self._content_bytes(request["content"])
            expected_digest = self._require_text(
                request["content_digest"],
                "content_digest",
            )
            if sha256_hex(content) != expected_digest:
                raise GitHubSourceTransportError(
                    "WRITE_FILE content digest mismatch"
                )
            if (
                request["destination_path"] is not None
                or request["expected_destination_blob_id"] is not None
            ):
                raise GitHubSourceTransportError(
                    "WRITE_FILE must not carry destination state"
                )
        elif operation == "DELETE_FILE":
            if request["content"] is not None:
                raise GitHubSourceTransportError(
                    "DELETE_FILE must not carry content"
                )
            if request["content_digest"] is not None:
                raise GitHubSourceTransportError(
                    "DELETE_FILE must not carry content_digest"
                )
            if request["expected_blob_id"] == self.ABSENT:
                raise GitHubSourceTransportError(
                    "DELETE_FILE requires existing source blob"
                )
            if (
                request["destination_path"] is not None
                or request["expected_destination_blob_id"] is not None
            ):
                raise GitHubSourceTransportError(
                    "DELETE_FILE must not carry destination state"
                )
        else:
            if request["content"] is not None or request["content_digest"] is not None:
                raise GitHubSourceTransportError(
                    "MOVE_FILE must not carry content"
                )
            destination = self._require_text(
                request["destination_path"],
                "destination_path",
            )
            if destination == request["path"]:
                raise GitHubSourceTransportError(
                    "MOVE_FILE destination must differ from source"
                )
            self._require_text(
                request["expected_destination_blob_id"],
                "expected_destination_blob_id",
            )
            if request["expected_blob_id"] == self.ABSENT:
                raise GitHubSourceTransportError(
                    "MOVE_FILE requires existing source blob"
                )
        return request

    def mutate(
        self,
        request_payload: Mapping[str, Any],
    ) -> SourceMutationTransportResult:
        request = self._validate_request(request_payload)
        expected_head = request["expected_ref_head"]
        observed_head = self.client.get_ref_head(
            self.repository,
            self.ref,
        )
        if observed_head != expected_head:
            raise GitHubSourceCASMismatch(
                "GitHub ref head changed before source mutation"
            )

        commit = self.client.get_commit(
            self.repository,
            expected_head,
        )
        if commit.commit_sha != expected_head:
            raise GitHubSourceTransportError(
                "GitHub commit readback identity mismatch"
            )

        source = self.client.get_path(
            self.repository,
            request["path"],
            expected_head,
        )
        source = self._require_file_state(
            source,
            request["expected_blob_id"],
            label="source path",
        )

        operation = request["operation"]
        updates: list[GitHubTreeUpdate] = []
        expected_after: dict[str, str | None] = {}

        if operation == "WRITE_FILE":
            content = self._content_bytes(request["content"])
            blob_sha = self.client.create_blob(
                self.repository,
                content,
            )
            self._require_text(blob_sha, "created blob sha")
            mode = "100644" if source is None else source.mode
            updates.append(
                GitHubTreeUpdate(
                    path=request["path"],
                    mode=mode,
                    object_type="blob",
                    sha=blob_sha,
                )
            )
            expected_after[request["path"]] = blob_sha
        elif operation == "DELETE_FILE":
            assert source is not None
            updates.append(
                GitHubTreeUpdate(
                    path=request["path"],
                    mode=source.mode,
                    object_type="blob",
                    sha=None,
                )
            )
            expected_after[request["path"]] = None
        else:
            assert source is not None
            destination_path = request["destination_path"]
            destination = self.client.get_path(
                self.repository,
                destination_path,
                expected_head,
            )
            self._require_file_state(
                destination,
                request["expected_destination_blob_id"],
                label="destination path",
            )
            updates.extend(
                (
                    GitHubTreeUpdate(
                        path=request["path"],
                        mode=source.mode,
                        object_type="blob",
                        sha=None,
                    ),
                    GitHubTreeUpdate(
                        path=destination_path,
                        mode=source.mode,
                        object_type="blob",
                        sha=source.blob_sha,
                    ),
                )
            )
            expected_after[request["path"]] = None
            expected_after[destination_path] = source.blob_sha

        tree_sha = self.client.create_tree(
            self.repository,
            base_tree_sha=commit.tree_sha,
            updates=tuple(updates),
        )
        self._require_text(tree_sha, "created tree sha")
        new_commit = self.client.create_commit(
            self.repository,
            message=(
                f"Vera source mutation {request['mutation_id']}: "
                f"{operation} {request['path']}"
            ),
            tree_sha=tree_sha,
            parent_sha=expected_head,
        )
        self._require_text(new_commit, "created commit sha")

        before_update = self.client.get_ref_head(
            self.repository,
            self.ref,
        )
        if before_update != expected_head:
            raise GitHubSourceCASMismatch(
                "GitHub ref head changed while preparing source mutation"
            )

        updated_head = self.client.update_ref(
            self.repository,
            self.ref,
            new_sha=new_commit,
            force=False,
        )
        if updated_head != new_commit:
            raise GitHubSourceTransportError(
                "GitHub ref update returned unexpected head"
            )

        observed_after = self.client.get_ref_head(
            self.repository,
            self.ref,
        )
        if observed_after != new_commit:
            raise GitHubSourceTransportError(
                "GitHub post-write ref readback mismatch"
            )
        for path, expected_blob in expected_after.items():
            state = self.client.get_path(
                self.repository,
                path,
                new_commit,
            )
            if expected_blob is None:
                if state is not None:
                    raise GitHubSourceTransportError(
                        f"GitHub post-write path should be absent: {path}"
                    )
            else:
                if (
                    state is None
                    or state.object_type != "blob"
                    or state.blob_sha != expected_blob
                ):
                    raise GitHubSourceTransportError(
                        f"GitHub post-write blob readback mismatch: {path}"
                    )

        return SourceMutationTransportResult(
            repository=self.repository,
            ref=self.ref,
            operation=operation,
            path=request["path"],
            destination_path=request["destination_path"],
            previous_ref_head=expected_head,
            new_ref_head=new_commit,
            result_id=f"github-commit:{new_commit}",
        )
