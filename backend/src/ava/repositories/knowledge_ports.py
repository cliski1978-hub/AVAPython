"""Ports for future knowledge ingestion and retrieval services.

There are intentionally no production implementations in this module.
"""

from abc import ABC, abstractmethod
from collections.abc import Sequence

from ava.repositories.knowledge import (
    KnowledgeDocumentRecord,
    KnowledgeQuery,
    KnowledgeRetrievalResult,
    KnowledgeSourceRef,
)


class KnowledgeIngestionPort(ABC):
    """Future source-to-knowledge boundary; it performs no work in Phase 5.78."""

    @abstractmethod
    def ingest(self, source_ref: KnowledgeSourceRef) -> KnowledgeDocumentRecord:
        """Return the knowledge representation for a source when implemented."""
        raise NotImplementedError


class KnowledgeRetrieverPort(ABC):
    """Future scope-aware retrieval boundary, independent of execution runtime."""

    @abstractmethod
    def retrieve(self, query: KnowledgeQuery) -> Sequence[KnowledgeRetrievalResult]:
        """Return provenance-bearing results when retrieval is implemented."""
        raise NotImplementedError
