"""Deterministic native runtime execution, ownership, and cancellation tests."""

import asyncio

import pytest
from test_model_provider_port import FakeModelProvider
from test_native_agent import TestProvider

from ava.contracts.models import ModelRequest, ModelResponse
from ava.contracts.requests import RunRequest
from ava.contracts.responses import RunStatus
from ava.contracts.runtimes import RuntimeCapabilities
from ava.models.errors import ModelProviderError
from ava.runtimes.adapters.native.native_runtime import NativeRuntime
from ava.runtimes.contracts import AgentRuntimePort, RuntimeRunResult


@pytest.mark.parametrize("error", [None, ModelProviderError("secret URL"), RuntimeError("secret internal text")])
def test_execution_translation_and_cleanup(error: Exception | None, caplog: pytest.LogCaptureFixture) -> None:
    async def scenario() -> None:
        runtime = NativeRuntime()
        provider = TestProvider(error)
        result = await runtime.execute(run_id="run", request=RunRequest(prompt=" Hello\n "), model_provider=provider)
        assert isinstance(runtime, AgentRuntimePort)
        assert isinstance(result, RuntimeRunResult)
        assert result.status == (RunStatus.FAILED if error else RunStatus.COMPLETED)
        assert result.content == ("Model provider request failed" if error else "Native answer")
        assert provider.requests == [ModelRequest(messages=[{"role": "user", "content": " Hello\n "}])]
        assert runtime._run_tasks == {}
        assert (await runtime.cancel_run("run")).status == result.status
        if isinstance(error, RuntimeError):
            assert "Unexpected model provider failure" in caplog.text

    asyncio.run(scenario())


def test_metadata_is_conservative_and_provider_independent() -> None:
    runtime = NativeRuntime()
    info = runtime.get_runtime_info()
    assert info.runtime_id == "native"
    assert info.display_name == "AVA Native Runtime"
    assert info.capabilities == RuntimeCapabilities()
    info.capabilities.tools = True
    assert runtime.get_runtime_info().capabilities.tools is False


def test_one_runtime_uses_two_different_provider_implementations() -> None:
    async def scenario() -> None:
        runtime = NativeRuntime()
        request = RunRequest(prompt="Hello")
        first = TestProvider()
        second = FakeModelProvider(model_id="other-model")
        one = await runtime.execute(run_id="one", request=request, model_provider=first)
        two = await runtime.execute(run_id="two", request=request, model_provider=second)
        assert one.content == "Native answer"
        assert two.content == "reply to Hello"
        assert len(first.requests) == 1
        assert runtime._run_tasks == {}
        assert not hasattr(runtime, "_model_provider")

    asyncio.run(scenario())


@pytest.mark.parametrize("external", [False, True])
def test_cancellation_and_reuse(external: bool) -> None:
    async def scenario() -> None:
        runtime = NativeRuntime()
        provider = TestProvider(block=True)
        task = asyncio.create_task(runtime.execute(
            run_id="run", request=RunRequest(prompt="Cancel"), model_provider=provider,
        ))
        await asyncio.wait_for(provider.started.wait(), 1)
        if external:
            task.cancel()
        else:
            assert (await runtime.cancel_run("run")).status == RunStatus.CANCELLED
            assert (await runtime.cancel_run("run")).status == RunStatus.CANCELLED
        assert (await asyncio.wait_for(task, 1)).status == RunStatus.CANCELLED
        assert provider.cancelled
        assert runtime._run_tasks == {}
        assert (await runtime.cancel_run("run")).status == RunStatus.CANCELLED
        for _ in range(2):
            assert (await runtime.cancel_run("unknown")).status == RunStatus.RUNNING
        result = await runtime.execute(run_id="run", request=RunRequest(prompt="Again"), model_provider=TestProvider())
        assert result.status == RunStatus.COMPLETED
        assert (await runtime.cancel_run("run")).status == RunStatus.COMPLETED

    asyncio.run(scenario())


def test_duplicate_active_id_does_not_overwrite_or_cancel_original() -> None:
    async def scenario() -> None:
        runtime = NativeRuntime()
        provider = TestProvider(block=True)
        task = asyncio.create_task(runtime.execute(
            run_id="run", request=RunRequest(prompt="First"), model_provider=provider,
        ))
        await asyncio.wait_for(provider.started.wait(), 1)
        original = runtime._run_tasks["run"]
        duplicate_provider = TestProvider()
        duplicate = await runtime.execute(
            run_id="run", request=RunRequest(prompt="Duplicate"), model_provider=duplicate_provider,
        )
        assert duplicate == RuntimeRunResult(status=RunStatus.FAILED, content="Run is already active")
        assert runtime._run_tasks["run"] is original
        assert not original.done()
        assert duplicate_provider.requests == []
        await runtime.cancel_run("run")
        assert (await asyncio.wait_for(task, 1)).status == RunStatus.CANCELLED
        assert runtime._run_tasks == {}

    asyncio.run(scenario())


def test_concurrent_runs_and_runtime_instances_are_isolated() -> None:
    async def scenario() -> None:
        runtime = NativeRuntime()
        other = NativeRuntime()
        first, second = TestProvider(block=True), TestProvider(block=True)
        tasks = [asyncio.create_task(runtime.execute(
            run_id=run_id, request=RunRequest(prompt="Wait"), model_provider=provider,
        )) for run_id, provider in (("one", first), ("two", second))]
        await asyncio.wait_for(asyncio.gather(first.started.wait(), second.started.wait()), 1)
        assert set(runtime._run_tasks) == {"one", "two"}
        assert other._run_tasks == {}
        await other.cancel_run("one")
        assert not tasks[0].done()
        await runtime.cancel_run("one")
        assert (await asyncio.wait_for(tasks[0], 1)).status == RunStatus.CANCELLED
        assert not tasks[1].done()
        assert set(runtime._run_tasks) == {"two"}
        await runtime.cancel_run("two")
        assert (await asyncio.wait_for(tasks[1], 1)).status == RunStatus.CANCELLED
        assert runtime._run_tasks == {}

    asyncio.run(scenario())


@pytest.mark.parametrize("fail", [False, True])
def test_cancellation_wins_over_provider_cleanup_outcome(fail: bool) -> None:
    class SuppressingProvider(TestProvider):
        async def generate(self, request: ModelRequest, *, model_name: str | None = None) -> ModelResponse:
            try:
                return await super().generate(request, model_name=model_name)
            except asyncio.CancelledError:
                if fail:
                    raise ModelProviderError("secret cleanup error") from None
                return ModelResponse(content="Late answer", model_id="test")

    async def scenario() -> None:
        runtime = NativeRuntime()
        provider = SuppressingProvider(block=True)
        task = asyncio.create_task(runtime.execute(
            run_id="run", request=RunRequest(prompt="Cancel"), model_provider=provider,
        ))
        await asyncio.wait_for(provider.started.wait(), 1)
        await runtime.cancel_run("run")
        assert await asyncio.wait_for(task, 1) == RuntimeRunResult(status=RunStatus.CANCELLED)
        assert runtime._run_tasks == {}
        assert (await runtime.cancel_run("run")).status == RunStatus.CANCELLED

    asyncio.run(scenario())
