from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, TYPE_CHECKING

from portfolio_runtime.lantern.canonical import canonical_json_bytes, sha256_hex
from vera_assurance import EffectReceipt, EffectState

from .execution_adapters import (
    SourceMutationTransport,
    SourceMutationTransportResult,
)
from .outbound_authority import ProviderAuthorityEnvelope
from .provider_execution_binding import PreparedProviderDispatch
from .source_mutation_binding import SourceMutationBinding
from .task_execution import (
    TaskDelegationRef,
    TaskExecutionError,
    TaskState,
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


@dataclass(frozen=True, slots=True)
class SourceMutationCancellation:
    mutation_id: str
    mechanical_effect_id: str
    effect_receipt: EffectReceipt
    task_state: TaskState


@dataclass(frozen=True, slots=True)
class SourceMutationRecoveryAssessment:
    mutation_id: str
    task_id: str
    dependency_id: str
    repository: str
    ref: str
    operation: str
    path: str
    destination_path: str | None
    provider_fence_state: str | None
    lifecycle_permit_current: bool
    task_open: bool
    packet_current: bool
    writable_scope_current: bool
    delegation_current: bool
    provider_binding_current: bool
    provider_authority_current: bool
    transport_available: bool
    content_rehydration_required: bool
    dispatch_candidate_allowed: bool
    recovery_required: bool
    terminal: bool
    reason: str


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
            prepared = PreparedSourceMutation(
                task_id=task_id,
                dependency_id=dependency_id,
                packet_digest=packet_digest,
                request=request,
                writable_scope_entries=matched,
                delegation_ref=active_ref,
                provider_dispatch=provider_dispatch,
            )
            provider_binding = self.runtime.provider_execution_bindings.read(
                request.mutation_id
            )
            self.runtime.source_mutation_bindings.bind(
                prepared,
                provider_binding,
            )
            return prepared

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
            provider_binding = self.runtime.provider_execution_bindings.read(
                request.mutation_id
            )
            self.runtime.source_mutation_bindings.bind(
                prepared,
                provider_binding,
            )
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

            expected = {
                "repository": request.repository,
                "ref": request.ref,
                "operation": request.operation,
                "path": request.normalized_path,
                "destination_path": request.normalized_destination_path,
                "previous_ref_head": request.expected_ref_head,
            }

            def execute_transport() -> SourceMutationTransportResult:
                result = transport.mutate(payload)
                if type(result) is not SourceMutationTransportResult:
                    raise SourceMutationError(
                        "source mutation transport returned unexpected result type"
                    )
                for key, value in expected.items():
                    if getattr(result, key) != value:
                        raise SourceMutationError(
                            f"source mutation result mismatch at {key}"
                        )
                _require_text(result.new_ref_head, "new_ref_head")
                _require_text(result.result_id, "result_id")
                return result

            dispatch = prepared.provider_dispatch
            outbound = self.runtime.effects.dispatch_provider_effect(
                permit=dispatch.permit,
                effect_id=dispatch.effect_id,
                provider_id=dispatch.provider_id,
                operation=dispatch.operation,
                request_payload=dispatch.request_payload,
                authority=authority,
                execute=execute_transport,
                task_dependency=dispatch.task_dependency,
            )
            return SourceMutationResult(
                transport_result=outbound.value,
                outbound_result=outbound,
            )

    @staticmethod
    def _binding_delegation_ref(
        binding: SourceMutationBinding,
    ) -> TaskDelegationRef | None:
        raw = binding.delegation_ref
        if raw is None:
            return None
        return TaskDelegationRef(
            task_id=str(raw["task_id"]),
            delegation_id=str(raw["delegation_id"]),
            repository=str(raw["repository"]),
            ref=str(raw["ref"]),
            subject=str(raw["subject"]),
            assignee_ref=str(raw["assignee_ref"]),
            binding_event_digest=str(raw["binding_event_digest"]),
        )

    def assess_binding(
        self,
        binding: SourceMutationBinding,
    ) -> SourceMutationRecoveryAssessment:
        if type(binding) is not SourceMutationBinding:
            raise TypeError(
                "binding must be exact SourceMutationBinding"
            )
        reasons: list[str] = []

        try:
            task = self.runtime.tasks.read(binding.task_id)
            task_open = not task.closed
            packet_current = (
                task.packet.packet_digest == binding.packet_digest
            )
            parsed: list[tuple[str, SourceWritableScope]] = []
            for raw in task.packet.writable_scope:
                try:
                    parsed.append(
                        (raw, SourceWritableScope.parse(raw))
                    )
                except SourceMutationError:
                    continue
            targets = [binding.path]
            if binding.destination_path is not None:
                targets.append(binding.destination_path)
            matched: list[str] = []
            writable_scope_current = True
            for target in targets:
                options = [
                    raw
                    for raw, scope in parsed
                    if scope.matches(
                        repository=binding.repository,
                        ref=binding.ref,
                        path=target,
                    )
                ]
                if not options:
                    writable_scope_current = False
                    break
                matched.extend(options)
            if writable_scope_current:
                writable_scope_current = (
                    tuple(dict.fromkeys(matched))
                    == binding.writable_scope_entries
                )
        except (KeyError, TaskExecutionError):
            task_open = False
            packet_current = False
            writable_scope_current = False

        expected_delegation = self._binding_delegation_ref(binding)
        try:
            observed_delegation = (
                self.runtime.assert_task_subject_mutation_allowed(
                    repository=binding.repository,
                    ref=binding.ref,
                    subject=binding.subject,
                    actor_ref=binding.actor_ref,
                    delegation_ref=expected_delegation,
                )
            )
            delegation_current = (
                observed_delegation == expected_delegation
            )
        except TaskExecutionError:
            delegation_current = False

        provider_binding_current = False
        provider = None
        try:
            provider_binding = (
                self.runtime.provider_execution_bindings.read(
                    binding.provider_effect_id
                )
            )
            provider_binding_current = (
                provider_binding.binding_digest
                == binding.provider_binding_digest
                and provider_binding.request_digest
                == binding.provider_request_digest
                and provider_binding.permit.permit_digest
                == binding.lifecycle_permit_digest
            )
            provider = self.runtime.assess_provider_effect(
                binding.provider_effect_id
            )
        except (KeyError, ValueError):
            provider_binding_current = False
            provider = None

        try:
            self.runtime.effects.provider_authority_currentness(
                binding.provider_id
            )
            provider_authority_current = True
        except (PermissionError, ValueError):
            provider_authority_current = False

        transport = self.transports.get(
            (binding.repository, binding.ref)
        )
        transport_available = (
            transport is not None
            and transport.provider_id == binding.provider_id
        )

        if not task_open:
            reasons.append("owning task is missing or closed")
        if not packet_current:
            reasons.append("task packet digest changed")
        if not writable_scope_current:
            reasons.append("task writable scope no longer matches binding")
        if not delegation_current:
            reasons.append("delegation ownership is no longer current")
        if not provider_binding_current:
            reasons.append("provider execution binding is missing or changed")
        if not provider_authority_current:
            reasons.append("provider authority currentness is stale or unavailable")
        if not transport_available:
            reasons.append("source mutation transport is unavailable")

        lifecycle_current = (
            False
            if provider is None
            else provider.lifecycle_permit_current
        )
        if provider is not None and not lifecycle_current:
            reasons.append("bound lifecycle permit is stale")

        recovery_required = (
            not provider_binding_current
            or (provider is not None and provider.recovery_required)
        )
        terminal = False if provider is None else provider.terminal
        dispatch_candidate_allowed = bool(
            provider is not None
            and provider.dispatch_candidate_allowed
            and task_open
            and packet_current
            and writable_scope_current
            and delegation_current
            and provider_binding_current
            and provider_authority_current
            and transport_available
        )
        if dispatch_candidate_allowed:
            reasons.append(
                "all durable source/task/provider gates remain current"
            )
        elif provider is not None:
            reasons.append(provider.reason)

        return SourceMutationRecoveryAssessment(
            mutation_id=binding.mutation_id,
            task_id=binding.task_id,
            dependency_id=binding.dependency_id,
            repository=binding.repository,
            ref=binding.ref,
            operation=binding.operation,
            path=binding.path,
            destination_path=binding.destination_path,
            provider_fence_state=(
                None if provider is None else provider.fence_state
            ),
            lifecycle_permit_current=lifecycle_current,
            task_open=task_open,
            packet_current=packet_current,
            writable_scope_current=writable_scope_current,
            delegation_current=delegation_current,
            provider_binding_current=provider_binding_current,
            provider_authority_current=provider_authority_current,
            transport_available=transport_available,
            content_rehydration_required=(
                binding.operation == "WRITE_FILE"
            ),
            dispatch_candidate_allowed=dispatch_candidate_allowed,
            recovery_required=recovery_required,
            terminal=terminal,
            reason="; ".join(reasons),
        )

    def cancel_reserved_mutation(
        self,
        mutation_id: str,
        *,
        actor_ref: str,
        delegation_ref: TaskDelegationRef | None = None,
        reason: str,
    ) -> SourceMutationCancellation:
        _require_text(actor_ref, "cancellation actor_ref")
        reason = _require_text(reason, "cancellation reason")
        binding = self.runtime.source_mutation_bindings.read(mutation_id)

        with self.runtime.tasks.action_lock():
            task = self.runtime.tasks.read(binding.task_id)
            if task.closed:
                raise SourceMutationError(
                    "closed task cannot cancel a prepared source mutation"
                )
            if task.packet.packet_digest != binding.packet_digest:
                raise SourceMutationError(
                    "task packet changed after source mutation preparation"
                )
            if "source" not in task.packet.relevant_surfaces:
                raise SourceMutationError(
                    "task no longer declares source as a relevant surface"
                )

            parsed: list[tuple[str, SourceWritableScope]] = []
            for raw in task.packet.writable_scope:
                try:
                    parsed.append(
                        (raw, SourceWritableScope.parse(raw))
                    )
                except SourceMutationError:
                    continue
            targets = [binding.path]
            if binding.destination_path is not None:
                targets.append(binding.destination_path)
            matched: list[str] = []
            for target in targets:
                options = [
                    raw
                    for raw, scope in parsed
                    if scope.matches(
                        repository=binding.repository,
                        ref=binding.ref,
                        path=target,
                    )
                ]
                if not options:
                    raise SourceMutationError(
                        "source cancellation target is outside current task writable scope"
                    )
                matched.extend(options)
            if tuple(dict.fromkeys(matched)) != binding.writable_scope_entries:
                raise SourceMutationError(
                    "task writable scope changed after source mutation preparation"
                )

            self.runtime.assert_task_subject_mutation_allowed(
                repository=binding.repository,
                ref=binding.ref,
                subject=binding.subject,
                actor_ref=actor_ref,
                delegation_ref=delegation_ref,
            )

            active_dependency = next(
                (
                    item
                    for item in task.active_dependencies
                    if item.dependency_id == binding.dependency_id
                ),
                None,
            )
            if (
                active_dependency is None
                or active_dependency.kind != "PROVIDER_EFFECT"
                or active_dependency.target_id != binding.mutation_id
            ):
                raise SourceMutationError(
                    "source mutation no longer owns its active task dependency"
                )

            provider_binding = self.runtime.provider_execution_bindings.read(
                binding.provider_effect_id
            )
            if (
                provider_binding.binding_digest
                != binding.provider_binding_digest
                or provider_binding.task_dependency is None
                or provider_binding.task_dependency.task_id
                != binding.task_id
                or provider_binding.task_dependency.dependency_id
                != binding.dependency_id
            ):
                raise SourceMutationError(
                    "source/provider binding provenance diverged before cancellation"
                )

            mechanical_effect_id = (
                f"provider:{binding.provider_id}:{binding.provider_effect_id}"
            )
            try:
                receipt = self.runtime.fence.read(mechanical_effect_id)
            except KeyError as exc:
                raise SourceMutationError(
                    "source mutation has no reserved mechanical effect to cancel"
                ) from exc
            if receipt.state is not EffectState.RESERVED:
                raise SourceMutationError(
                    "only a RESERVED pre-dispatch source effect may be cancelled"
                )

            cancelled = self.runtime.cancel_reserved_effect(
                mechanical_effect_id
            )
            if cancelled.state is not EffectState.CANCELLED_PRE_DISPATCH:
                raise SourceMutationError(
                    "source effect cancellation did not reach pre-dispatch terminal state"
                )
            updated = self.runtime.tasks.cancel_dependency(
                binding.task_id,
                binding.dependency_id,
                reason=(
                    "SOURCE_MUTATION_CANCELLED_PRE_DISPATCH: "
                    + reason
                    + "; effect="
                    + mechanical_effect_id
                ),
            )
            return SourceMutationCancellation(
                mutation_id=binding.mutation_id,
                mechanical_effect_id=mechanical_effect_id,
                effect_receipt=cancelled,
                task_state=updated,
            )

    def rehydrate_mutation(
        self,
        mutation_id: str,
        *,
        content: str | bytes | None = None,
    ) -> PreparedSourceMutation:
        binding = self.runtime.source_mutation_bindings.read(mutation_id)
        if binding.operation == "WRITE_FILE":
            if not isinstance(content, (str, bytes)):
                raise SourceMutationError(
                    "WRITE_FILE restart requires caller-resupplied exact content"
                )
        elif content is not None:
            raise SourceMutationError(
                "DELETE_FILE/MOVE_FILE restart must not supply content"
            )

        request = SourceMutationRequest(
            mutation_id=binding.mutation_id,
            repository=binding.repository,
            ref=binding.ref,
            subject=binding.subject,
            actor_ref=binding.actor_ref,
            operation=binding.operation,
            path=binding.path,
            destination_path=binding.destination_path,
            expected_ref_head=binding.expected_ref_head,
            expected_blob_id=binding.expected_blob_id,
            expected_destination_blob_id=(
                binding.expected_destination_blob_id
            ),
            content=content,
        )
        request.validate()
        if request.content_digest != binding.content_digest:
            raise SourceMutationError(
                "caller-resupplied source content does not match durable content digest"
            )

        assessment = self.assess_binding(binding)
        if not assessment.dispatch_candidate_allowed:
            raise SourceMutationError(
                "persisted source mutation is not a current dispatch candidate: "
                + assessment.reason
            )

        provider_binding = self.runtime.provider_execution_bindings.read(
            binding.provider_effect_id
        )
        payload = request.request_payload()
        request_digest = self.runtime.effects.provider_request_digest(
            provider_id=provider_binding.provider_id,
            operation=provider_binding.operation,
            request_payload=payload,
        )
        if request_digest != binding.provider_request_digest:
            raise SourceMutationError(
                "rehydrated source request does not match durable provider request digest"
            )
        provider_dispatch = PreparedProviderDispatch(
            permit=provider_binding.permit,
            effect_id=provider_binding.effect_id,
            provider_id=provider_binding.provider_id,
            operation=provider_binding.operation,
            request_payload=payload,
            request_digest=provider_binding.request_digest,
            authority_subject=provider_binding.authority_subject,
            task_dependency=provider_binding.task_dependency,
        )
        prepared = PreparedSourceMutation(
            task_id=binding.task_id,
            dependency_id=binding.dependency_id,
            packet_digest=binding.packet_digest,
            request=request,
            writable_scope_entries=binding.writable_scope_entries,
            delegation_ref=self._binding_delegation_ref(binding),
            provider_dispatch=provider_dispatch,
        )
        self.runtime.source_mutation_bindings.bind(
            prepared,
            provider_binding,
        )
        return prepared

    def recover_mutations(
        self,
    ) -> tuple[SourceMutationRecoveryAssessment, ...]:
        return tuple(
            self.assess_binding(binding)
            for binding in self.runtime.source_mutation_bindings.all()
        )
