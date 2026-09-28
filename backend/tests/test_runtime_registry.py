"""Pure runtime instance storage; no model, execution, or metadata calls."""

import pytest

from ava.contracts.conversations import RunContext
from ava.contracts.requests import RunRequest
from ava.contracts.runtimes import RuntimeInfo
from ava.models.contracts import ModelProviderPort
from ava.runtimes import RuntimeRegistry
from ava.runtimes.contracts import AgentRuntimePort, RuntimeRunResult


class RegistryRuntime(AgentRuntimePort):
    """No provider state; fail if registration attempts to invoke the runtime."""

    def get_runtime_info(self) -> RuntimeInfo:
        raise AssertionError("Registry must not inspect metadata")

    async def execute(
        self, *, run_id: str, request: RunRequest, model_provider: ModelProviderPort,
        context: RunContext | None = None,
    ) -> RuntimeRunResult:
        raise AssertionError("Registry must not execute")

    async def cancel_run(self, run_id: str) -> RuntimeRunResult:
        raise AssertionError("Registry must not cancel")


def test_empty_registry() -> None:
    registry = RuntimeRegistry()
    assert registry.list() == []
    assert registry.get("native") is None
    assert not registry.contains("native")


def test_registration_preserves_instance_without_inspection() -> None:
    runtime = RegistryRuntime()
    registry = RuntimeRegistry()
    registry.register("opaque alias", runtime)
    assert registry.get("opaque alias") is runtime
    assert registry.contains("opaque alias")
    assert registry.list() == ["opaque alias"]


@pytest.mark.parametrize("blank", ["", "   ", "\t\n"])
def test_blank_registration_rejected_without_mutation(blank: str) -> None:
    registry = RuntimeRegistry()
    with pytest.raises(ValueError, match="non-blank"):
        registry.register(blank, RegistryRuntime())
    assert registry.list() == []


@pytest.mark.parametrize("same_instance", [False, True])
def test_duplicate_preserves_original(same_instance: bool) -> None:
    registry = RuntimeRegistry()
    first = RegistryRuntime()
    registry.register("runtime", first)
    with pytest.raises(ValueError, match="already registered"):
        registry.register("runtime", first if same_instance else RegistryRuntime())
    assert registry.get("runtime") is first
    assert registry.list() == ["runtime"]


def test_order_exact_keys_and_list_snapshot() -> None:
    registry = RuntimeRegistry()
    ids = ["z-last", " a spaced id ", "A", "a"]
    runtimes = [RegistryRuntime() for _ in ids]
    for key, runtime in zip(ids, runtimes, strict=True):
        registry.register(key, runtime)
    assert registry.list() == ids
    for key, runtime in zip(ids, runtimes, strict=True):
        assert registry.get(key) is runtime
        assert registry.contains(key)
    assert registry.get("a spaced id") is None
    assert not registry.contains("a spaced id")
    snapshot = registry.list()
    snapshot.clear()
    assert registry.list() == ids
    assert RuntimeRegistry().list() == []


@pytest.mark.parametrize("missing", ["missing", "", "   "])
def test_unknown_lookup_does_not_resolve_or_mutate(missing: str) -> None:
    registry = RuntimeRegistry()
    registry.register("known", RegistryRuntime())
    assert registry.get(missing) is None
    assert not registry.contains(missing)
    assert registry.list() == ["known"]
