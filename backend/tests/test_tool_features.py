import asyncio
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from ava.api.app import create_app
from ava.configuration.settings import Settings
from ava.contracts.tool_features import ToolFeatureConfiguration, UpdateToolFeaturesRequest
from ava.contracts.tools import ToolDefinition, ToolExecutionCategory, ToolRisk
from ava.infrastructure.persistence.database import SqliteDatabase
from ava.infrastructure.persistence.repositories.tool_feature_repository import RelationalToolFeatureRepository
from ava.repositories.tool_feature_repository import ToolFeatureConflictError, ToolFeatureRepository
from ava.services.tool_feature_service import (
    ToolFeatureAdministrationRequiredError,
    ToolFeatureService,
    ToolFeatureUnavailableError,
)
from ava.services.tool_feature_store import ToolFeatureStore
from ava.tools import ToolRegistry


class TestAdministration:
    __test__ = False

    def can_manage(self) -> bool:
        return True


def registry() -> ToolRegistry:
    result = ToolRegistry()
    result.register(
        ToolDefinition(
            tool_id="test.read",
            name="Fixture",
            description="No handler",
            tool_version="1",
            input_schema={"type": "object"},
            output_schema={"type": "object"},
            risk=ToolRisk.LOW,
            execution_category=ToolExecutionCategory.DETERMINISTIC,
        )
    )
    return result


def update(version: int, framework: bool = True, ids: tuple[str, ...] = ("test.read",)) -> UpdateToolFeaturesRequest:
    return UpdateToolFeaturesRequest(framework_enabled=framework, enabled_tool_ids=ids, expected_version=version)


@pytest.fixture(params=["memory", "sqlite"])
def repository(request: pytest.FixtureRequest, tmp_path: Path):  # type: ignore[no-untyped-def]
    if request.param == "memory":
        yield ToolFeatureStore()
    else:
        database = SqliteDatabase(str(tmp_path / "features.sqlite3"))
        yield RelationalToolFeatureRepository(database)
        database.dispose()


def test_defaults_updates_master_and_individual_gates(repository: ToolFeatureRepository) -> None:
    service = ToolFeatureService(registry(), repository, TestAdministration())
    state = service.state()
    assert state.configuration.configuration_version == 0
    assert not state.configuration.framework_enabled
    assert not state.tools[0].configured_enabled and not state.tools[0].effective_enabled
    with pytest.raises(ToolFeatureUnavailableError):
        service.require_enabled("test.read")
    enabled = service.update(update(0))
    assert enabled.tools[0].effective_enabled
    assert service.require_enabled("test.read").tool_id == "test.read"
    disabled = service.update(update(1, False))
    assert disabled.tools[0].configured_enabled and not disabled.tools[0].effective_enabled
    assert disabled.tools[0].reason == "framework_disabled"
    disabled_tool = service.update(update(2, True, ()))
    assert disabled_tool.tools[0].reason == "tool_disabled"
    assert not disabled_tool.tools[0].effective_enabled


def test_unknown_ids_conflicts_and_no_implicit_admin(repository: ToolFeatureRepository) -> None:
    service = ToolFeatureService(registry(), repository, TestAdministration())
    for ids in (("unknown.read",), ("test.read", "test.read")):
        with pytest.raises(ValueError):
            service.update(update(0, ids=ids))
    assert repository.get() is None
    with pytest.raises(ToolFeatureAdministrationRequiredError):
        ToolFeatureService(registry(), repository).update(update(0))
    service.update(update(0))
    with pytest.raises(ToolFeatureConflictError):
        service.update(update(0, False))
    with pytest.raises(ToolFeatureUnavailableError, match="unknown_tool"):
        service.require_enabled("not.registered")


def test_concurrent_compare_and_set_has_one_winner(repository: ToolFeatureRepository) -> None:
    service = ToolFeatureService(registry(), repository, TestAdministration())

    def save(_: int) -> bool:
        try:
            service.update(update(0))
            return True
        except ToolFeatureConflictError:
            return False

    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(pool.map(save, range(16))) == 1
    assert service.state().configuration.configuration_version == 1


def test_sqlite_restart_and_corrupt_state_fail_closed(tmp_path: Path) -> None:
    path = str(tmp_path / "features.sqlite3")
    database = SqliteDatabase(path)
    service = ToolFeatureService(registry(), RelationalToolFeatureRepository(database), TestAdministration())
    service.update(update(0))
    database.dispose()
    reopened = SqliteDatabase(path)
    try:
        service = ToolFeatureService(registry(), RelationalToolFeatureRepository(reopened), TestAdministration())
        assert service.state().tools[0].effective_enabled
        with reopened.transaction() as connection:
            connection.execute("UPDATE tool_feature_configuration SET enabled_tool_ids = 'not-json'")
        assert service.state().configuration_status == "invalid"
        assert not service.state().tools[0].effective_enabled and not service.state().can_manage
        with pytest.raises(ToolFeatureUnavailableError):
            service.require_enabled("test.read")
        with pytest.raises(ValueError):
            service.update(update(1))
    finally:
        reopened.dispose()


def test_new_registration_is_disabled_and_removed_definition_invalidates_configuration() -> None:
    catalog = registry()
    store = ToolFeatureStore()
    service = ToolFeatureService(catalog, store, TestAdministration())
    service.update(update(0))
    other = catalog.get("test.read")
    assert other is not None
    catalog.register(other.model_copy(update={"tool_id": "test.new"}))
    assert not next(item for item in service.state().tools if item.definition.tool_id == "test.new").effective_enabled
    state = ToolFeatureService(ToolRegistry(), store, TestAdministration()).state()
    assert state.configuration_status == "invalid" and not state.configuration.framework_enabled


@pytest.mark.parametrize(
    "body",
    [
        {"framework_enabled": "true", "enabled_tool_ids": [], "expected_version": 0},
        {"framework_enabled": True, "enabled_tool_ids": [], "expected_version": True},
        {"framework_enabled": True, "enabled_tool_ids": ["../x"], "expected_version": 0},
        {"framework_enabled": True, "enabled_tool_ids": [], "expected_version": 0, "isAdmin": True},
    ],
)
def test_configuration_validation(body: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        UpdateToolFeaturesRequest.model_validate(body)


def test_api_default_denial_and_trusted_integration_with_asgi_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    # This host's AnyIO worker scheduling hangs even without TestClient.
    # Exercise routing/validation/error mapping in-process without that worker
    # dependency; production keeps its normal threadpool dispatch unchanged.
    async def direct_threadpool(func, *args, **kwargs):  # type: ignore[no-untyped-def]
        return func(*args, **kwargs)

    monkeypatch.setattr("fastapi.routing.run_in_threadpool", direct_threadpool)

    async def scenario() -> None:
        for administration in (None, TestAdministration()):
            app = create_app(
                settings=Settings(persistence_provider="memory", attachment_storage="memory"),
                feature_administration=administration,
            )
            app.state.tool_registry.register(registry().get("test.read"))
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                read = await client.get("/settings/tool-features")
                assert read.status_code == 200 and not read.json()["configuration"]["framework_enabled"]
                result = await client.put(
                    "/settings/tool-features", json=update(0).model_dump(mode="json"), headers={"X-Role": "admin"}
                )
                if administration is None:
                    assert result.status_code == 403
                    assert not (await client.get("/settings/tool-features")).json()["configuration"][
                        "framework_enabled"
                    ]
                else:
                    assert result.status_code == 200 and result.json()["tools"][0]["effective_enabled"]
                    assert (
                        await client.put("/settings/tool-features", json=update(0).model_dump(mode="json"))
                    ).status_code == 409
                    assert (
                        await client.put(
                            "/settings/tool-features", json=update(1, ids=("unknown",)).model_dump(mode="json")
                        )
                    ).status_code == 422
            app.state.persistence.dispose()

    asyncio.run(scenario())


def test_feature_enabled_does_not_grant_execution_permission() -> None:
    from ava.contracts.runtimes import RuntimeCapabilities
    from ava.execution.tool_security import ToolAuthorizationPolicy

    service = ToolFeatureService(registry(), ToolFeatureStore(), TestAdministration())
    service.update(update(0))
    assert service.require_enabled("test.read")
    assert (
        not ToolAuthorizationPolicy()
        .evaluate(
            tool_id="file_editor",
            capabilities=RuntimeCapabilities(tools=True, filesystem=True),
            workspace=None,
        )
        .allowed
    )


def test_administration_errors_and_revocation_deny_before_commit() -> None:
    class BrokenAdministration:
        def can_manage(self) -> bool:
            raise RuntimeError("untrusted authentication error")

    store = ToolFeatureStore()
    service = ToolFeatureService(registry(), store, BrokenAdministration())
    assert not service.state().can_manage
    with pytest.raises(ToolFeatureAdministrationRequiredError):
        service.update(update(0))
    assert store.get() is None

    class WithdrawnAdministration:
        calls = 0

        def can_manage(self) -> bool:
            self.calls += 1
            return self.calls < 3

    with pytest.raises(ToolFeatureAdministrationRequiredError):
        ToolFeatureService(registry(), store, WithdrawnAdministration()).update(update(0))
    assert store.get() is None


def test_configuration_zero_version_cannot_enable_features() -> None:
    with pytest.raises(ValidationError):
        ToolFeatureConfiguration(framework_enabled=True)
