"""Phase 5.6 runtime-configuration domain and boundary tests."""

import inspect

import pytest

from ava.runtimes.configurations import RuntimeConfiguration
from ava.services.run_service import RunService


def _configuration(**changes: object) -> RuntimeConfiguration:
    values: dict[str, object] = {
        "runtime_configuration_id": "openhands-local",
        "runtime_type": "openhands",
        "display_name": "OpenHands Local",
        "enabled": True,
    }
    values.update(changes)
    return RuntimeConfiguration(**values)  # type: ignore[arg-type]


def test_configuration_preserves_instance_identity_type_and_display_name() -> None:
    configuration = _configuration()
    assert configuration.runtime_configuration_id == "openhands-local"
    assert configuration.runtime_type == "openhands"
    assert configuration.display_name == "OpenHands Local"
    assert configuration.enabled is True


def test_enabled_defaults_true() -> None:
    configuration = RuntimeConfiguration("native-local", "native", "Native AVA")
    assert configuration.enabled is True


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("runtime_configuration_id", " "),
        ("runtime_type", ""),
        ("display_name", "\t"),
    ],
)
def test_blank_values_are_rejected(field: str, value: str) -> None:
    with pytest.raises(ValueError, match=f"{field} must be a non-blank string"):
        _configuration(**{field: value})


def test_enabled_must_be_boolean() -> None:
    with pytest.raises(ValueError, match="enabled must be a bool"):
        _configuration(enabled=1)


def test_runtime_configuration_and_run_service_remain_independent_from_model_provider_domain() -> None:
    source = inspect.getsource(RuntimeConfiguration)
    for forbidden in ("ModelConfiguration", "ProviderConnection", "provider_connection_id", "model_id", "provider_id"):
        assert forbidden not in source
    assert "RuntimeConfiguration" not in inspect.getsource(RunService)
