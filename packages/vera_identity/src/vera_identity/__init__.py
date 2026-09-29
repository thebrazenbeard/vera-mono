"""Local Vera identity/bootstrap resource package."""

from .loader import load_json_resource, load_text_resource, resource_path
from .semantic_knowledge import (
    SemanticAdmissionReceipt,
    SemanticKnowledgeConflict,
    SemanticKnowledgeStore,
)

__all__ = [
    "SemanticAdmissionReceipt",
    "SemanticKnowledgeConflict",
    "SemanticKnowledgeStore",
    "load_json_resource",
    "load_text_resource",
    "resource_path",
]
