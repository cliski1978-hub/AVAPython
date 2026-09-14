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
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[1] / "src" / "ava"
CORE_DIR = SRC_DIR / "core"
CONTRACTS_DIR = SRC_DIR / "contracts"
SERVICES_DIR = SRC_DIR / "services"
API_DIR = SRC_DIR / "api"
AGENT_ADAPTERS_DIR = SRC_DIR / "agents" / "adapters"
MOCK_ADAPTER_DIR = AGENT_ADAPTERS_DIR / "mock"

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
        if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module and (
            node.module == "ava" or node.module.startswith("ava.")
        ):
            paths.add(node.module)
    return paths


def _ava_sibling_imports(tree: ast.Module) -> set[str]:
    """Collect the second-level module names imported from the ava package."""
    return {path.split(".")[1] for path in _ava_imports(tree) if len(path.split(".")) >= 2}


# ============================================================
# BEGIN: Core Independence Tests
# ============================================================


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
            if import_path.startswith("ava.agents.adapters") or import_path.startswith(
                "ava.models.providers"
            ):
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
            if import_path.startswith("ava.agents.adapters") or import_path.startswith(
                "ava.models.providers"
            ):
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