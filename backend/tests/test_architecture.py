"""Architecture enforcement tests.

Establishes that AVA core and contracts must not import vendor/provider
infrastructure, and that AVA's internal dependency direction is respected:

    API / Infrastructure
            ↓
         Services
            ↓
    Core / Ports / Contracts

Never the reverse. Framework types must never escape adapters.
"""

import ast
import re
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[1] / "src" / "ava"
CORE_DIR = SRC_DIR / "core"
CONTRACTS_DIR = SRC_DIR / "contracts"
SERVICES_DIR = SRC_DIR / "services"
API_DIR = SRC_DIR / "api"
AGENTS_DIR = SRC_DIR / "agents"
EXECUTION_DIR = SRC_DIR / "execution"
AGENT_ADAPTERS_DIR = SRC_DIR / "agents" / "adapters"
MOCK_ADAPTER_DIR = AGENT_ADAPTERS_DIR / "mock"
MODELS_DIR = SRC_DIR / "models"
MODELS_PORT_FILE = MODELS_DIR / "contracts.py"
MODELS_REGISTRY_FILE = MODELS_DIR / "model_registry.py"
MODELS_RESOLVER_FILE = MODELS_DIR / "resolver.py"
OPENAI_COMPATIBLE_PROVIDER_DIR = MODELS_DIR / "providers" / "openai_compatible"
CONFIGURATION_DIR = SRC_DIR / "configuration"
INFRASTRUCTURE_DIR = SRC_DIR / "infrastructure"
PERSISTENCE_DIR = INFRASTRUCTURE_DIR / "persistence"
REPOSITORIES_DIR = SRC_DIR / "repositories"

# Vendor/provider modules that must never appear in AVA core or contracts.
FORBIDDEN_IMPORTS = {
    "fastapi",
    "uvicorn",
    "langchain",
    "langgraph",
    "sqlalchemy",
    "openai",
    "anthropic",
    "ollama",
    "boto3",
    "aws",
    "databricks",
    "torch",
    "transformers",
}

# Internal dependency boundaries. Each directory name maps to the set of
# sibling AVA modules it must never import. Ports are excluded from the
# agents/models restriction and treated as dependencies of core/services.
INTERNAL_BOUNDARIES: dict[str, set[str]] = {
    "core": {"api", "infrastructure", "services"},
    "contracts": {"api", "infrastructure", "services", "agents", "models"},
    "services": {"api", "infrastructure"},
    "repositories": {"api", "infrastructure", "services", "agents", "models", "core"},
}

# Modules in agents/models that are ports and may be imported by core/services.
PORT_MODULES = {"agents.contracts", "models.contracts"}


def _iter_python_files(directory: Path) -> list[Path]:
    """Yield all .py files beneath the given directory."""
    return sorted(directory.rglob("*.py"))


def _top_level_imports(tree: ast.Module) -> set[str]:
    """Collect the set of top-level imported module names."""
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module.split(".")[0])
    return imports


def _ava_imports(tree: ast.Module) -> set[str]:
    """Collect full dotted import paths rooted at the ``ava`` package."""
    paths: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "ava" or alias.name.startswith("ava."):
                    paths.add(alias.name)
        if (
            isinstance(node, ast.ImportFrom)
            and node.level == 0
            and node.module
            and (node.module == "ava" or node.module.startswith("ava."))
        ):
            paths.add(node.module)
    return paths


def _ava_sibling_imports(tree: ast.Module) -> set[str]:
    """Collect the second-level module names imported from the ava package."""
    return {path.split(".")[1] for path in _ava_imports(tree) if len(path.split(".")) >= 2}


# ============================================================
# BEGIN: Core Independence Tests
# ============================================================


def test_tool_contracts_remain_inward_values_without_execution_dependencies() -> None:
    """Phase 6.2 tool values import no policy implementation, SDK or executor."""
    tree = ast.parse((CONTRACTS_DIR / "tools.py").read_text(encoding="utf-8"))
    assert _top_level_imports(tree) <= {"math", "datetime", "enum", "typing", "pydantic", "ava"}
    assert _ava_imports(tree) <= {
        "ava.contracts.errors", "ava.contracts.json_types", "ava.contracts.version",
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            assert node.level == 0, "Relative imports must not bypass tool boundaries"
        assert not isinstance(node, (ast.AsyncFunctionDef, ast.Await)), "Tool values must not execute"
    classes = {node.name for node in tree.body if isinstance(node, ast.ClassDef)}
    assert not classes & {"ToolRegistry", "ToolExecutionService", "ApprovalService"}


def test_tool_registry_is_a_catalog_without_runtime_or_policy_authority() -> None:
    directory = SRC_DIR / "tools"
    assert (directory / "registry.py").is_file()
    for path in (directory / "registry.py", directory / "__init__.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        assert _top_level_imports(tree) <= {"__future__", "ava", "builtins", "collections", "threading"}
        assert _ava_imports(tree) <= {"ava.contracts.tools", "ava.tools.registry"}
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert node.level == 0
            assert not isinstance(node, (ast.AsyncFunctionDef, ast.Await))
    # Registrations originate in trusted composition, never runtime SDK code.
    for directory in (AGENT_ADAPTERS_DIR, SRC_DIR / "runtimes"):
        for path in _iter_python_files(directory):
            assert not any(
                name.startswith("ava.tools") for name in _ava_imports(ast.parse(path.read_text(encoding="utf-8")))
            ), path


def test_tool_feature_management_is_separate_from_runtime_and_execution_authority() -> None:
    tree = ast.parse((SERVICES_DIR / "tool_feature_service.py").read_text(encoding="utf-8"))
    assert not any(
        name.startswith(("ava.runtimes", "ava.models", "ava.execution", "ava.infrastructure"))
        for name in _ava_imports(tree)
    )
    route = ast.parse((API_DIR / "routes" / "tool_features.py").read_text(encoding="utf-8"))
    assert all(name.startswith(("ava.contracts", "ava.services")) for name in _ava_imports(route))
    from ava.contracts.tool_features import ToolFeatureConfiguration, UpdateToolFeaturesRequest

    assert not ToolFeatureConfiguration().framework_enabled
    assert not ToolFeatureConfiguration().enabled_tool_ids
    assert set(UpdateToolFeaturesRequest.model_fields) == {
        "framework_enabled", "enabled_tool_ids", "expected_version", "contract_version",
    }


def test_tool_policy_is_runtime_neutral_and_run_service_does_not_own_it() -> None:
    path = SERVICES_DIR / "tool_policy_service.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    assert _top_level_imports(tree) <= {"ava", "hashlib", "json", "collections", "types", "pathlib", "stat", "pydantic"}
    assert not any(name.startswith(("ava.runtimes", "ava.models", "ava.infrastructure", "ava.api"))
                   for name in _ava_imports(tree))
    assert "ava.workspaces.resolver" in _ava_imports(tree)
    assert "ava.execution.command_policy" in _ava_imports(tree)
    assert "ava.services.tool_feature_service" in _ava_imports(tree)
    run = ast.parse((SERVICES_DIR / "run_service.py").read_text(encoding="utf-8"))
    assert "ava.services.tool_policy_service" not in _ava_imports(run)
    authority = ast.parse((SRC_DIR / "tools" / "authority.py").read_text(encoding="utf-8"))
    assert _top_level_imports(authority) <= {"dataclasses", "enum", "typing", "ava"}
    assert _ava_imports(authority) <= {"ava.contracts.tools", "ava.workspaces.contracts"}


def test_core_modules_have_files() -> None:
    """The core directory should contain at least one Python module."""
    assert list(_iter_python_files(CORE_DIR)), "AVA core must contain modules"


def test_core_must_not_import_forbidden_modules() -> None:
    """AVA core must never import vendor/provider infrastructure."""
    violations: list[str] = []
    for path in _iter_python_files(CORE_DIR):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for name in _top_level_imports(tree):
            if name in FORBIDDEN_IMPORTS:
                violations.append(f"{path}: imports '{name}'")
    assert not violations, "Forbidden imports in AVA core:\n" + "\n".join(violations)


# ============================================================
# END: Core Independence Tests
# ============================================================


# ============================================================
# BEGIN: Contracts Independence Tests
# ============================================================


def test_contracts_must_not_import_transport_or_ai_frameworks() -> None:
    """AVA contracts must never import transport or AI framework modules.

    Contracts are AVA-owned and provider-neutral. They may depend only on
    stdlib and Pydantic so both backend and future client implementations can
    share them.
    """
    violations: list[str] = []
    for path in _iter_python_files(CONTRACTS_DIR):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for name in _top_level_imports(tree):
            if name in FORBIDDEN_IMPORTS:
                violations.append(f"{path}: imports '{name}'")
    assert not violations, "Forbidden imports in AVA contracts:\n" + "\n".join(violations)


# ============================================================
# END: Contracts Independence Tests
# ============================================================


# ============================================================
# BEGIN: Agent Adapter Independence Tests
# ============================================================


def test_mock_adapter_must_not_import_forbidden_modules() -> None:
    """The mock adapter must be free of AI/provider and transport libraries.

    This adapter exists specifically to validate AVA's execution flow
    without binding AVA to an AI framework, so any such import is a
    regression.
    """
    violations: list[str] = []
    for path in _iter_python_files(MOCK_ADAPTER_DIR):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for name in _top_level_imports(tree):
            if name in FORBIDDEN_IMPORTS:
                violations.append(f"{path}: imports '{name}'")
    assert not violations, "Forbidden imports in mock adapter:\n" + "\n".join(violations)


def test_mock_adapter_depends_only_on_ports_and_contracts() -> None:
    """The mock adapter must depend inward on AVA ports/contracts only.

    It may never reach outward into AVA services, core behavior, API layer,
    or infrastructure.
    """
    allowed = {"agents", "contracts"}
    violations: list[str] = []
    for path in _iter_python_files(MOCK_ADAPTER_DIR):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for sibling in _ava_sibling_imports(tree):
            if sibling not in allowed:
                violations.append(f"{path}: imports 'ava.{sibling}'")
    assert not violations, "Outward imports in mock adapter:\n" + "\n".join(violations)


# ============================================================
# END: Agent Adapter Independence Tests
# ============================================================


# ============================================================
# BEGIN: Model Port Independence Tests
# ============================================================


def test_model_port_must_not_import_forbidden_modules() -> None:
    """The model provider port must be free of vendor/provider and transport libraries.

    ``ava.models.contracts`` defines the ``ModelProviderPort`` abstraction.
    AVA Core programs against it; real provider SDKs must not leak into the
    port layer.
    """
    violations: list[str] = []
    for path in (MODELS_PORT_FILE,):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for name in _top_level_imports(tree):
            if name in FORBIDDEN_IMPORTS:
                violations.append(f"{path}: imports '{name}'")
    assert not violations, "Forbidden imports in models port:\n" + "\n".join(violations)


def test_model_port_depends_only_on_contracts() -> None:
    """The model port must depend inward on AVA contracts only.

    It may never reach outward into AVA services, core, API layer,
    agents, infrastructure, or concrete provider implementations.
    The same constraint applies to other modules in the models layer
    (e.g. the provider registry), which may depend on the port or on
    contracts but on nothing outward.
    """
    allowed = {"contracts", "models"}
    violations: list[str] = []
    for path in _iter_python_files(MODELS_DIR):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for sibling in _ava_sibling_imports(tree):
            if sibling not in allowed:
                violations.append(f"{path}: imports 'ava.{sibling}'")
    assert not violations, "Outward imports in models layer:\n" + "\n".join(violations)


# ============================================================
# END: Model Port Independence Tests
# ============================================================


# ============================================================
# BEGIN: Model Resolver Independence Tests
# ============================================================


def test_model_resolver_depends_only_on_models_and_contracts() -> None:
    """The resolver may depend only on the registry, the port, and contracts.

    It must never import vendor/provider SDKs, the agent ports/adapters,
    RunService, runtime frameworks, configuration, or any outward layer.
    Resolution is AVA-identity-based only.
    """
    allowed = {"contracts", "models"}
    violations: list[str] = []
    tree = ast.parse(
        MODELS_RESOLVER_FILE.read_text(encoding="utf-8"),
        filename=str(MODELS_RESOLVER_FILE),
    )
    for name in _top_level_imports(tree):
        if name in FORBIDDEN_IMPORTS:
            violations.append(f"{MODELS_RESOLVER_FILE}: imports '{name}'")
    for sibling in _ava_sibling_imports(tree):
        if sibling not in allowed:
            violations.append(f"{MODELS_RESOLVER_FILE}: imports 'ava.{sibling}'")
    assert not violations, "Resolver dependency violations:\n" + "\n".join(violations)


# ============================================================
# END: Model Resolver Independence Tests
# ============================================================


# ============================================================
# BEGIN: Model Provider Discovery Service Independence Tests
# ============================================================


def test_model_provider_discovery_service_imports_only_contracts_and_model_ports() -> None:
    """The discovery service depends only on contracts and the model layer.

    Discovery answers "what providers are available?" through the registry and
    ``ModelProviderPort``; it must never import concrete providers, HTTP
    clients, configuration, agent layers, runtime frameworks, the API layer,
    or infrastructure. The route-side guard (API layer never imports concrete
    providers) already covers its consumer.
    """
    file = SERVICES_DIR / "model_provider_discovery_service.py"
    allowed = {"contracts", "models"}
    violations: list[str] = []
    tree = ast.parse(file.read_text(encoding="utf-8"), filename=str(file))
    for name in _top_level_imports(tree):
        if name in FORBIDDEN_IMPORTS:
            violations.append(f"{file}: imports forbidden module '{name}'")
    for import_path in _ava_imports(tree):
        if import_path.startswith("ava.models.providers"):
            violations.append(f"{file}: imports concrete provider '{import_path}'")
    for sibling in _ava_sibling_imports(tree):
        if sibling not in allowed:
            violations.append(f"{file}: imports 'ava.{sibling}'")
    assert not violations, "Discovery service dependency violations:\n" + "\n".join(violations)


# ============================================================
# END: Model Provider Discovery Service Independence Tests
# ============================================================


# ============================================================
# BEGIN: OpenAI-Compatible Provider Independence Tests
# ============================================================


def test_openai_compatible_provider_imports_only_contracts_and_http() -> None:
    """The concrete provider may depend only on AVA contracts + a generic HTTP client.

    It may never depend on the registry, the resolver, configuration, agent
    layers, services, the API layer, or vendor SDKs. The provider is a pure
    protocol adapter: it does not register itself and does not know its AVA
    registry id.
    """
    allowed_siblings = {"contracts", "models"}
    violations: list[str] = []
    for path in _iter_python_files(OPENAI_COMPATIBLE_PROVIDER_DIR):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for name in _top_level_imports(tree):
            if name in FORBIDDEN_IMPORTS:
                violations.append(f"{path}: imports forbidden module '{name}'")
        for import_path in _ava_imports(tree):
            parts = import_path.split(".")
            if len(parts) < 2 or parts[1] not in allowed_siblings:
                violations.append(f"{path}: imports '{import_path}'")
            if import_path.startswith("ava.models.registry") or import_path.startswith("ava.models.resolver"):
                violations.append(f"{path}: imports registry/resolver '{import_path}'")
    assert not violations, "OpenAI-compatible provider dependency violations:\n" + "\n".join(violations)


def test_runtime_layers_must_not_import_openai_compatible_provider() -> None:
    """API, services, core, and agent layers never import the concrete provider.

    RunService (services) and AgentPort (agents) reach models only through the
    ``ModelProviderPort`` abstraction; importing the concrete OpenAI-compatible
    adapter in these runtime layers would couple execution to a vendor protocol.
    """
    runtime_dirs = (API_DIR, SERVICES_DIR, CORE_DIR, AGENTS_DIR)
    violations: list[str] = []
    for directory in runtime_dirs:
        for path in _iter_python_files(directory):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for import_path in _ava_imports(tree):
                if import_path.startswith("ava.models.providers.openai_compatible"):
                    violations.append(f"{path}: imports '{import_path}'")
    assert not violations, "Concrete provider imports in runtime layers:\n" + "\n".join(violations)


# ============================================================
# END: OpenAI-Compatible Provider Independence Tests
# ============================================================


# ============================================================
# BEGIN: Provider Construction Localization Tests
# ============================================================


def test_provider_construction_is_localized_to_infrastructure() -> None:
    """The concrete model provider is constructed only by the composition layer.

    ``ava.models.providers.openai_compatible`` may be imported by its own
    package and by the infrastructure composition module (where the configured
    provider is built and registered). Every other AVA module — including the
    API factory and its routes — must reach the provider only through
    composition, so provider choice stays a configuration decision.
    """
    allowed = (
        OPENAI_COMPATIBLE_PROVIDER_DIR,  # the adapter's own package
        INFRASTRUCTURE_DIR / "composition.py",  # provider construction site
        INFRASTRUCTURE_DIR / "model_provider_factory.py",  # per-run connection construction
    )
    violations: list[str] = []
    for path in _iter_python_files(SRC_DIR):
        if any(path.is_relative_to(directory) for directory in allowed):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for import_path in _ava_imports(tree):
            if import_path.startswith("ava.models.providers.openai_compatible"):
                violations.append(f"{path}: imports '{import_path}'")
    assert not violations, "Provider imports outside infrastructure composition:\n" + "\n".join(violations)


# ============================================================
# END: Provider Construction Localization Tests
# ============================================================


# ============================================================
# BEGIN: Configuration Independence Tests
# ============================================================


def test_configuration_must_not_import_registry_or_providers() -> None:
    """The configuration layer must not depend on the registry or providers.

    Configuration answers only what the application is configured to use. It
    must never reach into provider resolution, the ``ModelProviderRegistry``,
    or concrete model-provider adapters — those belong to the resolution step.
    """
    forbidden_prefixes = (
        "ava.models.registry",
        "ava.models.providers",
    )
    violations: list[str] = []
    for path in _iter_python_files(CONFIGURATION_DIR):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for import_path in _ava_imports(tree):
            if any(import_path.startswith(prefix) for prefix in forbidden_prefixes):
                violations.append(f"{path}: imports '{import_path}'")
    assert not violations, "Registry/provider imports in configuration layer:\n" + "\n".join(violations)


# ============================================================
# END: Configuration Independence Tests
# ============================================================


# ============================================================
# BEGIN: Internal Dependency Direction Tests
# ============================================================


def test_internal_dependency_direction_is_respected() -> None:
    """No AVA module may cross its boundary the wrong way.

    Enforces: API / Infrastructure → Services → Core / Ports / Contracts.
    """
    violations: list[str] = []
    for dir_name, forbidden in INTERNAL_BOUNDARIES.items():
        directory = SRC_DIR / dir_name
        for path in _iter_python_files(directory):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for name in _ava_sibling_imports(tree):
                if (
                    path.name in {"provider_connection_repository.py", "model_configuration_repository.py"}
                    and name == "models"
                ):
                    continue
                if name in forbidden:
                    violations.append(f"{path}: imports 'ava.{name}'")
    assert not violations, "Internal boundary violations:\n" + "\n".join(violations)


def test_api_must_not_import_concrete_adapters() -> None:
    """The API layer must reach agents/models only through services/ports.

    Route and factory modules must never import concrete adapter
    implementations such as ``ava.agents.adapters.mock`` or
    ``ava.models.providers``.
    """
    violations: list[str] = []
    for path in _iter_python_files(API_DIR):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for import_path in _ava_imports(tree):
            if import_path.startswith("ava.agents.adapters") or import_path.startswith("ava.models.providers"):
                violations.append(f"{path}: imports '{import_path}'")
    assert not violations, "Adapter imports in the API layer:\n" + "\n".join(violations)


def test_services_must_not_import_concrete_adapters() -> None:
    """The services layer must reach agents/models only through their ports.

    Services orchestrate agent adapters via ``AgentPort``; importing a
    concrete ``ava.agents.adapters.*`` implementation here would couple the
    core to a provider.
    """
    violations: list[str] = []
    for path in _iter_python_files(SERVICES_DIR):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for import_path in _ava_imports(tree):
            if import_path.startswith("ava.agents.adapters") or import_path.startswith("ava.models.providers"):
                violations.append(f"{path}: imports '{import_path}'")
    assert not violations, "Adapter imports in the services layer:\n" + "\n".join(violations)


def test_core_may_import_agents_and_models_only_through_their_ports() -> None:
    """AVA core must reach agents/models only through the port modules.

    Concrete adapters (anything other than the ports) must never be imported
    by core.
    """
    violations: list[str] = []
    for path in _iter_python_files(CORE_DIR):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for import_path in _ava_imports(tree):
            if any(import_path.startswith(f"ava.{fragment}") for fragment in ("agents", "models")) and not any(
                import_path == port or import_path.startswith(f"{port}.") for port in PORT_MODULES
            ):
                violations.append(f"{path}: imports '{import_path}'")
    assert not violations, "Non-port imports in AVA core:\n" + "\n".join(violations)


# ============================================================
# END: Internal Dependency Direction Tests
# ============================================================


def test_native_agent_depends_only_on_contracts_and_stdlib() -> None:
    """Additive native guard, including the AVA error contract's actual location."""
    import sys

    files = _iter_python_files(AGENT_ADAPTERS_DIR / "native")
    assert files
    allowed = {
        "ava.agents.contracts",
        "ava.models.bindings",
        "ava.models.contracts",
        "ava.models.errors",
        "ava.models.model_registry",
        "ava.runtimes.contracts",
    }
    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert node.level == 0, f"Relative import bypass in {path}"
        for name in _top_level_imports(tree):
            assert name == "ava" or name in sys.stdlib_module_names, (path, name)
        for name in _ava_imports(tree):
            assert (
                name in allowed
                or name == "ava.contracts"
                or name.startswith("ava.contracts.")
                or name == "ava.workspaces"
                or name.startswith("ava.workspaces.")
                or name.startswith("ava.execution.")
            ), (path, name)


def test_run_service_remains_model_provider_free() -> None:
    tree = ast.parse((SERVICES_DIR / "run_service.py").read_text(encoding="utf-8"))
    assert not any(name.startswith("ava.models") for name in _ava_imports(tree))


def test_runtime_contract_layer_depends_only_on_ava_abstractions() -> None:
    """Allow Pydantic DTOs, stdlib, and inward contracts; reject outward imports."""
    import sys

    files = [SRC_DIR / "runtimes" / "contracts.py", SRC_DIR / "runtimes" / "__init__.py"]
    assert files
    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert node.level == 0, f"Relative import bypass in {path}"
        for name in _top_level_imports(tree):
            assert name in {"ava", "pydantic"} or name in sys.stdlib_module_names, (path, name)
        for name in _ava_imports(tree):
            allowed = (
                name == "ava.models.contracts"
                or name == "ava.models.bindings"
                or name == "ava.workspaces.contracts"
                or name.startswith("ava.contracts.")
            )
            if path.name == "__init__.py":
                allowed = allowed or name in {
                        "ava.runtimes.contracts",
                        "ava.runtimes.configurations",
                        "ava.runtimes.registry",
                    "ava.runtimes.resolver",
                }
            assert allowed, (path, name)


def test_model_and_data_contracts_do_not_depend_on_runtime_port() -> None:
    for path in [*_iter_python_files(CONTRACTS_DIR), MODELS_PORT_FILE]:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        assert not any(name.startswith("ava.runtimes") for name in _ava_imports(tree)), path


def test_run_service_does_not_depend_on_runtime_contracts() -> None:
    tree = ast.parse((SERVICES_DIR / "run_service.py").read_text(encoding="utf-8"))
    assert not any(name.startswith(("ava.runtimes", "ava.contracts.runtimes")) for name in _ava_imports(tree))


def test_native_runtime_depends_only_on_ports_and_contracts() -> None:
    """Implementation guard separate from the stricter runtime-port guard."""
    import sys

    files = _iter_python_files(SRC_DIR / "runtimes" / "adapters")
    assert files
    allowed = {
        "ava.models.contracts",
        "ava.models.errors",
        "ava.models.bindings",
        "ava.execution.command_policy",
        "ava.execution.tool_security",
        "ava.execution.sandbox",
        "ava.runtimes.contracts",
        "ava.runtimes.qualification",
        "ava.workspaces.contracts",
    }
    openhands_adapter_dir = SRC_DIR / "runtimes" / "adapters" / "openhands"
    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert node.level == 0, f"Relative import bypass in {path}"
        for name in _top_level_imports(tree):
            # OpenHands imports live only inside the OpenHands adapter
            # subpackage (the sanctioned adapter-local boundary); the SDK import
            # inside execute() is lazy and never eager.
            if name == "openhands" and path.is_relative_to(openhands_adapter_dir):
                continue
            assert name == "ava" or name in sys.stdlib_module_names, (path, name)
        for name in _ava_imports(tree):
            assert name in allowed or name.startswith("ava.contracts.") or name.startswith("ava.runtimes.adapters."), (
                path,
                name,
            )


def test_openhands_adapter_never_builds_terminal_task_or_shell() -> None:
    """Architecture guard: OpenHands adapter has no terminal/exec tools or shell.

    Step 33 grants FileEditorTool only. No TerminalTool, TaskTrackerTool,
    browser, delegation, apply_patch, or subprocess-style execution may be
    referenced anywhere in the adapter subpackage.
    """
    violations: list[str] = []
    forbidden_modules = {
        "openhands.tools.terminal",
        "openhands.tools.task_tracker",
        "openhands.tools.task",
        "openhands.tools.browser_use",
        "openhands.tools.delegate",
        "openhands.tools.apply_patch",
        "subprocess",
        "shlex",
    }
    forbidden_calls = {"os.system", "os.popen"}

    for path in _iter_python_files(SRC_DIR / "runtimes" / "adapters" / "openhands"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name in forbidden_modules:
                        violations.append(f"{path}: imports '{alias.name}'")
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module in forbidden_modules:
                violations.append(f"{path}: imports '{node.module}'")
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                base = getattr(node.func.value, "value", None) or getattr(node.func.value, "id", "")
                candidate = f"{base}.{node.func.attr}"
                if candidate in forbidden_calls:
                    violations.append(f"{path}: calls '{candidate}'")
    assert not violations, "Forbidden tool/shell usage in OpenHands adapter:\n" + "\n".join(violations)


def test_command_policy_is_runtime_neutral_and_never_executes_commands() -> None:
    """The Step 34 policy seam must not depend on OpenHands or run processes."""
    path = SRC_DIR / "execution" / "command_policy.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    forbidden = {"openhands", "subprocess", "os", "shlex"}
    imports = _top_level_imports(tree)
    assert not imports.intersection(forbidden), (path, imports.intersection(forbidden))


def test_public_run_request_has_no_shell_escalation_fields() -> None:
    """Clients select an opaque workspace, never terminal authority."""
    path = CONTRACTS_DIR / "requests.py"
    text = path.read_text(encoding="utf-8")
    for field in ("allow_shell", "enable_terminal", "allow_commands", "command_permissions"):
        assert field not in text, f"Public RunRequest must not expose {field}"


def test_runtime_registry_depends_only_on_runtime_port() -> None:
    """The container must not know models, implementations, or outward layers."""
    import sys

    path = SRC_DIR / "runtimes" / "registry.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            assert node.level == 0, f"Relative import bypass in {path}"
    for name in _top_level_imports(tree):
        assert name == "ava" or name in sys.stdlib_module_names, (path, name)
    assert _ava_imports(tree) == {"ava.runtimes.contracts"}


def test_runtime_resolver_depends_only_on_runtime_port_and_registry() -> None:
    """Resolution must not depend on models, implementations, or configuration."""
    import sys

    path = SRC_DIR / "runtimes" / "resolver.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            assert node.level == 0, f"Relative import bypass in {path}"
    for name in _top_level_imports(tree):
        assert name == "ava" or name in sys.stdlib_module_names, (path, name)
    assert _ava_imports(tree) == {"ava.runtimes.contracts", "ava.runtimes.registry"}


def test_workspace_discovery_service_imports_only_contracts_and_workspaces() -> None:
    """Workspace discovery depends only on contracts and the workspaces layer.

    Discovery answers "what workspaces are approved?" through the shared
    ``WorkspaceRegistry``; it must never import models, runtimes, adapters,
    configuration, the API layer, or infrastructure. It creates no
    ``RuntimeWorkspaceBinding`` and performs no filesystem/network activity.
    """
    file = SERVICES_DIR / "workspace_discovery_service.py"
    allowed = {"contracts", "workspaces"}
    violations: list[str] = []
    tree = ast.parse(file.read_text(encoding="utf-8"), filename=str(file))
    for name in _top_level_imports(tree):
        if name in FORBIDDEN_IMPORTS:
            violations.append(f"{file}: imports forbidden module '{name}'")
    for sibling in _ava_sibling_imports(tree):
        if sibling not in allowed:
            violations.append(f"{file}: imports 'ava.{sibling}'")
    assert not violations, "Workspace discovery service dependency violations:\n" + "\n".join(violations)


# ============================================================
# BEGIN: Workspace Security Boundary Tests
# ============================================================


def test_workspace_registry_and_resolver_depend_only_on_workspaces() -> None:
    """The registry/resolver must not know runtimes, models, or outward layers."""
    import sys

    for path in (SRC_DIR / "workspaces" / "registry.py", SRC_DIR / "workspaces" / "resolver.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert node.level == 0, f"Relative import bypass in {path}"
        for name in _top_level_imports(tree):
            assert name == "ava" or name in sys.stdlib_module_names, (path, name)
        siblings = {p.split(".")[1] for p in _ava_imports(tree) if len(p.split(".")) >= 2}
        assert siblings <= {"workspaces"}, (path, siblings)


def test_runtime_adapters_must_not_import_workspace_resolver_or_registry() -> None:
    """Runtimes receive only approved bindings; they never resolve workspace ids."""
    violations: list[str] = []
    for path in _iter_python_files(SRC_DIR / "runtimes" / "adapters"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for name in _ava_imports(tree):
            if name.startswith(("ava.workspaces.resolver", "ava.workspaces.registry")):
                violations.append(f"{path}: imports '{name}'")
    assert not violations, "Workspace resolver/registry imports in runtime adapters:\n" + "\n".join(violations)


def test_run_service_remains_workspace_free() -> None:
    """RunService depends only on AgentPort and never learns about workspaces."""
    tree = ast.parse((SERVICES_DIR / "run_service.py").read_text(encoding="utf-8"))
    assert not any(name.startswith("ava.workspaces") for name in _ava_imports(tree))


def test_agent_port_contract_remains_workspace_free() -> None:
    """The public AgentPort interface is unchanged by workspace orchestration.

    ``RunRequest`` already carries the opaque ``workspace_id``; workspace
    resolution lives inside the adapter implementation, not on the port.
    """
    tree = ast.parse((AGENTS_DIR / "contracts.py").read_text(encoding="utf-8"))
    assert not any(name.startswith("ava.workspaces") for name in _ava_imports(tree))


# ============================================================
# END: Workspace Security Boundary Tests
# ============================================================


def test_tool_security_has_no_runtime_model_or_provider_dependency() -> None:
    path = SRC_DIR / "execution" / "tool_security.py"
    tree = ast.parse(path.read_text())
    assert not (_top_level_imports(tree) & {"openhands", "litellm", "ollama"})
    assert not (_ava_sibling_imports(tree) & {"models", "runtimes", "infrastructure"})
    policy = next(
        node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "ToolAuthorizationPolicy"
    )
    names = {node.id for node in ast.walk(policy) if isinstance(node, ast.Name)}
    assert not (names & {"model_id", "provider", "runtime_id", "profile", "prompt"})


def test_run_service_does_not_own_security_policy() -> None:
    tree = ast.parse((SERVICES_DIR / "run_service.py").read_text())
    assert not (_ava_sibling_imports(tree) & {"execution", "workspaces", "runtimes"})
    assert not any(
        isinstance(node, ast.Name) and node.id in {"ToolAuthorizationPolicy", "WorkspaceRegistry", "RuntimeRegistry"}
        for node in ast.walk(tree)
    )


def test_public_request_has_no_permission_or_sandbox_grants() -> None:
    from ava.contracts.requests import RunRequest

    assert not (
        set(RunRequest.model_fields)
        & {
            "allow_shell",
            "enable_shell",
            "allow_write",
            "enable_network",
            "permissions",
            "workspace_root",
            "sandbox",
        }
    )


# ============================================================
# BEGIN: Multi-Model Descriptive-Not-Authoritative Boundary Tests
# ============================================================

_DESCRIPTIVE_MODEL_FIELDS = {
    "permissions",
    "allow_shell",
    "allow_write",
    "allow_network",
    "workspace_permissions",
    "sandbox_limits",
    "sandbox",
    "capability_grant",
    "elevated",
}


def test_model_and_runtime_metadata_contracts_carry_no_permission_grants() -> None:
    """Model/runtime metadata stays descriptive and never grants authority.

    A model's declared capabilities, runtime capabilities, provider health, and
    selection identities may inform routing, but they must never carry a
    permission, sandbox limit, or capability grant. Security decisions remain
    server/workspace-owned (Steps 32-36).
    """
    from ava.contracts.execution import RunExecutionOverride, RunExecutionSelection
    from ava.contracts.models import ModelCapabilities, ModelInfo, ModelProviderHealth
    from ava.contracts.runtimes import RuntimeCapabilities, RuntimeInfo

    for model in (
        ModelCapabilities,
        ModelInfo,
        ModelProviderHealth,
        RuntimeCapabilities,
        RuntimeInfo,
        RunExecutionSelection,
        RunExecutionOverride,
    ):
        assert not (set(model.model_fields) & _DESCRIPTIVE_MODEL_FIELDS), model.__name__


def test_runtime_model_binding_carries_no_permission_grants() -> None:
    """The provider-to-runtime binding transports identity, not authority."""
    from ava.models.bindings import ConfiguredModelBinding, RuntimeModelBinding

    for binding in (ConfiguredModelBinding, RuntimeModelBinding):
        assert not (set(binding.__dataclass_fields__) & _DESCRIPTIVE_MODEL_FIELDS), binding.__name__


def test_hosting_mode_is_closed_descriptive_metadata() -> None:
    """Hosting placement is a closed, descriptive enum — never authority.

    Added in Step 39 and refined in Step 40: exactly local/company_hosted/external,
    kept off the capability contract, and never a permission field on the binding.
    Step 40 intentionally exposes it as descriptive metadata on the read-only
    ``ModelInfo`` catalog, so it is now present there (but still not a capability
    and still absent from ``_DESCRIPTIVE_MODEL_FIELDS``).
    """
    from ava.contracts.models import ModelCapabilities, ModelHostingMode, ModelInfo
    from ava.models.bindings import ConfiguredModelBinding

    assert {mode.value for mode in ModelHostingMode} == {"local", "company_hosted", "external"}
    assert "hosting_mode" not in ModelCapabilities.model_fields
    assert "hosting_mode" in ModelInfo.model_fields
    assert "hosting_mode" not in _DESCRIPTIVE_MODEL_FIELDS
    binding_fields = set(ConfiguredModelBinding.__dataclass_fields__) & _DESCRIPTIVE_MODEL_FIELDS
    assert not binding_fields


# ============================================================
# END: Multi-Model Descriptive-Not-Authoritative Boundary Tests
# ============================================================


# ============================================================
# BEGIN: Model Registry Boundary Tests
# ============================================================


def test_model_registry_is_a_pure_catalog() -> None:
    """The Model Registry depends only on contracts/stdlib, not infrastructure.

    Step 40 introduces ``ava.models.model_registry`` as the single source of
    truth for configured models. It must stay a pure, in-process catalog: no
    provider adapters, no runtime adapters, no API/service/infrastructure, and
    no framework types.
    """
    import sys

    tree = ast.parse(MODELS_REGISTRY_FILE.read_text(encoding="utf-8"))
    for name in _top_level_imports(tree):
        assert name in {"ava", "dataclasses", "builtins"} or name in sys.stdlib_module_names, name
    for name in _ava_imports(tree):
        assert name == "ava.contracts.models", name


def test_model_qualification_store_is_harness_and_runtime_independent() -> None:
    """Step 41 metadata lookup must not consume or invoke qualification harnesses."""
    tree = ast.parse((MODELS_DIR / "qualifications.py").read_text(encoding="utf-8"))
    imported = _ava_imports(tree)
    assert "ava.runtimes.qualification" not in imported
    assert not any(name.startswith("ava.runtimes") for name in imported)
    assert not any(name.startswith("ava.models.providers") for name in imported)
    assert not any(name.startswith("ava.infrastructure") for name in imported)


def test_model_orchestrator_has_no_security_or_runtime_adapter_dependency() -> None:
    """Selection metadata cannot become a workspace/tool/security authority."""
    tree = ast.parse((SRC_DIR / "execution" / "model_orchestrator.py").read_text(encoding="utf-8"))
    imported = _ava_imports(tree)
    forbidden = (
        "ava.execution.tool_security",
        "ava.execution.model_resources",
        "ava.infrastructure.sandbox",
        "ava.workspaces",
        "ava.runtimes",
        "ava.models.providers",
    )
    assert not any(name.startswith(forbidden) for name in imported)


def test_model_resource_manager_has_no_workspace_or_security_dependency() -> None:
    """Resource lifecycle cannot become a permission or workspace authority.

    The resource manager executes an already-selected model; it must never
    select models (no orchestration/routing scope) and must stay away from
    workspace, tool, sandbox, provider-implementation, and runtime-adapter
    authority.
    """
    tree = ast.parse((SRC_DIR / "execution" / "model_resources.py").read_text(encoding="utf-8"))
    imported = _ava_imports(tree)
    forbidden = (
        "ava.execution.model_orchestrator",
        "ava.execution.routing",
        "ava.execution.tool_security",
        "ava.infrastructure.sandbox",
        "ava.workspaces",
        "ava.runtimes",
        "ava.models.providers",
    )
    assert not any(name.startswith(forbidden) for name in imported)


def test_model_registry_holds_no_operational_resource_state() -> None:
    """Declared metadata and live resource state stay separate concepts.

    ``ModelProfile``/``ModelRegistry`` describe configured models; the resource
    manager keeps its descriptors, states, leases, and capacity elsewhere. A
    registry-bound file must never reference the resource layer.
    """
    tree = ast.parse(MODELS_REGISTRY_FILE.read_text(encoding="utf-8"))
    imported = _ava_imports(tree)
    assert not any("resources" in name for name in imported)
    assert not any("leases" in name.lower() for name in imported)


def test_run_service_does_not_depend_on_model_registry() -> None:
    """Registry resolution stays below the AgentPort; RunService is unaware of it."""
    tree = ast.parse((SERVICES_DIR / "run_service.py").read_text(encoding="utf-8"))
    imported = _ava_imports(tree)
    assert not any(name == "ava.models.model_registry" for name in imported)
    assert not any(name.startswith("ava.models") for name in imported)


def test_model_discovery_route_does_not_import_concrete_providers() -> None:
    """The /models catalog route is registry/service-backed, never provider-aware."""
    tree = ast.parse((API_DIR / "routes" / "models.py").read_text(encoding="utf-8"))
    for name in _ava_imports(tree):
        assert not name.startswith("ava.models.providers"), name
        assert not name.startswith("ava.models.adapters"), name
        assert not name.startswith("ava.runtimes.adapters"), name


# ============================================================
# END: Model Registry Boundary Tests
# ============================================================


# ============================================================
# BEGIN: Persistence Repository Port Boundary Tests
# ============================================================

#: Modules a repository port must never import: vendor/framework/database.
REPOSITORY_FORBIDDEN_MODULES = FORBIDDEN_IMPORTS | {
    "aiosqlite",
    "asyncpg",
    "databases",
    "duckdb",
    "peewee",
    "psycopg",
    "psycopg2",
    "pymysql",
    "pymongo",
    "redis",
    "sqlalchemy",
    "sqlite3",
    "sqlmodel",
}


def test_repository_ports_import_no_forbidden_or_database_modules() -> None:
    """Repository ports must not import SQL/ORM/database, vendor, or framework modules."""
    violations: list[str] = []
    for path in _iter_python_files(REPOSITORIES_DIR):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for name in _top_level_imports(tree):
            if name in REPOSITORY_FORBIDDEN_MODULES:
                violations.append(f"{path}: imports '{name}'")
    assert not violations, "Forbidden imports in repository ports:\n" + "\n".join(violations)


def test_repository_ports_depend_only_on_contracts_and_each_other() -> None:
    """Repository ports use only AVA-owned types: contracts + sibling ports.

    No runtime/model/provider implementations, no FastAPI/API layer, no
    infrastructure, no services, no core. Anything else crossing the port
    boundary would leak framework or database concepts into the contract.
    """
    allowed_siblings = {"contracts", "repositories"}
    violations: list[str] = []
    for path in _iter_python_files(REPOSITORIES_DIR):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for name in _ava_imports(tree):
            parts = name.split(".")
            if (
                path.name in {"provider_connection_repository.py", "model_configuration_repository.py"}
                and parts[:2] == ["ava", "models"]
            ):
                continue
            if (
                path.name == "runtime_configuration_repository.py"
                and parts[:2] == ["ava", "runtimes"]
            ):
                continue
            if (
                path.name == "execution_defaults_repository.py"
                and parts[:2] == ["ava", "configuration"]
            ):
                continue
            if len(parts) >= 2 and parts[1] not in allowed_siblings:
                violations.append(f"{path}: imports '{name}'")
    assert not violations, "Outward imports in repository ports:\n" + "\n".join(violations)


def test_content_store_ports_stay_free_of_filesystem_stdlib() -> None:
    """Ports, contracts, and services never touch the filesystem directly.

    Step 4.14.D introduces the first physical content adapter; it lives in
    ``ava.infrastructure`` precisely so ``os`` / ``pathlib`` / ``tempfile``
    machinery never leaks into the storage-neutral ports, contracts, or
    services. The in-memory service adapter uses only ``io``.
    """
    violations: list[str] = []
    for directory in (REPOSITORIES_DIR, CONTRACTS_DIR, SERVICES_DIR):
        for path in _iter_python_files(directory):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for name in _top_level_imports(tree):
                if path.name in {"workspace_access.py", "workspace_access_service.py"}:
                    continue
                if name in {"os", "pathlib", "tempfile"}:
                    violations.append(f"{path}: imports '{name}'")
    assert not violations, "Filesystem imports outside infrastructure:\n" + "\n".join(violations)


def test_local_attachment_content_store_lives_in_infrastructure() -> None:
    """The local content adapter is an infrastructure adapter over the port."""
    from ava.infrastructure.attachment_content_store import LocalAttachmentContentStore
    from ava.repositories import AttachmentContentStore

    assert issubclass(LocalAttachmentContentStore, AttachmentContentStore)
    assert LocalAttachmentContentStore.__module__.startswith("ava.infrastructure")
    assert AttachmentContentStore.__abstractmethods__ == frozenset({"put", "open", "exists"})


def test_attachment_service_programs_against_ports_only() -> None:
    """AttachmentService depends on contracts + ports, never concrete adapters.

    Step 4.14.E keeps the orchestration slice backend-neutral: it may import
    the AVA contracts and the two ports (``AttachmentRepository``,
    ``AttachmentContentStore``) and must never name the concrete stores, the
    database layer, the local content adapter, or infrastructure. Composition
    (``create_app``) injects the port implementations.
    """
    path = SERVICES_DIR / "attachment_service.py"
    imports = _ava_imports(ast.parse(path.read_text(encoding="utf-8"), filename=str(path)))

    assert imports & {
        "ava.contracts",
        "ava.contracts.attachments",
        "ava.repositories.attachment_content_store",
        "ava.repositories.attachment_repository",
    }
    forbidden_prefixes = (
        "ava.infrastructure",
        "ava.services.attachment_content_store",
        "ava.services.attachment_store",
    )
    assert not any(name.startswith(forbidden_prefixes) for name in imports), imports


def test_attachment_transport_vocabulary_stays_in_the_api_layer() -> None:
    """FastAPI upload/multipart vocabulary never leaves the transport layer (Step 4.14.F).

    ``UploadFile`` and the FastAPI ``File``/``Form`` upload markers are
    transport concerns whose only legal home is ``ava/api``. Even the
    attachment service — which receives the uploaded bytes — consumes a plain
    ``BinaryIO`` stream, never a framework upload object. ``python-multipart``
    is FastAPI's multipart parser and is therefore a declared dependency that
    AVA source must never import directly.
    """
    transport_terms = ("UploadFile", "File(", "Form(")
    offenders: list[str] = []
    for path in sorted(SRC_DIR.rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        if not any(term in source for term in transport_terms):
            continue
        if path.is_relative_to(API_DIR):
            continue
        offenders.append(str(path.relative_to(SRC_DIR)))
    assert not offenders, offenders

    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    assert "python-multipart" in pyproject.read_text(encoding="utf-8")


def test_agent_port_remains_free_of_repository_ports() -> None:
    """The AgentPort execution contract must not know persistence ports.

    Repository adoption in Step 4.3 touches RunService and the stores only;
    the port through which run execution happens stays a pure execution
    contract. If an agent adapter ever needs persistent state beyond a run,
    it does so through its own seams, never this one.
    """
    tree = ast.parse((AGENTS_DIR / "contracts.py").read_text(encoding="utf-8"))
    assert not any(name.startswith("ava.repositories") for name in _ava_imports(tree))


def test_run_service_depends_on_repository_ports_not_concrete_stores() -> None:
    """RunService programs against repository ports; composition injects stores.

    Step 4.3 inverts the dependency: RunService may import the
    ``ava.repositories`` ports for typing and must never name the concrete
    in-memory stores (``ava.services.run_store`` / ``ava.services.run_event_store``)
    or any database/ORM layer. This is why the constructor requires injected
    repositories rather than defaulting to fresh stores.
    """
    tree = ast.parse((SERVICES_DIR / "run_service.py").read_text(encoding="utf-8"))
    imports = _ava_imports(tree)
    assert imports & {"ava.repositories", "ava.repositories.run_repository", "ava.repositories.run_event_repository"}
    forbidden = (
        "ava.services.run_store",
        "ava.services.run_event_store",
    )
    assert not any(name.startswith(forbidden) for name in imports)


def test_agent_port_dependency_survives_run_service_repository_adoption() -> None:
    """RunService keeps its AgentPort execution dependency alongside the ports."""
    tree = ast.parse((SERVICES_DIR / "run_service.py").read_text(encoding="utf-8"))
    assert "ava.agents.contracts" in _ava_imports(tree)


def test_repository_stores_conform_to_their_ports() -> None:
    """The in-memory stores explicitly implement the repository ports."""
    from ava.repositories import (
        ConversationRepository,
        DocumentRepository,
        DocumentRevisionRepository,
        MessageRepository,
        RunEventRepository,
        RunRepository,
    )
    from ava.services.conversation_store import ConversationStore
    from ava.services.document_revision_store import InMemoryDocumentRevisionStore
    from ava.services.document_store import DocumentStore
    from ava.services.message_store import MessageStore
    from ava.services.run_event_store import RunEventStore
    from ava.services.run_store import RunStore

    assert issubclass(RunStore, RunRepository)
    assert issubclass(RunEventStore, RunEventRepository)
    assert issubclass(ConversationStore, ConversationRepository)
    assert issubclass(MessageStore, MessageRepository)
    assert issubclass(DocumentStore, DocumentRepository)
    assert issubclass(InMemoryDocumentRevisionStore, DocumentRevisionRepository)


def test_conversation_service_depends_on_repository_ports_not_concrete_stores() -> None:
    """ConversationService programs against repository ports; composition injects stores.

    Step 4.4 keeps the service layer independent of persistence mechanics:
    ConversationService must import the ``ava.repositories`` ports for
    typing and must never name the concrete in-memory stores
    (``ava.services.conversation_store`` / ``ava.services.message_store``)
    or any database/ORM layer. This is why the constructor requires injected
    repositories rather than defaulting to fresh stores.
    """
    tree = ast.parse((SERVICES_DIR / "conversation_service.py").read_text(encoding="utf-8"))
    imports = _ava_imports(tree)
    assert imports & {
        "ava.repositories.conversation_repository",
        "ava.repositories.message_repository",
    }
    forbidden = (
        "ava.services.conversation_store",
        "ava.services.message_store",
    )
    assert not any(name.startswith(forbidden) for name in imports)


def test_run_service_uses_only_conversation_repository_ports_for_relationships() -> None:
    """Phase 5.19 permits stable-ID relationship validation, never services/stores."""
    tree = ast.parse((SERVICES_DIR / "run_service.py").read_text(encoding="utf-8"))
    imports = _ava_imports(tree)
    assert {
        "ava.repositories.conversation_repository",
        "ava.repositories.message_repository",
    } <= imports
    forbidden = (
        "ava.services.conversation_service",
        "ava.services.conversation_store",
        "ava.services.message_store",
    )
    assert not any(name.startswith(forbidden) for name in imports)


def test_conversation_sources_import_no_frontend_or_vendor_packages() -> None:
    """Conversation backend files import only stdlib + ava + pydantic + fastapi.

    Step 4.4 is backend-only and the conversation domain must stay usable
    from any future transport: no frontend package (``@ava/agent-ui``,
    ``@ava/contracts``), Tauri, or React-family import may appear anywhere in
    the new conversation sources. The role/status vocabulary is backend-owned
    and deliberately mirrors the frontend's string members instead.
    """
    forbidden = {"@ava", "tauri", "react", "vue", "svelte", "preact", "solid-js"}
    conversation_sources = [
        CONTRACTS_DIR / "conversations.py",
        REPOSITORIES_DIR / "conversation_repository.py",
        REPOSITORIES_DIR / "message_repository.py",
        SERVICES_DIR / "conversation_store.py",
        SERVICES_DIR / "message_store.py",
        SERVICES_DIR / "conversation_service.py",
        API_DIR / "routes" / "conversations.py",
    ]
    violations: list[str] = []
    for path in conversation_sources:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for name in _top_level_imports(tree):
            if name in forbidden:
                violations.append(f"{path}: imports '{name}'")
    assert not violations, "Forbidden imports in conversation sources:\n" + "\n".join(violations)


def test_conversation_repository_ports_import_only_contracts_and_records() -> None:
    """Conversation/message ports import only AVA contracts plus stdlib.

    The Step 4.4 ports are framework-neutral persistence contracts: their
    AVA imports must be limited to ``ava`` (for exception typing) and the
    ``ava.contracts`` vocabulary. Reuse of existing AVA port scanning
    (``ava_imports`` vs allowed siblings) is unnecessary here because the
    ports depend on exactly the contract enums and their own records.
    """
    tree = ast.parse((REPOSITORIES_DIR / "conversation_repository.py").read_text(encoding="utf-8"))
    assert _ava_sibling_imports(tree) <= {"contracts"}
    message_tree = ast.parse((REPOSITORIES_DIR / "message_repository.py").read_text(encoding="utf-8"))
    assert _ava_sibling_imports(message_tree) <= {"contracts"}


def test_document_service_depends_on_repository_port_not_concrete_store() -> None:
    """DocumentService programs against the repository port; composition injects store.

    Step 4.5 keeps the service layer independent of persistence mechanics:
    DocumentService must import the ``ava.repositories`` document port for
    typing and must never name the concrete in-memory store
    (``ava.services.document_store``) or any database/ORM layer. This is why
    the constructor requires an injected repository rather than defaulting to
    a fresh store.
    """
    tree = ast.parse((SERVICES_DIR / "document_service.py").read_text(encoding="utf-8"))
    imports = _ava_imports(tree)
    assert "ava.repositories.document_repository" in imports
    assert not any(
        name.startswith(("ava.services.document_store", "ava.infrastructure"))
        for name in imports
    )


def test_document_repository_port_imports_only_contracts_and_records() -> None:
    """The document port is framework/database neutral: contracts + its record."""
    tree = ast.parse((REPOSITORIES_DIR / "document_repository.py").read_text(encoding="utf-8"))
    assert _ava_sibling_imports(tree) <= {"contracts"}


def test_run_service_stays_free_of_document_domain() -> None:
    """RunService must not know the document domain.

    Step 4.5 introduces document persistence next to run persistence without
    coupling either: RunService keeps no imports of document repositories,
    stores, the document service, or the HTML content policy.
    """
    tree = ast.parse((SERVICES_DIR / "run_service.py").read_text(encoding="utf-8"))
    imports = _ava_imports(tree)
    forbidden = (
        "ava.repositories.document_repository",
        "ava.services.document_service",
        "ava.services.document_store",
        "ava.services.html_content_policy",
    )
    assert not any(name.startswith(forbidden) for name in imports)


def test_document_sources_import_no_frontend_or_vendor_packages() -> None:
    """Document backend files import only stdlib + ava + pydantic + fastapi.

    Step 4.5 is backend-only and the document domain must stay usable from
    any future transport: no frontend package (``@ava/*``), Tauri,
    React-family, Tiptap, or ProseMirror import may appear anywhere in the
    new document sources. Editor-neutral content is enforced by the
    ``html_content_policy`` module, which never imports the editor.
    """
    forbidden = {
        "@ava",
        "@tiptap",
        "tiptap",
        "prosemirror",
        "prosemirror-state",
        "prosemirror-view",
        "prosemirror-model",
        "prosemirror-commands",
        "react",
        "vue",
        "svelte",
        "preact",
        "solid-js",
        "tauri",
    }
    document_sources = [
        CONTRACTS_DIR / "documents.py",
        REPOSITORIES_DIR / "document_repository.py",
        SERVICES_DIR / "document_store.py",
        SERVICES_DIR / "document_service.py",
        SERVICES_DIR / "html_content_policy.py",
        API_DIR / "routes" / "documents.py",
    ]
    violations: list[str] = []
    for path in document_sources:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for name in _top_level_imports(tree):
            if name in forbidden:
                violations.append(f"{path}: imports '{name}'")
    assert not violations, "Forbidden imports in document sources:\n" + "\n".join(violations)


def test_html_content_policy_is_editor_neutral_and_stdlib_only() -> None:
    """The HTML content policy depends only on the standard library.

    Content safety cannot depend on the editor that produced the content:
    ``html_content_policy`` must import no ``ava`` modules (no services, no
    contracts) and nothing outside the standard library (only ``html``). This
    proves the sanitization boundary is AVA-owned and editor-neutral.
    """
    tree = ast.parse((SERVICES_DIR / "html_content_policy.py").read_text(encoding="utf-8"))
    assert not _ava_imports(tree)
    assert _top_level_imports(tree) <= {"html", "re"}


#: Database drivers / ORM modules that may be imported ONLY by
#: ``ava.infrastructure.persistence`` — the sanctioned database boundary.
DATABASE_MODULES = {
    "aiosqlite",
    "asyncpg",
    "databases",
    "duckdb",
    "peewee",
    "psycopg",
    "psycopg2",
    "pymysql",
    "pymongo",
    "redis",
    "sqlalchemy",
    "sqlite3",
    "sqlmodel",
}


def test_database_imports_are_confined_to_infrastructure_persistence() -> None:
    """Only ``ava.infrastructure.persistence`` may import database drivers.

    Step 4.6 introduces the first concrete relational adapter. To keep the
    repository ports, contracts, services, and API layer database-neutral, no
    file outside the persistence package may import a database driver or ORM
    module (``sqlite3``, ``sqlalchemy``, ``aiosqlite``, ``sqlmodel``, ...).
    """
    violations: list[str] = []
    for path in _iter_python_files(SRC_DIR):
        if path.is_relative_to(PERSISTENCE_DIR):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for name in _top_level_imports(tree):
            if name in DATABASE_MODULES:
                violations.append(f"{path}: imports '{name}'")
    assert not violations, "Database imports outside persistence:\n" + "\n".join(violations)


def test_services_do_not_import_database_modules() -> None:
    """The services layer programs against ports; no driver/ORM import."""
    violations: list[str] = []
    for path in _iter_python_files(SERVICES_DIR):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for name in _top_level_imports(tree):
            if name in DATABASE_MODULES:
                violations.append(f"{path}: imports '{name}'")
    assert not violations, "Database imports in services:\n" + "\n".join(violations)


def test_contracts_do_not_import_database_modules() -> None:
    """AVA contracts stay database-neutral and shareable with clients."""
    violations: list[str] = []
    for path in _iter_python_files(CONTRACTS_DIR):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for name in _top_level_imports(tree):
            if name in DATABASE_MODULES:
                violations.append(f"{path}: imports '{name}'")
    assert not violations, "Database imports in contracts:\n" + "\n".join(violations)


def test_persistence_layer_imports_only_repositories_and_contracts() -> None:
    """Adapters depend inward on the ports/contracts, never on services/core/API.

    The persistence package may import the ``ava.repositories`` ports, the
    ``ava.contracts`` vocabulary, and its own sibling modules
    (``ava.infrastructure``). Everything else — services, core, API, agents,
    models — is forbidden, and top-level imports must be stdlib plus ``ava``
    only (no third-party ORM dependencies).
    """
    import sys

    allowed_siblings = {"contracts", "infrastructure", "repositories"}
    violations: list[str] = []
    for path in _iter_python_files(PERSISTENCE_DIR):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for name in _top_level_imports(tree):
            if name != "ava" and name not in sys.stdlib_module_names:
                if (
                    path.name in {"workspace_access_repository.py", "workspace_grant_repository.py"}
                    and name == "pydantic"
                ):
                    continue
                violations.append(f"{path}: top-level import '{name}'")
        for name in _ava_sibling_imports(tree):
            if (
                path.name in {"provider_connection_repository.py", "model_configuration_repository.py"}
                and name == "models"
            ):
                continue
            if path.name == "runtime_configuration_repository.py" and name == "runtimes":
                continue
            if path.name == "execution_defaults_repository.py" and name == "configuration":
                continue
            if name not in allowed_siblings:
                violations.append(f"{path}: imports 'ava.{name}'")
    assert not violations, "Persistence layer dependency violations:\n" + "\n".join(violations)


def test_relational_repositories_conform_to_their_ports() -> None:
    """The relational adapters explicitly implement the repository ports."""
    from ava.infrastructure.persistence.repositories import (
        RelationalAttachmentRepository,
        RelationalConversationRepository,
        RelationalDocumentRepository,
        RelationalDocumentRevisionRepository,
        RelationalMessageRepository,
        RelationalProviderConnectionRepository,
        RelationalRunEventRepository,
        RelationalRunRepository,
    )
    from ava.repositories import (
        AttachmentRepository,
        ConversationRepository,
        DocumentRepository,
        DocumentRevisionRepository,
        MessageRepository,
        ProviderConnectionRepository,
        RunEventRepository,
        RunRepository,
    )

    assert issubclass(RelationalRunRepository, RunRepository)
    assert issubclass(RelationalRunEventRepository, RunEventRepository)
    assert issubclass(RelationalConversationRepository, ConversationRepository)
    assert issubclass(RelationalMessageRepository, MessageRepository)
    assert issubclass(RelationalDocumentRepository, DocumentRepository)
    assert issubclass(RelationalDocumentRevisionRepository, DocumentRevisionRepository)
    assert issubclass(RelationalAttachmentRepository, AttachmentRepository)
    assert issubclass(RelationalProviderConnectionRepository, ProviderConnectionRepository)


def test_secret_backends_are_infrastructure_only() -> None:
    """Secret material lives in infrastructure and is never imported by AVA layers.

    Phase 5.9 keeps the credential vocabulary (``SecretValue``,
    ``CredentialReference``, the ``CredentialResolver`` port) in
    ``ava.models.credentials``, but the only backend that actually touches
    secret storage belongs to infrastructure. Core, contracts, models,
    services, repositories, runtimes, and agents must not import it, so no
    domain or contract module can reach process-environment or vault state.
    """
    backend = INFRASTRUCTURE_DIR / "credentials.py"
    assert backend.exists(), "the environment credential backend must be infrastructure-side"
    for directory in (
        CORE_DIR,
        CONTRACTS_DIR,
        MODELS_DIR,
        SERVICES_DIR,
        REPOSITORIES_DIR,
        SRC_DIR / "runtimes",
        AGENTS_DIR,
    ):
        for path in _iter_python_files(directory):
            assert "infrastructure.credentials" not in path.read_text(encoding="utf-8"), path


def test_settings_routes_depend_only_on_contracts_and_services() -> None:
    """The Settings transport layer reaches no repository, domain, or adapter type.

    Settings routes are a transport shim: they translate contracts and service
    errors, and nothing else. Reaching a repository or a domain dataclass
    directly from a route would bypass the immutability, credential-reference,
    and cross-record validation the service owns.
    """
    path = API_DIR / "routes" / "settings.py"
    assert path.exists(), "the Settings API must have its own route module"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    ava_imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("ava."):
            ava_imports.add(node.module)
    allowed_prefixes = ("ava.contracts.", "ava.services.")
    for imported in ava_imports:
        assert imported.startswith(allowed_prefixes), f"settings route imports '{imported}'"
    assert "ava.contracts.settings" in ava_imports
    assert "ava.services.settings_service" in ava_imports


def test_settings_layers_import_no_runtime_or_provider_implementation() -> None:
    """Neither the Settings routes nor the Settings service touch a runtime.

    Persisted runtime configuration is a configuration record. Resolving one to
    a constructed ``AgentRuntimePort`` is execution's job (Phase 5.16), so an
    import of any runtime implementation from the Settings boundary would be
    configuration quietly acquiring execution behavior.
    """
    for path in (API_DIR / "routes" / "settings.py", SERVICES_DIR / "settings_service.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for import_path in _ava_imports(tree):
            assert not import_path.startswith("ava.runtimes.adapters"), path
            assert not import_path.startswith("ava.models.providers"), path
            assert not import_path.startswith("ava.agents.adapters"), path


def test_settings_expose_credential_reference_and_never_a_secret() -> None:
    """No Settings contract may carry resolved secret material.

    ``credential_reference`` is configuration metadata and is allowed. A field
    for an API key, token, password, or the ``SecretValue`` wrapper is not, and
    neither is a reference to that wrapper anywhere in the contract module.
    """
    import ava.contracts.settings as settings_contracts

    forbidden = {
        "api_key",
        "credential",
        "credential_value",
        "password",
        "token",
        "secret",
        "secret_value",
    }
    for name in dir(settings_contracts):
        attribute = getattr(settings_contracts, name)
        if not hasattr(attribute, "model_fields"):
            continue
        assert forbidden & set(attribute.model_fields) == set(), name
    assert "credential_reference" in settings_contracts.ProviderConnectionResponse.model_fields

    # Checked by AST rather than substring: the module docstring deliberately
    # names what is absent, and prose about an omission is not a reference to
    # the thing omitted.
    tree = ast.parse((CONTRACTS_DIR / "settings.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            assert not node.module.startswith(("ava.models", "ava.infrastructure")), node.module
        if isinstance(node, ast.Name):
            assert node.id != "SecretValue", node.id
        if isinstance(node, ast.Attribute):
            assert node.attr != "SecretValue", node.attr


def test_settings_defaults_contract_has_no_adapter_identity_field() -> None:
    """Defaults reference configured identity only, never adapter or registry keys."""
    from ava.contracts.settings import ApplicationExecutionDefaultsResponse

    assert set(ApplicationExecutionDefaultsResponse.model_fields) == {
        "default_provider_connection_id",
        "default_model_id",
        "default_runtime_configuration_id",
        "contract_version",
    }


def test_settings_service_does_not_resolve_credentials() -> None:
    """Managing configuration must never resolve a secret.

    ``SettingsService`` is on a request path. Resolving a credential there would
    put secret material in a service that returns HTTP contracts, which is
    exactly the boundary Phase 5.9 kept secret-free.
    """
    source = (SERVICES_DIR / "settings_service.py").read_text(encoding="utf-8")
    for forbidden in ("CredentialResolver", "SecretValue", "resolve_connection_credential", "reveal("):
        assert forbidden not in source, f"settings_service.py must not use {forbidden}"
    assert "CredentialReference" in source, "credential-reference syntax is still validated"


def test_settings_routes_do_not_shadow_discovery_routes() -> None:
    """``/settings/*`` is persisted configuration; discovery keeps its own paths.

    Discovery answers "what is available and healthy?" and discovery must not
    become a view of the configuration tables, nor configuration a view of the
    live registries. The path prefixes are disjoint, which is what keeps the
    two concepts separate on the wire.
    """
    for path in sorted(_iter_python_files(API_DIR / "routes")):
        if path.name in {"settings.py", "tool_features.py", "workspace_access.py"}:
            continue
        text = path.read_text(encoding="utf-8")
        assert '"/settings' not in text, f"{path.name} must not serve the Settings prefix"
    settings_text = (API_DIR / "routes" / "settings.py").read_text(encoding="utf-8")
    for discovery_path in ('"/runtimes"', '"/models"', '"/model-providers"', '"/capabilities"'):
        assert discovery_path not in settings_text, discovery_path


def test_run_service_remains_independent_of_credential_resolution() -> None:
    """``RunService → AgentPort`` must not gain a credential dependency."""
    text = (SERVICES_DIR / "run_service.py").read_text(encoding="utf-8")
    for forbidden in ("CredentialResolver", "SecretValue", "CredentialReference", "reveal("):
        assert forbidden not in text, f"run_service.py must not reference {forbidden}"


def test_persisted_configuration_declares_no_resolved_secret_column() -> None:
    """No migration may introduce a secret-bearing column for provider connections."""
    forbidden = re.compile(r"\b(credential_value|api_key|password|token|secret_value)\b\s+(TEXT|VARCHAR|BLOB)")
    versions = INFRASTRUCTURE_DIR / "persistence" / "migrations" / "versions"
    for path in _iter_python_files(versions):
        assert not forbidden.search(path.read_text(encoding="utf-8")), path


def test_runtime_configuration_adapters_conform_to_their_ports() -> None:
    """Phase 5.7's runtime-configuration adapters implement the AVA port."""
    from ava.infrastructure.persistence.repositories import RelationalRuntimeConfigurationRepository
    from ava.repositories import RuntimeConfigurationRepository
    from ava.services.runtime_configuration_store import RuntimeConfigurationStore

    assert issubclass(RelationalRuntimeConfigurationRepository, RuntimeConfigurationRepository)
    assert issubclass(RuntimeConfigurationStore, RuntimeConfigurationRepository)


def test_execution_defaults_adapters_conform_to_their_port() -> None:
    """Phase 5.8's defaults adapters implement the singular AVA port."""
    from ava.infrastructure.persistence.repositories import RelationalExecutionDefaultsRepository
    from ava.repositories import ExecutionDefaultsRepository
    from ava.services.execution_defaults_store import ExecutionDefaultsStore

    assert issubclass(RelationalExecutionDefaultsRepository, ExecutionDefaultsRepository)
    assert issubclass(ExecutionDefaultsStore, ExecutionDefaultsRepository)


def test_persistence_schema_contains_only_implemented_phase_tables() -> None:
    """The migrations contain framework tables and completed Phase 5 domains.

    The default migrations create ``runs``, ``run_events``, ``conversations``,
    ``messages``, ``documents`` (Step 4.7), ``document_revisions``
    (Step 4.13.C's immutable revision history), and ``attachments`` +
    ``idx_attachments_owner`` (Step 4.14.C's attachment metadata), and
    Phase 6.8's approval records and Phase 6.13's durable tool invocation
    lifecycle. Unimplemented later-phase vocabulary may not
    leak into the schema, and schema text may live only
    in the migrations package. ``attachment`` became legitimate with Step
    4.14.C, so its schema vocabulary is no longer forbidden. Later audit,
    model-invocation, and qualification concepts remain excluded.
    """
    migration_dir = PERSISTENCE_DIR / "migrations" / "versions"
    created: list[str] = []
    for path in _iter_python_files(migration_dir):
        text = path.read_text(encoding="utf-8")
        created.extend(re.findall(r"CREATE TABLE (?:IF NOT EXISTS )?(\w+)", text))
        created.extend(re.findall(r"CREATE (?:UNIQUE )?INDEX (\w+)", text))
    # Migration 23 rebuilds Project-file metadata through a transaction-local
    # table and recreates an existing index; neither adds another final object.
    created = sorted(set(created) - {"IF", "project_files_new"})
    assert created == [
        "application_execution_defaults",
        "approval_records",
        "approval_records_pending_run",
        "approval_records_pending_workspace",
        "attachments",
        "conversation_context_summaries",
        "conversation_folders",
        "conversations",
        "core_prompt_assignments",
        "core_prompts",
        "document_revisions",
        "documents",
        "idx_attachments_owner",
        "idx_conversation_folders_name",
        "idx_conversations_project",
        "idx_messages_conversation_order",
        "idx_project_files_project_id",
        "idx_run_events_one_terminal",
        "idx_runs_assistant_message",
        "idx_runs_cancellation_requested",
        "idx_runs_conversation",
        "idx_runs_source_user_message",
        "ix_core_prompt_assignments_prompt_order",
        "ix_core_prompt_assignments_scope_order",
        "ix_runs_owner_conversation_created",
        "ix_tool_invocation_reservations_run_created",
        "ix_tool_invocation_reservations_state",
        "ix_workspace_access_grants_principal",
        "ix_workspace_access_grants_workspace",
        "messages",
        "model_configurations",
        "project_files",
        "projects",
        "provider_connections",
        "run_events",
        "runs",
        "runtime_configurations",
        "tool_feature_configuration",
        "tool_invocation_reservations",
        "ux_core_prompt_assignment_global",
        "ux_core_prompt_assignment_target",
        "ux_project_files_project_normalized_name",
        "ux_workspace_access_grants_active_scope",
        "workspace_access_configurations",
        "workspace_access_grants",
    ]
    forbidden = ("audit", "model_invocation", "qualification")
    for path in _iter_python_files(PERSISTENCE_DIR / "migrations"):
        text = path.read_text(encoding="utf-8")
        for word in forbidden:
            assert word not in text, f"forbidden later-phase vocabulary in {path}: {word}"


def test_schema_creation_is_owned_by_the_migration_system() -> None:
    """CREATE statements live only in the migrations package (Step 4.7).

    The migration system is the single authoritative schema owner: no adapter,
    database-lifecycle module, composition seam, or settings code may embed
    ``CREATE TABLE``/``CREATE INDEX`` DDL.
    """
    violations: list[str] = []
    creation_dirs = {PERSISTENCE_DIR / "migrations"}
    ddl_pattern = re.compile(r"\bCREATE\s+(TABLE|UNIQUE\s+INDEX|INDEX)\b")
    for path in _iter_python_files(PERSISTENCE_DIR):
        if any(path.is_relative_to(directory) for directory in creation_dirs):
            continue
        if ddl_pattern.search(path.read_text(encoding="utf-8")):
            violations.append(str(path))
    assert not violations, f"Schema DDL outside the migration system: {violations}"


def test_migrations_are_confined_to_infrastructure_persistence() -> None:
    """Only the persistence package may import the migration system.

    Repository ports, contracts, services, API, core, agents, and configuration
    must never see the migration module.
    """
    violations: list[str] = []
    for path in _iter_python_files(SRC_DIR):
        if path.is_relative_to(PERSISTENCE_DIR):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for import_path in _ava_imports(tree):
            if import_path.startswith("ava.infrastructure.persistence.migrations"):
                violations.append(f"{path}: imports '{import_path}'")
    assert not violations, "Migration imports outside infrastructure persistence:\n" + "\n".join(
        violations
    )


def test_ports_services_and_contracts_never_name_the_migration_system() -> None:
    """The five repository ports and their consumers stay migration-unaware."""
    violations: list[str] = []
    for directory in (REPOSITORIES_DIR, SERVICES_DIR, CONTRACTS_DIR):
        for path in _iter_python_files(directory):
            text = path.read_text(encoding="utf-8")
            if "migrations" in text:
                violations.append(f"{path}: mentions the migration system")
    assert not violations, "Migration vocabulary in ports/services/contracts:\n" + "\n".join(
        violations
    )


def test_schema_metadata_table_is_infrastructure_only() -> None:
    """``ava_schema_migrations`` appears only inside infrastructure persistence."""
    violations: list[str] = []
    for path in _iter_python_files(SRC_DIR):
        text = path.read_text(encoding="utf-8")
        if "ava_schema_migrations" in text and not path.is_relative_to(PERSISTENCE_DIR):
            violations.append(str(path))
    assert not violations, f"Metadata table named outside infrastructure persistence: {violations}"


def test_default_persistence_provider_remains_the_in_memory_stores() -> None:
    """The unconfigured production default stays ``memory`` (Step 4.7 unchanged)."""
    text = (CONFIGURATION_DIR / "settings.py").read_text(encoding="utf-8")
    assert '"AVA_PERSISTENCE", "memory"' in text, "default persistence provider must be memory"


def test_application_persistence_selection_is_localized_to_composition() -> None:
    """The application-persistence selector lives in composition; API consumes ports.

    Steps 4.8/4.9 activate run/run-event/conversation/message persistence by
    composing ``create_application_persistence`` in
    ``ava.infrastructure.composition``. The API
    factory must reach the selected implementation only through that seam —
    never the concrete stores, never the relational adapters directly. Because
    ``ava.services`` may not be imported from the persistence package, the
    selector (which needs both the in-memory stores and the relational
    bundles) must live in composition, not in ``ava.infrastructure.persistence``.
    """
    composition_source = INFRASTRUCTURE_DIR / "composition.py"
    source = composition_source.read_text(encoding="utf-8")
    assert "class ApplicationPersistence" in source
    assert "def create_application_persistence" in source
    assert "def create_relational_repositories" not in source

    app_tree = ast.parse((API_DIR / "app.py").read_text(encoding="utf-8"))
    imports = _ava_imports(app_tree)
    assert "ava.infrastructure.composition" in imports
    forbidden = (
        "ava.services.run_store",
        "ava.services.run_event_store",
        "ava.services.conversation_store",
        "ava.services.message_store",
        "ava.services.document_store",
        "ava.infrastructure.persistence.repositories",
    )
    assert not any(name.startswith(forbidden) for name in imports)
    app_text = (API_DIR / "app.py").read_text(encoding="utf-8")
    assert "create_application_persistence(" in app_text


def test_relational_adapters_are_constructed_only_inside_the_persistence_package() -> None:
    """Concrete relational adapters stay confined to their persistence package.

    Only ``ava.infrastructure.persistence.composition`` may import the
    concrete ``Relational*`` adapter modules; only the infrastructure
    composition seam may import the top-level persistence package. Services,
    contracts, ports, routes, and the API factory never name the relational
    implementation or the persistence package.
    """
    violations: list[str] = []
    for path in _iter_python_files(SRC_DIR):
        if path.is_relative_to(PERSISTENCE_DIR):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for import_path in _ava_imports(tree):
            if import_path.startswith("ava.infrastructure.persistence.repositories"):
                violations.append(f"{path}: imports '{import_path}'")
            if (
                import_path == "ava.infrastructure.persistence"
                or import_path.startswith("ava.infrastructure.persistence.")
            ) and path != INFRASTRUCTURE_DIR / "composition.py":
                violations.append(f"{path}: imports '{import_path}'")
    assert not violations, "Relational adapter imports outside persistence:\n" + "\n".join(
        violations
    )


def test_application_persistence_carries_all_activated_ports() -> None:
    """ApplicationPersistence selects every implemented durable domain port.

    ``ApplicationPersistence`` carries run, run-event, conversation, message,
    provider-connection,
    and document state plus the Step 4.13 document revision history repository,
    the Step 4.14.C attachment metadata repository, the Phase 6.8 approval
    repository, the durable tool invocation lifecycle port, and the document write
    coordinator. The API factory receives only the composed ports, never
    concrete stores.
    """
    fields = _collect_annotated_fields(
        INFRASTRUCTURE_DIR / "composition.py", "ApplicationPersistence"
    )
    assert fields == {
        "run_repository",
        "run_event_repository",
        "conversation_repository",
        "message_repository",
        "model_configuration_repository",
        "provider_connection_repository",
        "runtime_configuration_repository",
        "execution_defaults_repository",
        "document_repository",
        "document_revision_repository",
        "attachment_repository",
        "conversation_folder_repository",
        "core_prompt_assignment_repository",
        "core_prompt_repository",
        "document_write_coordinator",
        "database",
        "project_repository",
        "project_file_repository",
        "context_summary_repository",
        "tool_feature_repository",
        "workspace_access_repository",
        "workspace_grant_repository",
        "approval_repository",
        "invocation_reservation_repository",
    }

    app_text = (API_DIR / "app.py").read_text(encoding="utf-8")
    assert "application_persistence.conversation_repository" in app_text
    assert "application_persistence.message_repository" in app_text
    assert "application_persistence.document_repository" in app_text

    composition_text = (INFRASTRUCTURE_DIR / "composition.py").read_text(encoding="utf-8")
    assert "conversation_repository=bundle.conversation_repository" in composition_text
    assert "message_repository=bundle.message_repository" in composition_text
    assert "model_configuration_repository=bundle.model_configuration_repository" in composition_text
    assert "provider_connection_repository=bundle.provider_connection_repository" in composition_text
    assert "runtime_configuration_repository=bundle.runtime_configuration_repository" in composition_text
    assert "execution_defaults_repository=bundle.execution_defaults_repository" in composition_text
    assert "document_repository=bundle.document_repository" in composition_text
    assert "document_revision_repository=bundle.document_revision_repository" in composition_text
    assert "attachment_repository=bundle.attachment_repository" in composition_text
    assert "document_write_coordinator=bundle.document_write_coordinator" in composition_text


def test_conversation_routes_remain_persistence_neutral() -> None:
    """Conversation routes use the service and never name persistence details."""
    route_tree = ast.parse((API_DIR / "routes" / "conversations.py").read_text(encoding="utf-8"))
    imports = _ava_imports(route_tree)
    assert "ava.services.conversation_service" in imports
    forbidden = (
        "ava.repositories",
        "ava.infrastructure.persistence",
        "ava.services.conversation_store",
        "ava.services.message_store",
    )
    assert not any(name.startswith(forbidden) for name in imports)


def test_migration_versions_include_all_completed_phase_five_domains() -> None:
    """The migration ledger includes all completed Phase 4/5 schema work.

    Steps 4.8/4.9/4.10/4.11/4.12 activate existing schema only — no migrations
    are added — Step 4.13.C adds exactly one (the document revision history,
    v0002), and Step 4.14.C adds exactly one more (the attachment metadata
    table, v0003); Phase 5.3 adds provider connections (v0004), Phase 5.5
    adds model configurations (v0005), Phase 5.7 adds runtime
    configurations (v0006), and Phase 5.8 adds application execution
    defaults (v0007), Phase 5.19 adds durable run relationship ids (v0008),
    and Phase 6.13 adds durable tool invocation reservations (v0028).
    """
    version_files = sorted(
        path.name
        for path in (PERSISTENCE_DIR / "migrations" / "versions").iterdir()
        if re.match(r"v\d{4}_.*\.py", path.name)
    )
    assert version_files == [
        "v0001_initial_schema.py",
        "v0002_document_revisions.py",
        "v0003_attachments.py",
        "v0004_provider_connections.py",
        "v0005_model_configurations.py",
        "v0006_runtime_configurations.py",
        "v0007_application_execution_defaults.py",
        "v0008_run_conversation_relationships.py",
        "v0009_run_cancellation_request.py",
        "v0010_conversation_organization_metadata.py",
        "v0011_conversation_folders.py",
        "v0012_projects.py",
        "v0013_conversation_project_relationship.py",
        "v0014_conversation_project_index.py",
        "v0015_core_prompts.py",
        "v0016_core_prompt_assignments.py",
        "v0017_project_execution_defaults.py",
        "v0018_project_files.py",
        "v0019_conversation_title_ownership.py",
        "v0020_run_inspection.py",
        "v0021_model_context_window.py",
        "v0022_conversation_context_summaries.py",
        "v0023_project_file_name_uniqueness.py",
        "v0024_tool_features.py",
        "v0025_workspace_access.py",
        "v0026_approvals.py",
        "v0027_run_execution_mode.py",
        "v0028_tool_invocation_reservations.py",
        "v0029_trusted_execution_authority.py",
    ], (
        "unexpected migration version files; found versions: "
        + ", ".join(version_files)
    )


def _collect_annotated_fields(path: Path, class_name: str) -> set[str]:
    """Return the annotated field names declared on a dataclass body."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            fields: set[str] = set()
            for item in node.body:
                if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                    fields.add(item.target.id)
            return fields
    raise AssertionError(f"{path} does not define class {class_name}")


# ============================================================
# END: Persistence Repository Port Boundary Tests
# ============================================================


# ============================================================
# BEGIN: Step 4.13 Document Revision Boundary Tests
# ============================================================


def _public_methods(tree: ast.Module, class_name: str) -> set[str]:
    """Collect the names of public methods declared on the named class."""
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            return {
                item.name
                for item in node.body
                if isinstance(item, ast.FunctionDef) and not item.name.startswith("_")
            }
    raise AssertionError(f"{class_name} not found")


def test_document_revision_repository_port_is_append_only() -> None:
    """The revision port exposes append/read only; no history mutation methods.

    Step 4.13 keeps ``DocumentRevisionRepository`` immutable: the port may
    append and read (``list_for_document``/``get``/``get_latest``) but must
    never expose update/replace/rename/delete/save/restore/revert. History
    mutation or a later restore that rewrites history would break the
    current-vs-history ownership split.
    """
    path = REPOSITORIES_DIR / "document_revision_repository.py"
    methods = _public_methods(
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path)),
        "DocumentRevisionRepository",
    )
    assert methods == {"append", "get", "get_latest", "list_for_document"}, methods


def test_document_repository_port_stays_revision_free() -> None:
    """The current-document port contains no revision/history behavior.

    Step 4.13's ownership split keeps ``DocumentRepository`` current-state
    only: the port exposes create/get/list/update_title/update_content and no
    revision or history naming. If a method name or record field carried
    revision vocabulary, history would have leaked into the durable current
    state.
    """
    path = REPOSITORIES_DIR / "document_repository.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    methods = _public_methods(tree, "DocumentRepository")
    assert methods == {"create", "get", "list", "update_content", "update_title"}, methods
    for record in tree.body:
        if isinstance(record, ast.ClassDef) and record.name == "DocumentRecord":
            fields = {
                item.target.id
                for item in record.body
                if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name)
            }
            assert not any("revision" in field for field in fields), fields


# ============================================================
# END: Step 4.13 Document Revision Boundary Tests
# ============================================================


def test_execution_configuration_repository_fanout_stays_in_resolver() -> None:
    """Selection and execution consume a resolution port, never four stores."""
    forbidden = {
        "ava.repositories.execution_defaults_repository",
        "ava.repositories.provider_connection_repository",
        "ava.repositories.model_configuration_repository",
        "ava.repositories.runtime_configuration_repository",
    }
    for relative in (
        "services/run_service.py", "agents/contracts.py", "agents/adapters/native/native_agent.py",
        "execution/selector.py", "execution/persisted_execution.py",
    ):
        tree = ast.parse((SRC_DIR / relative).read_text())
        assert not (set(_ava_imports(tree)) & forbidden), relative
        names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
        assert not names & {
            "ExecutionDefaultsRepository", "ProviderConnectionRepository", "ModelConfigurationRepository",
            "RuntimeConfigurationRepository", "CredentialResolver", "SecretValue",
        }, relative
    resolver = ast.parse((SRC_DIR / "execution/configuration_resolver.py").read_text())
    assert forbidden <= set(_ava_imports(resolver))
    for imported in _ava_imports(resolver):
        assert not imported.startswith(("ava.infrastructure", "ava.models.providers", "ava.runtimes.adapters"))
    calls = {
        node.func.attr for node in ast.walk(resolver)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert not calls & {"generate", "execute", "acquire", "load", "reveal"}


def test_settings_remain_independent_of_execution_resolution() -> None:
    for relative in ("api/routes/settings.py", "services/settings_service.py", "contracts/settings.py"):
        tree = ast.parse((SRC_DIR / relative).read_text())
        assert not any(name.startswith("ava.execution") for name in _ava_imports(tree))


def test_configuration_records_remain_sdk_free() -> None:
    for relative in ("models/model_configurations.py", "runtimes/configurations.py"):
        tree = ast.parse((SRC_DIR / relative).read_text())
        assert all(name.startswith("ava.contracts") for name in _ava_imports(tree))


def test_execution_results_hide_ports_and_runtime_binding_hides_secret() -> None:
    from dataclasses import fields

    from ava.execution.persisted_execution import PersistedExecutionConfiguration
    from ava.execution.selector import ResolvedExecution
    from ava.models.bindings import RuntimeModelBinding

    for result in (PersistedExecutionConfiguration, ResolvedExecution):
        shape = {field.name: field for field in fields(result)}
        assert not shape["model_provider"].repr
        assert not shape["runtime"].repr
        assert not {"api_key", "credential", "secret_value"} & shape.keys()
    assert not next(field for field in fields(RuntimeModelBinding) if field.name == "api_key").repr


def test_run_and_event_contracts_gain_no_credential_fields() -> None:
    from ava.agents.contracts import AgentRunResult
    from ava.contracts.events import RunEvent
    from ava.contracts.execution import RunExecutionSelection
    from ava.contracts.responses import RunResponse

    forbidden = {"api_key", "credential", "credential_reference", "secret_value", "endpoint", "model_provider"}
    for contract in (AgentRunResult, RunEvent, RunExecutionSelection, RunResponse):
        assert not forbidden & contract.model_fields.keys()


def test_bootstrap_stays_in_composition_and_out_of_execution_domains() -> None:
    for relative in (
        "services/run_service.py", "agents/contracts.py", "models/model_configurations.py",
        "models/provider_connections.py", "runtimes/configurations.py", "runtimes/registry.py",
        "configuration/execution_defaults.py", "api/routes/settings.py",
    ):
        tree = ast.parse((SRC_DIR / relative).read_text())
        imports = set(_ava_imports(tree))
        assert "ava.configuration.settings" not in imports, relative
        assert "ava.infrastructure.configuration_bootstrap" not in imports, relative
    source = (INFRASTRUCTURE_DIR / "configuration_bootstrap.py").read_text()
    assert "uuid" not in source
    assert "credential_reference=None" in source
    tree = ast.parse(source)
    assert not any(name.startswith("ava.infrastructure.persistence") for name in _ava_imports(tree))


def test_frontend_does_not_read_execution_environment() -> None:
    frontend = SRC_DIR.parents[2] / "frontend" / "packages"
    assert frontend.is_dir()
    for package in ("workspace", "settings-core", "agent-ui"):
        for path in (frontend / package / "src").rglob("*"):
            if path.suffix not in {".ts", ".tsx"} or ".test." in path.name:
                continue
            source = path.read_text(encoding="utf-8")
            assert not any(name in source for name in (
                "AVA_AGENT_RUNTIME", "AVA_MODEL_PROVIDER", "AVA_MODEL_NAME", "AVA_MODEL_ID",
                "AVA_MODEL_HOSTING_MODE", "AVA_LOCAL_MODEL_BASE_URL",
            )), path


# ============================================================
# BEGIN: Execution Context Boundary Tests
# ============================================================


def test_context_construction_service_depends_only_on_contracts_and_repositories() -> None:
    """Context construction is a pure policy over durable records.

    The service answers "which messages may this run send?" from repository
    ports and the neutral contract vocabulary only. It may not reach agents,
    runtimes, models, providers, the API, or infrastructure, so no execution
    or transport concern can leak into the context policy.
    """
    file = SERVICES_DIR / "context_construction_service.py"
    allowed_prefixes = ("ava.contracts", "ava.repositories")
    violations: list[str] = []
    for import_path in _ava_imports(ast.parse(file.read_text(encoding="utf-8"))):
        if not import_path.startswith(allowed_prefixes):
            violations.append(f"{file}: imports '{import_path}'")
    assert not violations, "Context construction outside contracts/repositories:\n" + "\n".join(violations)


def test_runtimes_and_adapters_must_not_read_persistence_or_services() -> None:
    """A runtime receives context; it never assembles or queries it.

    Agent adapters and runtimes may import contracts, ports, and execution
    policy, but never conversation/message/run repositories or the services
    that own them. This keeps a second, runtime-specific transcript policy from
    being possible at all.
    """
    forbidden = (
        "ava.repositories",
        "ava.services",
        "ava.api",
        "ava.infrastructure",
    )
    violations: list[str] = []
    for directory in (AGENTS_DIR, SRC_DIR / "runtimes"):
        for path in _iter_python_files(directory):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for import_path in _ava_imports(tree):
                if import_path.startswith(forbidden):
                    violations.append(f"{path}: imports '{import_path}'")
    assert not violations, "Persistence or service imports in execution layers:\n" + "\n".join(violations)


def test_run_service_delegates_context_construction() -> None:
    """RunService consumes the context capability, never building history.

    The run lifecycle service may hold the context service and forward its
    result, but it must not read message records to assemble a transcript, and
    it must not import the runtimes that will consume the context.
    """
    file = SERVICES_DIR / "run_service.py"
    tree = ast.parse(file.read_text(encoding="utf-8"))
    for import_path in _ava_imports(tree):
        assert not import_path.startswith("ava.runtimes"), import_path
    source = file.read_text(encoding="utf-8")
    assert "_message_repository.list_for_conversation" not in source
    assert "_conversation_repository.list_for_conversation" not in source
    assert "ava.services.context_construction_service" in _ava_imports(tree)


def test_execution_context_contracts_stay_free_of_sdks_and_persistence() -> None:
    """The neutral context vocabulary is a leaf contract.

    ``ContextMessage``/``RunContext`` cross the agent, runtime, and service
    boundaries, so they must carry no vendor SDK, transport, or persistence
    type.
    """
    file = CONTRACTS_DIR / "conversations.py"
    tree = ast.parse(file.read_text(encoding="utf-8"))
    for import_path in _ava_imports(tree):
        assert import_path.startswith("ava.contracts") or import_path == "ava.workspaces.contracts", import_path
    for name in _top_level_imports(tree):
        assert name not in FORBIDDEN_IMPORTS, name


# ============================================================
# END: Execution Context Boundary Tests
# ============================================================
# ============================================================
# BEGIN: Context Window Boundary Tests
# ============================================================


def test_context_window_manager_depends_only_on_neutral_contracts() -> None:
    """The window policy is a pure function of messages and a limit.

    A tokenizer, provider, runtime, or repository would make the budget depend
    on I/O or on a specific model's vocabulary, which is exactly the coupling
    this module exists to avoid. Only neutral message/attachment context
    contracts and the standard library are allowed in.
    """
    file = EXECUTION_DIR / "context_window.py"
    tree = ast.parse(file.read_text(encoding="utf-8"))
    for import_path in _ava_imports(tree):
        assert import_path in {
            "ava.contracts.conversations", "ava.contracts.attachment_context",
        }, import_path
    for name in _top_level_imports(tree):
        assert name not in FORBIDDEN_IMPORTS, name


def test_context_windowing_depends_on_no_provider_or_runtime() -> None:
    """The limit arrives as data; AVA never discovers a model window itself.

    The manager sees only the limit it is handed. The agent adapter may hold
    the resolved execution — that is where a limit legitimately enters — but it
    may not reach for a concrete provider implementation or a model registry,
    so the window can only come from the already-selected model.
    """
    for import_path in _ava_imports(
        ast.parse((EXECUTION_DIR / "context_window.py").read_text(encoding="utf-8"))
    ):
        assert not import_path.startswith(("ava.models", "ava.infrastructure")), import_path
    agent = AGENTS_DIR / "adapters" / "native" / "native_agent.py"
    for import_path in _ava_imports(ast.parse(agent.read_text(encoding="utf-8"))):
        assert not import_path.startswith(
            ("ava.infrastructure", "ava.models.registry")
        ), f"{agent}: windowing must not discover model metadata: {import_path}"


def test_runtimes_never_import_the_context_window_manager() -> None:
    """Windowing happens once, above the runtime boundary.

    If a runtime could import the manager it could trim independently, and the
    two runtimes would send different histories for the same conversation. The
    guard makes a second trimming site impossible rather than merely unused.
    """
    for path in _iter_python_files(SRC_DIR / "runtimes"):
        for import_path in _ava_imports(ast.parse(path.read_text(encoding="utf-8"))):
            assert import_path != "ava.execution.context_window", (
                f"{path}: runtime-level windowing would diverge between runtimes: {import_path}"
            )


def test_context_window_lives_outside_the_service_layer() -> None:
    """The window policy is execution policy, not a lifecycle service.

    Placing it in ``ava.services`` would make it reachable from the run
    lifecycle and would let context assembly depend on execution, reversing the
    Phase 5.21 direction. ``ava.execution`` is the only home that keeps
    construction upstream of windowing.
    """
    assert (EXECUTION_DIR / "context_window.py").exists()
    assert not list(SERVICES_DIR.glob("*context_window*"))
    assert not list(CONTRACTS_DIR.glob("*context_window*"))


# ============================================================
# END: Context Window Boundary Tests
# ============================================================
# ============================================================
# BEGIN: Run Lifecycle Authority Tests
# ============================================================


def _called_attribute_names(tree: ast.Module, attribute: str) -> set[str]:
    """Collect the source files that call ``<something>.<attribute>(...)``."""
    files: set[str] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == attribute
        ):
            files.add(getattr(node.func.value, "id", ""))
    return files


def test_only_the_lifecycle_authority_writes_run_status() -> None:
    """Exactly one production path may change a run's durable status.

    Phase 5.23 moved the transition rules out of ``RunService`` and into
    ``RunLifecycleService``. If a second caller could reach
    ``RunRepository.update_status`` the state machine would stop being
    enforceable: a caller could move a completed run back to running and no
    test of the table would notice. The repository keeps the primitive, because
    the primitive is what the lifecycle authority uses.
    """
    allowed = {
        "run_lifecycle_service.py",
        # Persistence adapters and the in-memory store implement the port.
        "run_repository.py",
        "run_store.py",
    }
    violations: list[str] = []
    for path in _iter_python_files(SRC_DIR):
        if path.name in allowed:
            continue
        if "update_status" in _called_attribute_names(
            ast.parse(path.read_text(encoding="utf-8")), "update_status"
        ):
            violations.append(str(path.relative_to(SRC_DIR)))
    assert not violations, (
        "run status may only be written by the lifecycle authority:\n"
        + "\n".join(violations)
    )


def test_only_the_lifecycle_authority_guards_a_run_status_write() -> None:
    """The compare-and-swap is as centralized as the plain write.

    A guarded write anywhere else would be a second race-resolution policy, and
    the two could disagree about which writer wins.
    """
    allowed = {
        "run_lifecycle_service.py",
        "run_repository.py",
        "run_store.py",
    }
    violations: list[str] = []
    for path in _iter_python_files(SRC_DIR):
        if path.name in allowed:
            continue
        if "compare_and_set_status" in _called_attribute_names(
            ast.parse(path.read_text(encoding="utf-8")), "compare_and_set_status"
        ):
            violations.append(str(path.relative_to(SRC_DIR)))
    assert not violations, (
        "guarded run status writes belong to the lifecycle authority:\n"
        + "\n".join(violations)
    )


def test_the_run_service_holds_no_transition_policy() -> None:
    """``RunService`` coordinates a run; it does not decide what a run may become.

    The service legitimately still *asks* for a state — it cannot orchestrate an
    execution without saying "start" and "complete" — and it may read the shared
    ``is_terminal`` classification. What it must not own is a rule: a local
    table or status collection, its own transition helpers, or a hand-written
    legality check. Any of those would be a second state machine that could
    drift from the authority.
    """
    path = SERVICES_DIR / "run_service.py"
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)

    assert "ava.services.run_lifecycle_service" in _ava_imports(tree)
    for token in ("ALLOWED_TRANSITIONS", "LIFECYCLE_EVENT_FOR_STATUS"):
        assert token not in source, f"RunService must not restate the {token} table"

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in {
            "start",
            "complete",
            "fail",
            "cancel",
            "transition",
        }:
            assert node.name not in {"start", "complete"}, (
                f"RunService defines its own {node.name}(): transitions belong to the authority"
            )
        if isinstance(node, (ast.Set, ast.Dict, ast.List, ast.Tuple)):
            statuses = {
                element.attr
                for element in ast.walk(node)
                if isinstance(element, ast.Attribute)
                and isinstance(element.value, ast.Name)
                and element.value.id == "RunStatus"
            }
            assert len(statuses) < 2, (
                f"RunService line {node.lineno} collects {sorted(statuses)}: "
                "a local status set is a second state machine"
            )


def _calls_attribute(tree: ast.Module, attribute: str) -> bool:
    """Whether the module calls ``<anything>.<attribute>(...)`` anywhere.

    ``_called_attribute_names`` answers a different question: it reports the
    *receivers* of such calls, so testing an attribute name against its result
    is always false. This returns the answer these guards actually need.
    """
    return any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == attribute
        for node in ast.walk(tree)
    )


def _imports_symbol(tree: ast.Module, symbol: str) -> bool:
    """Whether the module imports a named symbol from anywhere in ``ava``."""
    return any(name == symbol for name in _ava_imports(tree)) or any(
        (node.module or "").startswith("ava") and symbol in {a.name for a in node.names}
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    )


def test_agents_and_runtimes_cannot_reach_the_lifecycle_authority() -> None:
    """Only orchestration may settle a run.

    An agent adapter or runtime reports an *outcome*; letting either import the
    lifecycle authority would let execution code invent durable state, and the
    two runtimes or a future adapter could settle the same run differently.

    The application factory is the one API-layer exception: it is composition
    root, not request handling, and Phase 5.30 required it to hold the authority
    so cold-start reconciliation can settle stranded runs before readiness. A
    *route* must still never import it -- an HTTP handler that settles a run
    would be a second place where lifecycle policy is decided.
    """
    composition_roots = {"app.py"}
    for directory in (AGENTS_DIR, SRC_DIR / "runtimes", API_DIR):
        for path in _iter_python_files(directory):
            if directory == API_DIR and path.name in composition_roots:
                continue
            for import_path in _ava_imports(ast.parse(path.read_text(encoding="utf-8"))):
                assert import_path != "ava.services.run_lifecycle_service", (
                    f"{path}: only orchestration may move a run's durable state: {import_path}"
                )


def test_cold_start_recovery_delegates_every_settlement_to_the_authority() -> None:
    """Recovery converges state; it must not own a second way to settle a run.

    ``RunRecoveryService`` decides *which* runs are stranded, but the actual
    status write and lifecycle fact belong to ``RunLifecycleService``. A direct
    ``update_status`` or ``compare_and_set_status`` call would give recovery a
    private path around the authority and its guards.
    """
    path = SERVICES_DIR / "run_recovery_service.py"
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)

    assert "ava.services.run_lifecycle_service" in _ava_imports(tree)
    for method in ("update_status", "compare_and_set_status", "request_cancellation"):
        assert not _calls_attribute(tree, method), (
            f"recovery must not call {method}(): the lifecycle authority owns run state writes"
        )
    # Recovery asks which runs are active; it must not keep its own status set.
    assert not _imports_symbol(tree, "RunStatus"), (
        "recovery reads active runs through RunRepository.list_active, not its own status set"
    )


def test_repositories_stay_blind_persistence() -> None:
    """A repository stores a status; it never decides whether one is legal.

    Lifecycle legality lives in the authority. If a repository refused an
    illegal transition it would be enforcing a rule it does not own, and the
    same rule would have to be written again for every future storage backend.
    """
    forbidden = ("ALLOWED_TRANSITIONS", "LIFECYCLE_EVENT_FOR_STATUS", "is_terminal")
    paths = [
        *_iter_python_files(REPOSITORIES_DIR),
        *_iter_python_files(PERSISTENCE_DIR),
        SERVICES_DIR / "run_store.py",
    ]
    for path in paths:
        source = path.read_text(encoding="utf-8")
        for token in forbidden:
            assert token not in source, (
                f"{path}: repositories stay blind, so they must not encode lifecycle rules ({token})"
            )


def test_lifecycle_events_are_facts_not_authority() -> None:
    """A run's status is read from the run, never reconstructed from its events.

    The lifecycle appends its event *after* the status write, so events describe
    transitions rather than grant them. A reader that rebuilt a status from the
    event log would make the log authoritative and invert the guarantee the
    ordering exists to provide.
    """
    for path in _iter_python_files(SRC_DIR):
        if path.name in {"run_lifecycle_service.py", "run_event_repository.py", "run_event_store.py"}:
            continue
        source = path.read_text(encoding="utf-8")
        assert "def status_from_events" not in source, path
        assert "def current_status_from_events" not in source, path


# ============================================================
# END: Run Lifecycle Authority Tests
# ============================================================


def test_cancellation_intent_is_not_a_lifecycle_status() -> None:
    from ava.contracts.events import EventType
    from ava.contracts.responses import RunStatus
    from ava.repositories.run_event_repository import TERMINAL_EVENT_TYPES

    assert set(RunStatus) == {
        RunStatus.PENDING, RunStatus.RUNNING, RunStatus.WAITING_FOR_APPROVAL,
        RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED,
    }
    assert EventType.RUN_CANCEL_REQUESTED not in TERMINAL_EVENT_TYPES


def test_cancellation_intent_writes_stay_at_the_lifecycle_boundary() -> None:
    for path in _iter_python_files(SRC_DIR):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "request_cancellation"):
                assert path.name in {"run_service.py", "run_lifecycle_service.py"}, path
    # Startup and execution adapters must not interpret intent as an outcome.
    for directory in (AGENTS_DIR, SRC_DIR / "runtimes"):
        for path in _iter_python_files(directory):
            assert "cancellation_requested_at" not in path.read_text(encoding="utf-8"), path
    assert "request_cancellation" not in (API_DIR / "app.py").read_text(encoding="utf-8")


def test_stream_route_is_an_event_observer_not_a_lifecycle_writer() -> None:
    """SSE may read persisted facts but cannot mutate a run because of I/O."""
    source = (API_DIR / "routes" / "runs.py").read_text(encoding="utf-8")
    stream_start = source.index("async def stream_run")
    stream_end = source.index(
        "# ============================================================\n# END: Stream Run Events"
    )
    stream_source = source[stream_start:stream_end]
    for forbidden in ("cancel_run(", "prepare_run(", "execute_prepared_run(", "_lifecycle"):
        assert forbidden not in stream_source, forbidden


def test_stream_contract_has_no_provider_or_runtime_dependency() -> None:
    """The transport envelope stays in the leaf contracts package."""
    source = (CONTRACTS_DIR / "events.py").read_text(encoding="utf-8")
    for forbidden in ("provider", "runtime", "fastapi", "StreamingResponse"):
        assert forbidden not in source.lower(), forbidden


def test_run_event_repository_is_append_only_and_owns_replay_boundary() -> None:
    """The event port exposes append/read operations without history mutation."""
    from ava.repositories.run_event_repository import RunEventRepository

    methods = {
        name for name, value in vars(RunEventRepository).items()
        if callable(value) and not name.startswith("_")
    }
    assert methods == {"append", "get_events", "get_latest", "list_after_sequence"}


def test_replay_route_is_an_event_observer_not_a_lifecycle_writer() -> None:
    """History reads cannot infer, append, or mutate lifecycle facts."""
    source = (API_DIR / "routes" / "runs.py").read_text(encoding="utf-8")
    replay_start = source.index("async def get_run_events")
    replay_end = source.index(
        "# ============================================================\n# END: Get Run Events"
    )
    replay_source = source[replay_start:replay_end]
    for forbidden in ("cancel_run(", "prepare_run(", "execute_prepared_run(", "append(", "_lifecycle"):
        assert forbidden not in replay_source, forbidden


def test_assistant_content_has_one_application_write_path() -> None:
    """Only the focused output module may update messages and author content facts."""
    allowed = SERVICES_DIR / "assistant_response_service.py"
    offenders: list[str] = []
    for path in _iter_python_files(SRC_DIR):
        if path == allowed or path.name in {"message_repository.py", "message_store.py"}:
            continue
        source = path.read_text(encoding="utf-8")
        if ".update_content(" in source and "document" not in path.name:
            offenders.append(str(path.relative_to(SRC_DIR)))
    assert offenders == []
    source = allowed.read_text(encoding="utf-8")
    assert "EventType.MESSAGE_CONTENT" in source
    assert "self._messages.update_content" in source


def test_runtime_and_agent_adapters_do_not_own_partial_content_persistence() -> None:
    forbidden = (
        "ava.repositories.message_repository",
        "ava.repositories.run_event_repository",
        "ava.services.assistant_response_service",
    )
    for directory in (AGENTS_DIR / "adapters", SRC_DIR / "runtimes" / "adapters"):
        for path in _iter_python_files(directory):
            imports = _ava_imports(ast.parse(path.read_text(encoding="utf-8")))
            assert not any(name.startswith(forbidden) for name in imports), path


def test_project_file_domain_stays_out_of_storage_and_knowledge_implementations() -> None:
    """Project file metadata ports cannot reach adapters or future RAG layers."""
    project_file_modules = (
        REPOSITORIES_DIR / "project_file.py",
        REPOSITORIES_DIR / "project_file_repository.py",
        REPOSITORIES_DIR / "project_file_content.py",
        CONTRACTS_DIR / "project_files.py",
    )
    forbidden = {"api", "infrastructure", "services", "agents", "models", "knowledge", "rag"}
    for path in project_file_modules:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        violations = _ava_sibling_imports(tree) & forbidden
        assert not violations, f"{path} must remain a domain/port/contract module: {violations}"


def test_knowledge_ports_are_provider_neutral_and_avoid_storage_adapters() -> None:
    """Knowledge identity and ports cannot bind AVA to a vendor or adapter."""
    knowledge_paths = (
        REPOSITORIES_DIR / "knowledge.py",
        REPOSITORIES_DIR / "knowledge_ports.py",
    )
    forbidden_modules = FORBIDDEN_IMPORTS | {
        "chromadb",
        "faiss",
        "langchain_core",
        "llama_index",
        "llamaindex",
        "pinecone",
        "pgvector",
        "qdrant_client",
        "sentence_transformers",
        "weaviate",
    }
    forbidden_siblings = {"api", "agents", "execution", "infrastructure", "models", "runtimes", "services"}
    for path in knowledge_paths:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        vendor_imports = _top_level_imports(tree) & forbidden_modules
        assert not vendor_imports, f"{path} imports provider/framework modules: {vendor_imports}"
        sibling_imports = _ava_sibling_imports(tree) & forbidden_siblings
        assert not sibling_imports, f"{path} imports adapters or runtime layers: {sibling_imports}"


def test_project_file_domain_does_not_import_knowledge() -> None:
    """Canonical Project File identity cannot depend on future Knowledge types."""
    project_file = REPOSITORIES_DIR / "project_file.py"
    tree = ast.parse(project_file.read_text(encoding="utf-8"), filename=str(project_file))

    knowledge_imports = {name for name in _ava_imports(tree) if ".knowledge" in name or ".rag" in name}
    assert not knowledge_imports, f"Project File domain must not import Knowledge: {knowledge_imports}"
