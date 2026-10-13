"""Registry snapshots and composition without execution or public endpoints."""

from concurrent.futures import ThreadPoolExecutor

import pytest
from pydantic import ValidationError

from ava.configuration.settings import Settings
from ava.contracts.tools import ToolCapability, ToolDefinition, ToolExecutionCategory, ToolRisk
from ava.tools import ToolRegistry


def definition(
    tool_id: str = "test.read",
    *,
    capabilities: tuple[ToolCapability, ...] = (ToolCapability.FILE_READ,),
    category: ToolExecutionCategory = ToolExecutionCategory.DETERMINISTIC,
) -> ToolDefinition:
    return ToolDefinition(
        tool_id=tool_id,
        name="Test-only read",
        description="Fixture; no handler.",
        tool_version="1",
        input_schema={"type": "object", "properties": {"resource_id": {"type": "string"}}, "required": ["resource_id"]},
        output_schema={"type": "object", "properties": {"values": {"type": "array", "items": {"type": "string"}}}},
        required_capabilities=capabilities,
        risk=ToolRisk.LOW,
        execution_category=category,
    )


def test_registration_lookup_and_all_metadata() -> None:
    registry = ToolRegistry()
    value = definition()
    registry.register(value)
    stored = registry.get(value.tool_id)
    assert stored == value
    assert stored is not value
    assert registry.list() == [value]
    assert registry.get("unknown.read") is None
    assert registry.get("../path") is None


def test_duplicate_identity_rejected_even_for_same_or_new_version() -> None:
    registry = ToolRegistry()
    value = definition()
    registry.register(value)
    for duplicate in (value, value.model_copy(update={"tool_version": "2"})):
        with pytest.raises(ValueError, match="already registered"):
            registry.register(duplicate)
    assert registry.list() == [value]


def test_list_sorted_independently_of_insertion_order_and_returned_list_edits() -> None:
    registry = ToolRegistry()
    for tool_id in ("z.read", "a.write", "m.read"):
        registry.register(definition(tool_id))
    values = registry.list()
    assert [value.tool_id for value in values] == ["a.write", "m.read", "z.read"]
    values.clear()
    assert len(registry.list()) == 3


def test_capability_and_category_filters_intersect_and_preserve_order() -> None:
    registry = ToolRegistry()
    registry.register(definition("z.agent", category=ToolExecutionCategory.AGENTIC))
    registry.register(definition("b.edit", capabilities=(ToolCapability.FILE_READ, ToolCapability.FILE_WRITE)))
    registry.register(definition("a.read"))
    assert [d.tool_id for d in registry.discover(capabilities=(ToolCapability.FILE_READ,))] == [
        "a.read",
        "b.edit",
        "z.agent",
    ]
    assert [
        d.tool_id for d in registry.discover(capabilities=(ToolCapability.FILE_READ, ToolCapability.FILE_WRITE))
    ] == [
        "b.edit",
    ]
    assert [d.tool_id for d in registry.discover(category=ToolExecutionCategory.AGENTIC)] == ["z.agent"]
    assert registry.discover(capabilities=(ToolCapability.NETWORK_ACCESS,)) == []
    assert registry.discover(capabilities=(ToolCapability.FILE_WRITE,), category=ToolExecutionCategory.AGENTIC) == []
    assert registry.discover() == registry.list()


@pytest.mark.parametrize("read", ["get", "list", "discover"])
def test_input_and_all_read_paths_cannot_mutate_registry_schemas(read: str) -> None:
    registry = ToolRegistry()
    value = definition()
    registry.register(value)
    expected = value.model_dump_json()
    value.input_schema.clear()
    value.output_schema["properties"] = {}
    result = registry.get("test.read") if read == "get" else getattr(registry, read)()[0]
    assert isinstance(result, ToolDefinition)
    properties = result.input_schema["properties"]
    assert isinstance(properties, dict)
    resource = properties["resource_id"]
    assert isinstance(resource, dict)
    resource["type"] = "number"
    required = result.input_schema["required"]
    assert isinstance(required, list)
    required.append("unregistered")
    result.input_schema.clear()
    result.output_schema["properties"] = {}
    untouched = registry.get("test.read")
    assert untouched is not None and untouched.model_dump_json() == expected


@pytest.mark.parametrize(
    "patch",
    [
        {"tool_id": "../escape"},
        {"contract_version": "v2"},
        {"input_schema": {}},
        {"output_schema": {"type": "object", "$ref": "https://example.invalid/schema"}},
        {"required_capabilities": ("vendor_shell",)},
    ],
)
def test_registration_revalidates_bypassed_contract_instances(patch: dict[str, object]) -> None:
    registry = ToolRegistry()
    # model_construct deliberately bypasses validation; registration must not.
    malformed = ToolDefinition.model_construct(**{**definition().model_dump(), **patch})
    with pytest.raises(ValidationError):
        registry.register(malformed)
    assert registry.list() == []


def test_mutated_nested_schema_is_revalidated() -> None:
    registry = ToolRegistry()
    value = definition()
    value.input_schema["type"] = "vendor_type"
    with pytest.raises(ValidationError):
        registry.register(value)
    assert registry.get("test.read") is None


def test_wrong_registration_type_is_rejected_and_instances_are_isolated() -> None:
    left, right = ToolRegistry(), ToolRegistry()
    with pytest.raises(TypeError):
        left.register({"tool_id": "test.read"})  # type: ignore[arg-type]
    left.register(definition())
    assert right.list() == []
    right.register(definition())
    assert left.get("test.read") == right.get("test.read")


def test_concurrent_reads_return_isolated_ordered_snapshots() -> None:
    registry = ToolRegistry()
    registry.register(definition("z.read"))
    registry.register(definition("a.read"))

    def read(_: int) -> tuple[str, ...]:
        values = registry.discover(capabilities=(ToolCapability.FILE_READ,))
        ids = tuple(value.tool_id for value in values)
        values[0].input_schema.clear()
        assert registry.get("a.read") is not None
        return ids

    with ThreadPoolExecutor(max_workers=8) as pool:
        assert list(pool.map(read, range(64))) == [("a.read", "z.read")] * 64
    assert registry.get("a.read") == definition("a.read")


def test_concurrent_duplicate_registration_has_one_winner() -> None:
    registry = ToolRegistry()

    def register(_: int) -> bool:
        try:
            registry.register(definition())
            return True
        except ValueError:
            return False

    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(pool.map(register, range(32))) == 1
    assert len(registry.list()) == 1


def test_composition_registers_only_descriptive_initial_tools_without_execution_claim() -> None:
    from ava.api.app import create_app
    from ava.infrastructure.composition import create_tool_registry

    registry = create_tool_registry()
    assert isinstance(registry, ToolRegistry)
    assert [item.tool_id for item in registry.list()] == [
        "workspace.file_info",
        "workspace.list_files",
        "workspace.read_file",
    ]
    registry.register(definition())
    assert [item.tool_id for item in create_tool_registry().list()] == [
        "workspace.file_info",
        "workspace.list_files",
        "workspace.read_file",
    ]
    # App construction only: no lifespan, TestClient sockets, or inference.
    app = create_app(settings=Settings(persistence_provider="memory", attachment_storage="memory"))
    assert isinstance(app.state.tool_registry, ToolRegistry)
    assert [item.tool_id for item in app.state.tool_registry.list()] == [
        "workspace.file_info",
        "workspace.list_files",
        "workspace.read_file",
    ]
    feature_state = app.state.tool_feature_service.state()
    assert not feature_state.framework_effective_enabled
    assert all(not item.effective_enabled for item in feature_state.tools)
    assert app.state.tool_execution_service._executors == {}
    assert not any(getattr(route, "path", "").startswith("/tools") for route in app.routes)
    assert not {"execute", "authorize", "approve", "enable"} & set(dir(registry))
    assert "authorized" not in ToolDefinition.model_fields


def test_registration_cannot_activate_an_existing_runtime_tool() -> None:
    from ava.contracts.runtimes import RuntimeCapabilities
    from ava.execution.tool_security import ToolAuthorizationPolicy

    registry = ToolRegistry()
    registry.register(definition("file_editor"))
    assert registry.get("file_editor") is not None
    decision = ToolAuthorizationPolicy().evaluate(
        tool_id="file_editor",
        capabilities=RuntimeCapabilities(tools=True, filesystem=True),
        workspace=None,
    )
    assert not decision.allowed and decision.reason_code == "workspace_required"


def test_discovery_rejects_vendor_or_permission_filters() -> None:
    registry = ToolRegistry()
    registry.register(definition())
    with pytest.raises(ValueError):
        registry.discover(capabilities=("allow_shell",))  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        registry.discover(category="openhands")  # type: ignore[arg-type]
