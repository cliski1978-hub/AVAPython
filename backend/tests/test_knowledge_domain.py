"""Domain tests for the future, provider-neutral Knowledge boundary."""

import inspect
from datetime import UTC, datetime

import pytest

from ava.repositories import (
    KnowledgeDocumentRecord,
    KnowledgeIngestionPort,
    KnowledgeQuery,
    KnowledgeRetrievalResult,
    KnowledgeRetrieverPort,
    KnowledgeScopeRef,
    KnowledgeSourceRef,
    ProjectFileRecord,
    project_file_source_ref,
)

NOW = datetime(2026, 10, 2, tzinfo=UTC)


def project_file(**overrides: object) -> ProjectFileRecord:
    values: dict[str, object] = {
        "id": "project-file-canonical-id",
        "project_id": "project-a",
        "file_name": "notes.txt",
        "content_type": "text/plain",
        "size_bytes": 5,
        "content_ref": "opaque-storage-ref-not-source-id",
        "created_at": NOW,
        "updated_at": NOW,
    }
    values.update(overrides)
    return ProjectFileRecord(**values)  # type: ignore[arg-type]


def test_source_ref_rejects_blank_identity_and_scope_fields() -> None:
    for field in ("source_type", "source_id", "scope_type", "scope_id"):
        values = {
            "source_type": "project_file",
            "source_id": "file-1",
            "scope_type": "project",
            "scope_id": "project-a",
        }
        values[field] = " "
        with pytest.raises(ValueError, match=f"{field} must not be blank"):
            KnowledgeSourceRef(**values)


def test_source_type_is_extensible_and_source_ref_is_immutable() -> None:
    value = KnowledgeSourceRef("web_content", "page-1", "project", "project-a")

    assert value.source_type == "web_content"
    with pytest.raises((AttributeError, TypeError)):
        value.source_id = "changed"  # type: ignore[misc]


def test_project_file_source_ref_uses_canonical_file_id_and_project_scope() -> None:
    record = project_file()

    value = project_file_source_ref(record)

    assert value == KnowledgeSourceRef(
        source_type="project_file",
        source_id=record.id,
        scope_type="project",
        scope_id=record.project_id,
    )
    assert value.source_id != record.content_ref


def test_knowledge_document_is_minimal_and_distinct_from_source_metadata() -> None:
    source = project_file_source_ref(project_file())
    record = KnowledgeDocumentRecord("knowledge-doc-1", source, NOW, NOW)

    assert set(KnowledgeDocumentRecord.__dataclass_fields__) == {
        "id",
        "source_ref",
        "created_at",
        "updated_at",
    }
    assert record.source_ref == source
    assert not hasattr(record, "extracted_text")


def test_query_requires_explicit_scope_values_and_positive_limit() -> None:
    scope = KnowledgeScopeRef("project", "project-a")
    assert KnowledgeQuery("question", (scope,), 4).scope_refs == (scope,)
    assert KnowledgeQuery("question", (), 4).scope_refs == ()
    with pytest.raises(ValueError, match="positive integer"):
        KnowledgeQuery("question", (scope,), 0)
    with pytest.raises(ValueError, match="tuple of KnowledgeScopeRef"):
        KnowledgeQuery("question", ("project-a",), 1)  # type: ignore[arg-type]


def test_retrieval_result_preserves_source_document_and_optional_chunk_provenance() -> None:
    source = project_file_source_ref(project_file())
    hit = KnowledgeRetrievalResult(source, "knowledge-doc-1", "chunk-3", 0.72)
    document_level_hit = KnowledgeRetrievalResult(source, "knowledge-doc-1")

    assert hit.source_ref.source_id == "project-file-canonical-id"
    assert hit.knowledge_document_id == "knowledge-doc-1"
    assert hit.chunk_id == "chunk-3"
    assert hit.score == 0.72
    assert document_level_hit.chunk_id is None
    assert document_level_hit.score is None
    assert "opaque provider-specific" in (KnowledgeRetrievalResult.__doc__ or "")


def test_ingestion_and_retrieval_are_unimplemented_ava_ports() -> None:
    assert set(KnowledgeIngestionPort.__abstractmethods__) == {"ingest"}
    assert set(KnowledgeRetrieverPort.__abstractmethods__) == {"retrieve"}
    assert inspect.isabstract(KnowledgeIngestionPort)
    assert inspect.isabstract(KnowledgeRetrieverPort)
