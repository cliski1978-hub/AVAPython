"""Runtime resolution parity with model resolution, using inert test ports."""

from unittest.mock import Mock

import pytest
from test_runtime_registry import RegistryRuntime

from ava.runtimes import RuntimeRegistry, RuntimeResolver, UnknownRuntimeError
from ava.runtimes.contracts import AgentRuntimePort


def test_resolution_preserves_identity_without_invoking_runtime() -> None:
    registry = RuntimeRegistry()
    runtime = Mock(spec=AgentRuntimePort)
    registry.register("test", runtime)
    resolver = RuntimeResolver(registry)
    assert resolver.resolve("test") is runtime
    assert resolver.resolve("test") is runtime
    assert runtime.mock_calls == []


@pytest.mark.parametrize("runtime_id", ["missing", "", "   ", "\t\n", "Native", "native ", "NATIVE"])
def test_missing_blank_and_nonexact_ids_fail_without_defaults(runtime_id: str) -> None:
    registry = RuntimeRegistry()
    native = RegistryRuntime()
    registry.register("native", native)
    resolver = RuntimeResolver(registry)
    with pytest.raises(UnknownRuntimeError) as caught:
        resolver.resolve(runtime_id)
    assert isinstance(caught.value, ValueError)
    assert caught.value.runtime_id == runtime_id
    assert str(caught.value) == f"Unknown runtime: {runtime_id!r}"
    assert registry.get(runtime_id) is None
    assert registry.list() == ["native"]
    assert registry.get("native") is native


def test_multiple_exact_ids_and_injected_registry_remain_independent() -> None:
    registry = RuntimeRegistry()
    resolver = RuntimeResolver(registry)
    ids = ["native", "Native", "native ", "other"]
    runtimes = [RegistryRuntime() for _ in ids]
    for runtime_id, runtime in zip(ids, runtimes, strict=True):
        registry.register(runtime_id, runtime)
    for runtime_id, runtime in zip(ids, runtimes, strict=True):
        assert resolver.resolve(runtime_id) is runtime
    assert registry.list() == ids
    with pytest.raises(UnknownRuntimeError):
        RuntimeResolver(RuntimeRegistry()).resolve("native")
