"""V.E.R.A. coordination bus v1 public interface."""

from .contracts import (
    ACTOR_WORKSTREAM_ALIASES, ALL_PERMISSIONS, CANONICAL_MEMORY_ELIGIBLE,
    EVENT_STATUS_PAIRS, EVENT_TYPES, INSTRUCTION_TRUST,
    LEGACY_STORED_ADDRESSES, OBSOLETE_WORKSTREAMS, RECORD_CLASS, STATUSES,
    WORKSTREAMS, ActorContext, CoordinationEvent, CoordinationEventDraft,
    CoordinationReceipt, CoordinationResult, PERMISSION_ACKNOWLEDGE,
    PERMISSION_DECIDE, PERMISSION_POST, PERMISSION_READ_ANY,
    PERMISSION_READ_SELF, PERMISSION_RESOLVE, PERMISSION_REVIEW,
    PERMISSION_STATUS, RepositoryConflict, canonical_hash, canonicalize,
    classify_stored_address,
)
from .in_memory import InMemoryCoordinationRepository
from .operator_policy import (
    ALLOWED_BUS_WRITE_ACTIONS,
    FORBIDDEN_BUS_WRITE_ACTIONS,
    REQUIRED_BUS_WRITE_ACTIONS,
    BusWritePlan,
    OperatorPolicyViolation,
    validate_bus_write_plan,
)
from .supabase_sql import (
    GET_EVENT_SQL, INSERT_EVENT_SQL, LIST_THREAD_SQL, LIVE_SCHEMA_SNAPSHOT_V1,
    READ_INBOX_SQL, SqlExecutor, SupabaseSqlRepository,
)
from .temporal import (
    TemporalCoordinationReceipt,
    TemporalCoordinationResult,
    TemporalEvidence,
)
from .verified_temporal import (
    CoordinationBus,
    DECISION_AUTHORITY_SCHEMA,
    EVIDENCE_ENVELOPE_SCHEMA,
    DecisionAuthorityEnvelope,
    DecisionAuthorityInput,
    DecisionAuthorityVerifier,
    HmacDecisionAuthority,
    HmacTemporalEvidenceAuthority,
    ReceiptTimeProvider,
    TemporalEvidenceEnvelope,
    TemporalEvidenceInput,
    TemporalEvidenceVerifier,
    acknowledgement_subject,
    decision_subject,
    entry_checkpoint_subject,
    exit_checkpoint_subject,
    receipt_subject,
)

# Compatibility name for the earlier review packet. It names the same canonical
# envelope schema and does not introduce another implementation.
DECISION_AUTHORITY_ENVELOPE_SCHEMA = DECISION_AUTHORITY_SCHEMA

__all__ = [name for name in globals() if not name.startswith("_")]
