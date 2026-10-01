from __future__ import annotations

from dataclasses import dataclass, field
import json
from typing import Callable

from vera_identity.loader import load_json_resource

from .registry import CAPABILITIES, validate_registry

from .interaction_semantics import (
    InteractionEnvelope,
    InteractionTarget,
    SpeechAct,
    interpret_utterance,
)


_IDENTITY_RESOURCE = "architecture/identity/VERA_PROJECT_IDENTITY_V1.json"


@dataclass(frozen=True, slots=True)
class ConsoleResponse:
    text: str
    envelope: InteractionEnvelope
    channel: str = "VERA_RESPONSE"
    exit_requested: bool = False


@dataclass(slots=True)
class VeraConsole:
    mode: str
    _context_provider: Callable[[], dict] | None = None
    _history: list[InteractionEnvelope] = field(default_factory=list, init=False)

    @classmethod
    def source_only(cls) -> "VeraConsole":
        return cls(mode="SOURCE_ONLY")

    @classmethod
    def runtime_bound(
        cls,
        context_provider: Callable[[], dict],
    ) -> "VeraConsole":
        if not callable(context_provider):
            raise TypeError("context_provider must be callable")
        return cls(
            mode="QUALIFIED_STATE_BOUND",
            _context_provider=context_provider,
        )

    @property
    def history(self) -> tuple[InteractionEnvelope, ...]:
        return tuple(self._history)

    def _context(self) -> dict | None:
        if self._context_provider is None:
            return None
        value = self._context_provider()
        if type(value) is not dict:
            raise TypeError("runtime context provider must return an exact dict")
        return value

    @staticmethod
    def _identity_text() -> str:
        identity = load_json_resource(_IDENTITY_RESOURCE)
        project = identity.get("project_name") or "Vera Mono"
        configured = identity.get("configured_name") or "Vera"
        statement = identity.get("canonical_statement")
        base = (
            f"I am {configured}, the configured interaction identity of "
            f"{project}."
        )
        if isinstance(statement, str) and statement.strip():
            return base + " " + statement.strip()
        return (
            base
            + " That configured identity is repository state, not proof of "
            "consciousness or uninterrupted runtime continuity."
        )

    @staticmethod
    def _help_text() -> str:
        return (
            "Vera Mono console commands:\n"
            "  :status              source/runtime status\n"
            "  :tasks               task-ledger context when runtime-bound\n"
            "  :context             reconstructed runtime context when bound\n"
            "  :identity            configured Vera identity\n"
            "  :meaning <text>      inspect candidate semantic/pragmatic reading\n"
            "  :help                show this help\n"
            "  :exit                leave the console\n"
            "Natural-language aliases such as 'what is your status?' are "
            "interpreted conservatively. Unrecognized language is preserved "
            "as unresolved rather than guessed."
        )

    def _status_text(self) -> str:
        context = self._context()
        if context is None:
            return (
                "SOURCE_ONLY — the Vera Mono repository interface is available, "
                "but no live runtime state is bound to this console."
            )
        status = context.get("status", "UNKNOWN")
        runtime_id = context.get("accepted_runtime_id")
        pieces = [f"QUALIFIED_STATE_BOUND — status={status}"]
        if runtime_id:
            pieces.append(f"runtime_id={runtime_id}")
        pieces.append(
            "This is runtime-state evidence, not protected-effect authority."
        )
        return "; ".join(pieces)

    def _tasks_text(self) -> str:
        context = self._context()
        if context is None:
            return (
                "No live runtime state is bound, so this source-only console "
                "has no task ledger to inspect."
            )
        return json.dumps(
            context.get("tasks", {"status": "NO_TASK_CONTEXT"}),
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            indent=2,
        )

    @staticmethod
    def _capabilities_text() -> str:
        errors = validate_registry()
        if errors:
            return "Capability registry is invalid: " + "; ".join(errors)
        rows = [
            {
                "capability_id": item.capability_id,
                "package": item.package,
                "role": item.role,
                "status": "SOURCE_DECLARED_NOT_RUNTIME_CONSUMPTION_PROOF",
            }
            for item in CAPABILITIES
        ]
        return json.dumps(
            {
                "schema": "VERA_CONSOLE_CAPABILITY_INVENTORY_V1",
                "capabilities": rows,
            },
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            indent=2,
        )

    def _context_text(self) -> str:
        context = self._context()
        if context is None:
            return (
                "SOURCE_ONLY — no reconstructed QualifiedVeraRuntime context "
                "is available."
            )
        return json.dumps(
            context,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            indent=2,
        )

    def _meaning_text(
        self,
        raw_text: str,
        *,
        previous_interaction_id: str | None,
    ) -> str:
        operand = raw_text.strip()
        if operand.lower().startswith(":meaning"):
            operand = operand[len(":meaning") :].strip()
        if not operand:
            return json.dumps(
                {
                    "channel": "DIAGNOSTIC_INTERPRETATION",
                    "status": "MISSING_OPERAND",
                    "message": "Use :meaning <text>.",
                },
                sort_keys=True,
            )
        nested = interpret_utterance(
            operand,
            previous_interaction_id=previous_interaction_id,
        )
        return json.dumps(
            {
                "channel": "DIAGNOSTIC_INTERPRETATION",
                "interpretation": nested.as_dict(),
                "claim_ceiling": (
                    "CANDIDATE_INTERPRETATION_NOT_TRUTH_NOT_CANON_"
                    "NOT_AUTHORITY_NOT_INTERNAL_THOUGHT"
                ),
            },
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            indent=2,
        )

    def dispatch(self, text: str) -> ConsoleResponse:
        previous = self._history[-1].interaction_id if self._history else None
        envelope = interpret_utterance(
            text,
            previous_interaction_id=previous,
        )
        self._history.append(envelope)

        if envelope.target is InteractionTarget.EXIT:
            return ConsoleResponse(
                "Leaving Vera Mono console.",
                envelope,
                exit_requested=True,
            )
        if envelope.target is InteractionTarget.HELP:
            return ConsoleResponse(self._help_text(), envelope)
        if envelope.target is InteractionTarget.IDENTITY:
            return ConsoleResponse(self._identity_text(), envelope)
        if envelope.target is InteractionTarget.STATUS:
            return ConsoleResponse(self._status_text(), envelope)
        if envelope.target is InteractionTarget.TASKS:
            return ConsoleResponse(self._tasks_text(), envelope)
        if envelope.target is InteractionTarget.CONTEXT:
            return ConsoleResponse(self._context_text(), envelope)
        if envelope.target is InteractionTarget.CAPABILITIES:
            return ConsoleResponse(self._capabilities_text(), envelope)
        if envelope.target is InteractionTarget.MEANING:
            return ConsoleResponse(
                self._meaning_text(
                    text,
                    previous_interaction_id=previous,
                ),
                envelope,
                channel="DIAGNOSTIC_INTERPRETATION",
            )
        if envelope.target is InteractionTarget.AMBIGUOUS:
            targets = ", ".join(
                candidate.target.value
                for candidate in envelope.candidates
            )
            return ConsoleResponse(
                f"AMBIGUOUS — the input maps to multiple console targets: "
                f"{targets}. Nothing was dispatched.",
                envelope,
            )
        if envelope.speech_act is SpeechAct.GREETING:
            return ConsoleResponse(
                "Hey. This is the Vera Mono repository-native console. "
                "Use :help to inspect the current interface.",
                envelope,
            )

        return ConsoleResponse(
            "UNRESOLVED — I preserved the input but this console does not yet "
            f"have qualified semantics for it: {envelope.raw_text}",
            envelope,
        )


def run_console_repl(console: VeraConsole) -> int:
    print("Vera Mono semantic console")
    print(f"mode: {console.mode}")
    print("semantic interpretation: candidate meaning, not authority")
    print("type :help for commands")
    while True:
        try:
            raw = input("vera> ")
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not raw.strip():
            continue
        response = console.dispatch(raw)
        print(response.text)
        if response.exit_requested:
            return 0
