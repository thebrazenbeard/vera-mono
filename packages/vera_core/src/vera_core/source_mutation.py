from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, TYPE_CHECKING

from portfolio_runtime.lantern.canonical import canonical_json_bytes, sha256_hex

from .execution_adapters import (
    SourceMutationTransport,
    SourceMutationTransportResult,
)
from .outbound_authority import ProviderAuthorityEnvelope
from .provider_execution_binding import PreparedProviderDispatch
from .task_execution import (
    TaskDelegationRef,
    TaskExecutionError,
)

if TYPE_CHECKING:
    from .qualified_runtime import QualifiedVeraRuntime


SOURCE_MUTATION_OPERATIONS = frozenset(
    {
        "WRITE_FILE",
        "DELETE_FILE",
        "MOVE_FILE",
    }
)


class SourceMutationError(TaskExecutionError):
    pass


def source_provider_id(repository: str) -> str:
    repository = _require_text(repository, "repository")
    return f"source:{repository}"


def _require_text(value: str, label: str) -> str:
    if type(value) is not str or not value.strip():
        raise SourceMutationError(f"{label} must be a non-empty exact string")
    return value


def normalize_source_path(path: str) -> str:
    path = _require_text(path, "source path")
    if "\\" in path:
        raise SourceMutationError("source path must use '/' separators")
    if path.startswith("/"):
        raise SourceMutationError("source path must be repository-relative")
    parts = path.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise SourceMutationError(
            "source path must not contain empty, '.', or '..' segments"
        )
    return "/".join(parts)


@dataclass(frozen=True, slots=True)
class SourceWritableScope:
    repository: str
    ref: str
    pattern: str

    PREFIX = "SOURCE"

    @classmethod
    def parse(cls, value: str) -> "SourceWritableScope":
        value = _require_text(value, "writable scope entry")
        parts = value.split("|")
        if len(parts) != 4 or parts[0] != cls.PREFIX:
            raise SourceMutationError(
                "source writable scope must use "
                "'SOURCE|<repository>|<ref>|<path-or-prefix/**>'"
            )
        repository = _require_text(parts[1], "writable scope repository")
        ref = _require_text(parts[2], "writable scope ref")
        raw_pattern = _require_text(parts[3], "writable scope path pattern")
        if raw_pattern == "**":
            pattern = "**"
        elif raw_pattern.endswith("/**"):
            prefix = normalize_source_path(raw_pattern[:-3])
            pattern = f"{prefix}/**"
        else:
            pattern = normalize_source_path(raw_pattern)
        return cls(repository=repository, ref=ref, pattern=pattern)

    def matches(self, *, repository: str, ref: str, path: str) -> bool:
        path = normalize_source_path(path)
        if repository != self.repository or ref != self.ref:
            return False
        if self.pattern == "**":
            return True
        if self.pattern.endswith("/**"):
            prefix = self.pattern[:-3]
            return path == prefix or path.startswith(prefix + "/")
        return path == self.pattern


@dataclass(frozen=True, slots=True)
class SourceMutationRequest:
    mutation_id: str
    repository: str
    ref: str
    subject: str
    actor_ref: str
    operation: str
    path: str
    expected_ref_head: str
    expected_blob_id: str
    content: str | bytes | None = None
    destination_path: str | None = None
    expected_destination_blob_id: str | None = None

    def validate(self) -> None:
        _require_text(self.mutation_id, "mutation_id")
        _require_text(self.repository, "repository")
        _require_text(self.ref, "ref")
        _require_text(self.subject, "subject")
        _require_text(self.actor_ref, "actor_ref")
        if self.operation not in SOURCE_MUTATION_OPERATIONS:
            raise SourceMutationError(
                f"unsupported source mutation operation: {self.operation!r}"
            )
        normalize_source_path(self.path)
        _require_text(self.expected_ref_head, "expected_ref_head")
        _require_text(self.expected_blob_id, "expected_blob_id")
        if self.operation == "WRITE_FILE":
            if self.content is None or not isinstance(self.content, (str, bytes)):
                raise SourceMutationError(
                    "WRITE_FILE requires exact str or bytes content"
                )
            if self.destination_path is not None:
                raise SourceMutationError(
                    "WRITE_FILE must not carry destination_path"
                )
            if self.expected_destination_blob_id is not None:
                raise SourceMutationError(
                    "WRITE_FILE must not carry destination CAS"
                )
        elif self.operation == "DELETE_FILE":
            if self.content is not None:
                raise SourceMutationError(
                    "DELETE_FILE must not carry content"
                )
            if self.expected_blob_id == "ABSENT":
                raise SourceMutationError(
                    "DELETE_FILE requires an existing expected_blob_id"
                )
            if self.destination_path is not None:
                raise SourceMutationError(
                    "DELETE_FILE must not carry destination_path"
                )
            if self.expected_destination_blob_id is not None:
                raise SourceMutationError(
                    "DELETE_FILE must not carry destination CAS"
                )
        elif self.operation == "MOVE_FILE":
            if self.content is not None:
                raise SourceMutationError(
                    "MOVE_FILE must not carry content"
                )
            if self.expected_blob_id == "ABSENT":
                raise SourceMutationError(
                    "MOVE_FILE requires an existing source blob id"
                )
            if self.destination_path is None:
                raise SourceMutationError(
                    "MOVE_FILE requires destination_path"
                )
            destination = normalize_source_path(self.destination_path)
            if destination == normalize_source_path(self.path):
                raise SourceMutationError(
                    "MOVE_FILE destination must differ from source"
                )
            _require_text(
                self.expected_destination_blob_id,
                "expected_destination_blob_id",
            )

    @property
    def normalized_path(self) -> str:
        return normalize_source_path(self.path)

    @property
    def normalized_destination_path(self) -> str | None:
        return (
            None
            if self.destination_path is None
            else normalize_source_path(self.destination_path)
        )

    @property
    def content_digest(self) -> str | None:
        if self.content is None:
            return None
        raw = (
            self.content.encode("utf-8")
            if isinstance(self.content, str)
            else self.content
        )
        return sha256_hex(raw)

    def request_payload(self) -> dict[str, Any]:
        self.validate()
        return {
            "schema": "VERA_MONO_SOURCE_MUTATION_REQUEST_V1",
            "mutation_id": self.mutation_id,
            "repository": self.repository,
            "ref": self.ref,
            "subject": self.subject,
            "actor_ref": self.actor_ref,
            "operation": self.operation,
            "path": self.normalized_path,
            "destination_path": self.normalized_destination_path,
            "expected_ref_head": self.expected_ref_head,
            "expected_blob_id": self.expected_blob_id,
            "expected_destination_blob_id": self.expected_destination_blob_id,
            "content": self.content,
            "content_digest": self.content_digest,
        }


@dataclass(frozen=True, slots=True)
class PreparedSourceMutation:
    task_id: str
    dependency_id: str
    packet_digest: str
    request: SourceMutationRequest
    writable_scope_entries: tuple[str, ...]
    delegation_ref: TaskDelegationRef | None
    provider_dispatch: PreparedProviderDispatch

    @property
    def authority_subject(self) -> str:
        return self.provider_dispatch.authority_subject


@dataclass(frozen=True, slots=True)
class SourceMutationResult:
    transport_result: SourceMutationTransportResult
    outbound_result: Any


class QualifiedSourceMutationAdapter:
    """Only qualified path for task-scoped repository/file mutation.

    Writable scope and active delegation ownership are checked at preparation
    and rechecked under the task action lock immediately before the host
    transport can mutate source. The actual write still travels through the
    lifecycle/trust/audit/effect-fenced provider gateway.
    """

    def __init__(
        self,
        *,
        runtime: "QualifiedVeraRuntime",
        transports: Mapping[tuple[str, str], SourceMutationTransport],
    ):
        self.runtime = runtime
        registry = dict(transports)
        for scope, transport in registry.items():
            if (
                not isinstance(scope, tuple)
                or len(scope) != 2
                or not all(type(item) is str and item for item in scope)
            ):
                raise TypeError(
                    "source mutation transport keys must be (repository, ref)"
                )
            if not isinstance(transport, SourceMutationTransport):
                raise TypeError(
                    f"source mutation transport for {scope!r} does not satisfy protocol"
                )
            if (transport.repository, transport.ref) != scope:
                raise ValueError(
                    f"source mutation transport identity mismatch for {scope!r}"
                )
            if transport.provider_id != source_provider_id(scope[0]):
                raise ValueError(
                    "source mutation transport provider_id must equal "
                    f"{source_provider_id(scope[0])!r}"
                )
        self.transports = registry

    @staticmethod
    def _matched_scopes(
        writable_scope: tuple[str, ...],
        request: SourceMutationRequest,
    ) -> tuple[str, ...]:
        targets = [request.normalized_path]
        if request.normalized_destination_path is not None:
            targets.append(request.normalized_destination_path)
        parsed: list[tuple[str, SourceWritableScope]] = []
        for raw in writable_scope:
            try:
                scope = SourceWritableScope.parse(raw)
            except SourceMutationError:
                continue
            parsed.append((raw, scope))
        matched: list[str] = []
        for target in targets:
            options = [
                raw
                for raw, scope in parsed
                if scope.matches(
                    repository=request.repository,
                    ref=request.ref,
                    path=target,
                )
            ]
            if not options:
                raise SourceMutationError(
                    f"source path is outside task packet writable_scope: {target}"
                )
            matched.extend(options)
        return tuple(dict.fromkeys(matched))

    def _validate_delegation_policy(
        self,
        *,
        task_id: str,
        request: SourceMutationRequest,
        delegation_ref: TaskDelegationRef | None,
    ) -> TaskDelegationRef | None:
        active_ref = self.runtime.assert_task_subject_mutation_allowed(
            repository=request.repository,
            ref=request.ref,
            subject=request.subject,
            actor_ref=request.actor_ref,
            delegation_ref=delegation_ref,
        )
        if active_ref is None:
            return None
        if active_ref.task_id != task_id:
            raise SourceMutationError(
                "delegation owner reference belongs to a different task"
            )
        state = self.runtime.tasks.read(task_id)
        delegation = state.delegation(active_ref.delegation_id)
        effect_names = {
            "SOURCE_MUTATION",
            f"SOURCE_{request.operation}",
        }
        prohibited = set(delegation.prohibited_effects)
        allowed = set(delegation.allowed_effects)
        if prohibited & effect_names:
            raise SourceMutationError(
                "active delegation explicitly prohibits this source mutation"
            )
        if allowed and not (allowed & effect_names):
            raise SourceMutationError(
                "active delegation does not allow this source mutation effect"
            )
        return active_ref

    def _validate_task_scope(
        self,
        *,
        task_id: str,
        request: SourceMutationRequest,
        delegation_ref: TaskDelegationRef | None,
    ) -> tuple[str, tuple[str, ...], TaskDelegationRef | None]:
        request.validate()
        state = self.runtime.tasks.read(task_id)
        if state.closed:
            raise SourceMutationError(
                "closed task cannot mutate source"
            )
        if "source" not in state.packet.relevant_surfaces:
            raise SourceMutationError(
                "task packet does not declare source as a relevant surface"
            )
        matched = self._matched_scopes(
            state.packet.writable_scope,
            request,
        )
        active_ref = self._validate_delegation_policy(
            task_id=task_id,
            request=request,
            delegation_ref=delegation_ref,
        )
        return state.packet.packet_digest, matched, active_ref

    def prepare(
        self,
        task_id: str,
        dependency_id: str,
        request: SourceMutationRequest,
        *,
        delegation_ref: TaskDelegationRef | None = None,
    ) -> PreparedSourceMutation:
        with self.runtime.tasks.action_lock():
            packet_digest, matched, active_ref = self._validate_task_scope(
                task_id=task_id,
                request=request,
                delegation_ref=delegation_ref,
            )
            provider_id = source_provider_id(request.repository)
            transport = self.transports.get(
                (request.repository, request.ref)
            )
            if transport is None:
                raise SourceMutationError(
                    "no host-injected source mutation transport for repository/ref"
                )
            if transport.provider_id != provider_id:
                raise SourceMutationError(
                    "source mutation transport provider identity drift"
                )
            bound = self.runtime._bind_task_dependency_unlocked(
                task_id,
                dependency_id,
                kind="PROVIDER_EFFECT",
                target_id=request.mutation_id,
            )
            task_dependency = bound.dependency_ref(dependency_id)
            try:
                provider_dispatch = self.runtime.prepare_provider_effect(
                    effect_id=request.mutation_id,
                    provider_id=provider_id,
                    operation=f"SOURCE_{request.operation}",
                    request_payload=request.request_payload(),
                    task_dependency=task_dependency,
                )
            except BaseException:
                if not self.runtime._task_dependency_target_started(
                    kind="PROVIDER_EFFECT",
                    target_id=request.mutation_id,
                ):
                    self.runtime.tasks.cancel_dependency(
                        task_id,
                        dependency_id,
                        reason=(
                            "qualified source mutation preparation failed "
                            "before durable provider/effect evidence"
                        ),
                    )
                raise
            return PreparedSourceMutation(
                task_id=task_id,
                dependency_id=dependency_id,
                packet_digest=packet_digest,
                request=request,
                writable_scope_entries=matched,
                delegation_ref=active_ref,
                provider_dispatch=provider_dispatch,
            )

    def execute(
        self,
        prepared: PreparedSourceMutation,
        *,
        authority: ProviderAuthorityEnvelope,
    ) -> SourceMutationResult:
        if type(prepared) is not PreparedSourceMutation:
            raise TypeError(
                "prepared must be exact PreparedSourceMutation"
            )
        request = prepared.request
        with self.runtime.tasks.action_lock():
            packet_digest, matched, active_ref = self._validate_task_scope(
                task_id=prepared.task_id,
                request=request,
                delegation_ref=prepared.delegation_ref,
            )
            if packet_digest != prepared.packet_digest:
                raise SourceMutationError(
                    "task packet changed after source mutation preparation"
                )
            if matched != prepared.writable_scope_entries:
                raise SourceMutationError(
                    "task writable scope changed after source mutation preparation"
                )
            if active_ref != prepared.delegation_ref:
                raise SourceMutationError(
                    "delegation ownership changed after source mutation preparation"
                )
            transport = self.transports.get(
                (request.repository, request.ref)
            )
            if transport is None:
                raise SourceMutationError(
                    "source mutation transport disappeared before execution"
                )
            if transport.provider_id != prepared.provider_dispatch.provider_id:
                raise SourceMutationError(
                    "source mutation provider identity changed before execution"
                )

            payload = request.request_payload()
            observed_digest = self.runtime.effects.provider_request_digest(
                provider_id=prepared.provider_dispatch.provider_id,
                operation=prepared.provider_dispatch.operation,
                request_payload=payload,
            )
            if observed_digest != prepared.provider_dispatch.request_digest:
                raise SourceMutationError(
                    "source mutation request changed after preparation"
                )

            outbound = self.runtime.dispatch_provider_effect(
                prepared.provider_dispatch,
                authority=authority,
                execute=lambda: transport.mutate(payload),
            )
            result = outbound.value
            if type(result) is not SourceMutationTransportResult:
                raise SourceMutationError(
                    "source mutation transport returned unexpected result type"
                )
            expected = {
                "repository": request.repository,
                "ref": request.ref,
                "operation": request.operation,
                "path": request.normalized_path,
                "destination_path": request.normalized_destination_path,
                "previous_ref_head": request.expected_ref_head,
            }
            for key, value in expected.items():
                if getattr(result, key) != value:
                    raise SourceMutationError(
                        f"source mutation result mismatch at {key}"
                    )
            _require_text(result.new_ref_head, "new_ref_head")
            _require_text(result.result_id, "result_id")
            return SourceMutationResult(
                transport_result=result,
                outbound_result=outbound,
            )
