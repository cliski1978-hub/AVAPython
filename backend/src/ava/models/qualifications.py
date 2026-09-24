"""Immutable read-only model qualification metadata.

This production catalog is separate from runtime qualification harnesses. It
stores curated summaries only and never invokes a provider, runtime, or tool.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

from ava.contracts.models import QualificationStatus
from ava.models.model_registry import ModelRegistry, UnknownModelError


def _require_identifier(value: str, *, field: str) -> None:
    if not value or not value.strip():
        raise ValueError(f"{field} must be non-empty")


@dataclass(frozen=True)
class ModelQualification:
    """One measured qualification summary for a configured model identity."""

    model_id: str
    qualification_id: str
    status: QualificationStatus
    task_class: str
    runtime_id: str | None = None
    evidence_summary: str | None = None
    measured_at: datetime | None = None

    def __post_init__(self) -> None:
        _require_identifier(self.model_id, field="model_id")
        _require_identifier(self.qualification_id, field="qualification_id")
        _require_identifier(self.task_class, field="task_class")
        if self.runtime_id is not None:
            _require_identifier(self.runtime_id, field="runtime_id")
        if not isinstance(self.status, QualificationStatus):
            raise ValueError("status must be a QualificationStatus")


class ModelQualificationStore:
    """Read-only in-memory lookup validated against the model registry."""

    def __init__(self, registry: ModelRegistry, qualifications: Iterable[ModelQualification] = ()) -> None:
        by_key: dict[tuple[str, str | None, str], ModelQualification] = {}
        for qualification in qualifications:
            if registry.get(qualification.model_id) is None:
                raise UnknownModelError(qualification.model_id)
            key = (qualification.model_id, qualification.runtime_id, qualification.qualification_id)
            if key in by_key:
                raise ValueError(f"duplicate model qualification: {key!r}")
            by_key[key] = qualification
        self._by_key = by_key

    def list_all(self) -> tuple[ModelQualification, ...]:
        """Return all records in deterministic public-summary order."""
        return tuple(sorted(self._by_key.values(), key=_sort_key))

    def list_for_model(self, model_id: str) -> tuple[ModelQualification, ...]:
        """Return the records associated with ``model_id``."""
        return tuple(item for item in self.list_all() if item.model_id == model_id)

    def get(self, model_id: str, qualification_id: str, runtime_id: str | None = None) -> ModelQualification | None:
        """Look up one record by model/runtime/qualification identity."""
        return self._by_key.get((model_id, runtime_id, qualification_id))


def _sort_key(item: ModelQualification) -> tuple[str, str, str, str]:
    return (item.model_id, item.task_class, item.runtime_id or "", item.qualification_id)
