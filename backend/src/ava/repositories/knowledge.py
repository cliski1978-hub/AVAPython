"""Provider-neutral identity and result types for future knowledge retrieval.

These types describe AVA's knowledge boundary only. They do not represent
stored chunks, embeddings, parser output, or an index implementation.
"""

import math
from dataclasses import dataclass
from datetime import datetime

from ava.repositories.project_file import ProjectFileRecord


def _require_nonblank(name: str, value: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must not be blank")


def _require_aware(name: str, value: datetime) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


@dataclass(frozen=True)
class KnowledgeScopeRef:
    """Explicit AVA scope identity used to constrain a future retrieval query."""

    scope_type: str
    scope_id: str

    def __post_init__(self) -> None:
        _require_nonblank("scope_type", self.scope_type)
        _require_nonblank("scope_id", self.scope_id)


@dataclass(frozen=True)
class KnowledgeSourceRef:
    """Stable identity and ownership scope of a source for future ingestion.

    ``source_type`` is an extensible AVA-owned string. ``source_id`` is the
    source resource's canonical identity; it is never a storage path.
    """

    source_type: str
    source_id: str
    scope_type: str
    scope_id: str

    def __post_init__(self) -> None:
        for name, value in (
            ("source_type", self.source_type),
            ("source_id", self.source_id),
            ("scope_type", self.scope_type),
            ("scope_id", self.scope_id),
        ):
            _require_nonblank(name, value)


def project_file_source_ref(record: ProjectFileRecord) -> KnowledgeSourceRef:
    """Represent a Project File using its canonical ID and owning Project."""

    return KnowledgeSourceRef(
        source_type="project_file",
        source_id=record.id,
        scope_type="project",
        scope_id=record.project_id,
    )


@dataclass(frozen=True)
class KnowledgeDocumentRecord:
    """Identity of a future knowledge representation, separate from its source."""

    id: str
    source_ref: KnowledgeSourceRef
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        _require_nonblank("id", self.id)
        if not isinstance(self.source_ref, KnowledgeSourceRef):
            raise ValueError("source_ref must be a KnowledgeSourceRef")
        _require_aware("created_at", self.created_at)
        _require_aware("updated_at", self.updated_at)


@dataclass(frozen=True)
class KnowledgeQuery:
    """Provider-neutral retrieval request with explicit, authorized scopes.

    Callers must derive ``scope_refs`` from current Project membership and
    access checks. An empty scope tuple does not mean global access.
    """

    query_text: str
    scope_refs: tuple[KnowledgeScopeRef, ...]
    limit: int

    def __post_init__(self) -> None:
        _require_nonblank("query_text", self.query_text)
        if not isinstance(self.scope_refs, tuple) or any(
            not isinstance(scope, KnowledgeScopeRef) for scope in self.scope_refs
        ):
            raise ValueError("scope_refs must be a tuple of KnowledgeScopeRef values")
        if not isinstance(self.limit, int) or isinstance(self.limit, bool) or self.limit <= 0:
            raise ValueError("limit must be a positive integer")


@dataclass(frozen=True)
class KnowledgeRetrievalResult:
    """A future retrieval hit with provenance back to its AVA source.

    ``score`` is an opaque provider-specific ranking value. AVA does not
    assign distance, probability, or cross-provider comparison semantics.
    """

    source_ref: KnowledgeSourceRef
    knowledge_document_id: str
    chunk_id: str | None = None
    score: float | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.source_ref, KnowledgeSourceRef):
            raise ValueError("source_ref must be a KnowledgeSourceRef")
        _require_nonblank("knowledge_document_id", self.knowledge_document_id)
        if self.chunk_id is not None:
            _require_nonblank("chunk_id", self.chunk_id)
        if self.score is not None and (
            isinstance(self.score, bool) or not isinstance(self.score, (int, float)) or not math.isfinite(self.score)
        ):
            raise ValueError("score must be a finite numeric value when provided")
