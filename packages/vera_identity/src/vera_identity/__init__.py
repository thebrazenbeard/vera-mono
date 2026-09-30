"""Local Vera identity/bootstrap resource package."""

from .contextual_interpretation import (
    ContextualAdmissionReceipt,
    ContextualInterpretation,
    ContextualInterpretationConflict,
    ContextualInterpretationError,
    ContextualInterpretationResult,
    ContextualInterpretationStore,
    ContextualSemanticView,
    InterpretationRelation,
    InterpretationRelationKind,
    query_semantic_interpretations,
)
from .loader import load_json_resource, load_text_resource, resource_path
from .semantic_knowledge import (
    SemanticAdmissionReceipt,
    SemanticKnowledgeConflict,
    SemanticKnowledgeStore,
)

__all__ = [
    "ContextualAdmissionReceipt",
    "ContextualInterpretation",
    "ContextualInterpretationConflict",
    "ContextualInterpretationError",
    "ContextualInterpretationResult",
    "ContextualInterpretationStore",
    "ContextualSemanticView",
    "InterpretationRelation",
    "InterpretationRelationKind",
    "SemanticAdmissionReceipt",
    "SemanticKnowledgeConflict",
    "SemanticKnowledgeStore",
    "load_json_resource",
    "load_text_resource",
    "query_semantic_interpretations",
    "resource_path",
]
