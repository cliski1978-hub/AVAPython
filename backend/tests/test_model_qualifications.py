"""Step 41 model-keyed qualification metadata tests."""

import dataclasses

import pytest

from ava.contracts.models import ModelCapabilities, ModelHostingMode, QualificationStatus
from ava.models.model_registry import ModelProfile, ModelRegistry, UnknownModelError
from ava.models.qualifications import ModelQualification, ModelQualificationStore


def _registry() -> ModelRegistry:
    return ModelRegistry(
        (
            ModelProfile("ava/one", "One", "local", "one-native", ModelHostingMode.LOCAL, ModelCapabilities(chat=True)),
            ModelProfile("ava/two", "Two", "local", "two-native", ModelHostingMode.LOCAL, ModelCapabilities(chat=True)),
        )
    )


def test_qualification_record_is_immutable_and_closed_status() -> None:
    record = ModelQualification("ava/one", "tool-call", QualificationStatus.PASS, "tool_calling")
    with pytest.raises(dataclasses.FrozenInstanceError):
        record.status = QualificationStatus.FAIL  # type: ignore[misc]
    with pytest.raises(ValueError, match="QualificationStatus"):
        ModelQualification("ava/one", "bad", "pass", "chat")  # type: ignore[arg-type]


def test_store_rejects_unknown_models_and_duplicate_identity() -> None:
    registry = _registry()
    unknown = ModelQualification("ava/missing", "chat", QualificationStatus.PASS, "chat")
    with pytest.raises(UnknownModelError):
        ModelQualificationStore(registry, (unknown,))

    first = ModelQualification("ava/one", "chat", QualificationStatus.PASS, "chat")
    duplicate = ModelQualification("ava/one", "chat", QualificationStatus.FAIL, "chat")
    with pytest.raises(ValueError, match="duplicate"):
        ModelQualificationStore(registry, (first, duplicate))


def test_store_lookup_and_listing_are_read_only_and_deterministic() -> None:
    registry = _registry()
    native = ModelQualification("ava/one", "z", QualificationStatus.PASS, "tools", "native")
    generic = ModelQualification("ava/one", "a", QualificationStatus.PARTIAL, "chat")
    store = ModelQualificationStore(registry, (native, generic))

    assert store.get("ava/one", "z", "native") == native
    assert store.get("ava/one", "z") is None
    assert [item.qualification_id for item in store.list_for_model("ava/one")] == ["a", "z"]
    assert [item.qualification_id for item in store.list_all()] == ["a", "z"]
