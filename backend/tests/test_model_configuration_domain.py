"""Phase 5.4 model-configuration domain tests."""

import inspect

import pytest

from ava.contracts.models import ModelCapabilities, ModelHostingMode
from ava.models.model_configurations import ModelConfiguration
from ava.services.run_service import RunService


def _configuration(**changes: object) -> ModelConfiguration:
    values: dict[str, object] = {
        "model_id": "ava.qwen.coder.primary",
        "provider_connection_id": "company-vllm",
        "provider_model_name": "qwen2.5-coder:7b",
        "display_name": "Qwen Coder 7B",
        "hosting_mode": ModelHostingMode.COMPANY_HOSTED,
        "capabilities": ModelCapabilities(chat=True, streaming=True, code_specialization=True),
        "enabled": True,
    }
    values.update(changes)
    return ModelConfiguration(**values)  # type: ignore[arg-type]


def test_configuration_preserves_distinct_identities_and_declared_metadata() -> None:
    configuration = _configuration()
    assert configuration.model_id == "ava.qwen.coder.primary"
    assert configuration.provider_connection_id == "company-vllm"
    assert configuration.provider_model_name == "qwen2.5-coder:7b"
    assert configuration.display_name == "Qwen Coder 7B"
    assert configuration.hosting_mode is ModelHostingMode.COMPANY_HOSTED
    assert configuration.capabilities.code_specialization is True
    assert configuration.enabled is True


def test_enabled_defaults_true_and_capabilities_use_existing_vocabulary() -> None:
    configuration = ModelConfiguration(
        model_id="ava.local",
        provider_connection_id="local-connection",
        provider_model_name="local-model",
        display_name="Local model",
        hosting_mode=ModelHostingMode.LOCAL,
    )
    assert configuration.enabled is True
    assert configuration.capabilities == ModelCapabilities()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("model_id", " "),
        ("provider_connection_id", ""),
        ("provider_model_name", "\t"),
        ("display_name", "\n"),
    ],
)
def test_blank_identity_and_display_values_are_rejected(field: str, value: str) -> None:
    with pytest.raises(ValueError, match=f"{field} must be a non-blank string"):
        _configuration(**{field: value})


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("hosting_mode", "local", "hosting_mode must be a ModelHostingMode"),
        ("capabilities", {"chat": True}, "capabilities must be a ModelCapabilities"),
        ("enabled", 1, "enabled must be a bool"),
    ],
)
def test_canonical_type_validation_is_enforced(field: str, value: object, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        _configuration(**{field: value})


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("provider_connection_id", "ava.qwen.coder.primary", "model_id must be distinct"),
        ("provider_model_name", "ava.qwen.coder.primary", "model_id must be distinct"),
        ("provider_model_name", "company-vllm", "provider_connection_id must be distinct"),
    ],
)
def test_model_provider_connection_and_provider_model_identities_stay_distinct(
    field: str, value: str, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        _configuration(**{field: value})


def test_run_service_does_not_depend_on_model_configuration() -> None:
    assert "ModelConfiguration" not in inspect.getsource(RunService)
