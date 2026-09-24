"""Settings / configuration tests.

Verify (Phase 3 Step 6) that AVA configuration independently identifies the
agent provider, model provider, and model name, that defaults are sane, and
that environment overrides follow the existing ``AVA_*`` conventions without
coupling the three selections.
"""

import pytest

from ava.configuration.settings import Settings
from ava.core.application import ApplicationConfig

#: All environment variables the settings layer reads. Tests clear them so
#: they assert on explicit values rather than ambient environment state.
_AVA_VARS = (
    "AVA_APPLICATION",
    "AVA_ENVIRONMENT",
    "AVA_AGENT_PROVIDER",
    "AVA_AGENT_RUNTIME",
    "AVA_MODEL_PROVIDER",
    "AVA_MODEL_NAME",
    "AVA_MODEL_ID",
    "AVA_MODEL_HOSTING_MODE",
    "AVA_LOCAL_MODEL_BASE_URL",
    "AVA_HOST",
    "AVA_PORT",
    "AVA_DEBUG",
    "AVA_LOG_LEVEL",
    "AVA_PERSISTENCE",
    "AVA_PERSISTENCE_DATABASE_URL",
    "AVA_ATTACHMENT_STORAGE",
    "AVA_ATTACHMENT_STORAGE_ROOT",
)


@pytest.fixture(autouse=True)
def _clean_ava_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove AVA_* environment variables before every test."""
    for name in _AVA_VARS:
        monkeypatch.delenv(name, raising=False)


def _set_env(monkeypatch: pytest.MonkeyPatch, *pairs: tuple[str, str]) -> None:
    """Set named AVA_* environment variables via monkeypatch."""
    for name, value in pairs:
        assert name in _AVA_VARS, f"unknown AVA env var: {name}"
        assert value, f"value for {name} must be non-empty"
        monkeypatch.setenv(name, value)


# ============================================================
# BEGIN: Default Settings Tests
# ============================================================


def test_default_settings_construct_successfully() -> None:
    """The settings construct with expected model configuration defaults.

    No live provider or installed model is required.
    """
    settings = Settings()
    assert settings.application_name == "AVA"
    assert settings.environment == "development"
    assert settings.agent_provider == "mock"
    assert settings.agent_runtime == "native"
    assert settings.model_provider == "local"
    assert settings.model_name == "local-model"
    assert settings.local_model_base_url == "http://localhost:11434/v1"


# ============================================================
# END: Default Settings Tests
# ============================================================


# ============================================================
# BEGIN: Persistence Settings Tests
# ============================================================


def test_default_persistence_settings_are_in_memory() -> None:
    """The production default keeps the in-memory stores active."""
    settings = Settings()
    assert settings.persistence_provider == "memory"
    assert settings.persistence_database_url == "ava.sqlite3"


def test_persistence_provider_env_override_enables_relational(monkeypatch: pytest.MonkeyPatch) -> None:
    """An explicit relational provider selects the SQLite adapters config."""
    _set_env(monkeypatch, ("AVA_PERSISTENCE", "relational"))
    settings = Settings()
    assert settings.persistence_provider == "relational"
    assert settings.agent_provider == "mock"
    assert settings.model_provider == "local"


def test_persistence_database_url_env_override_changes_only_url(monkeypatch: pytest.MonkeyPatch) -> None:
    """The database url override leaves provider selection alone."""
    _set_env(monkeypatch, ("AVA_PERSISTENCE_DATABASE_URL", "/data/ava.sqlite3"))
    settings = Settings()
    assert settings.persistence_database_url == "/data/ava.sqlite3"
    assert settings.persistence_provider == "memory"


def test_invalid_persistence_provider_is_a_configuration_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """An unrecognized provider value must never be silently downgraded."""
    _set_env(monkeypatch, ("AVA_PERSISTENCE", "oracle"))
    with pytest.raises(ValueError, match="AVA_PERSISTENCE must be one of: memory, relational"):
        Settings()


# ============================================================
# END: Persistence Settings Tests
# ============================================================


# ============================================================
# BEGIN: Attachment Content Storage Settings Tests
# ============================================================


def test_default_attachment_storage_is_memory() -> None:
    """The production default content store is the in-memory adapter."""
    settings = Settings()
    assert settings.attachment_storage == "memory"
    assert settings.attachment_storage_root == ""


def test_memory_mode_constructs_with_an_absent_root() -> None:
    """``memory`` needs no storage root and ignores it when present."""
    settings = Settings(attachment_storage="memory")
    assert settings.attachment_storage == "memory"
    assert settings.attachment_storage_root == ""


def test_memory_mode_ignores_a_configured_root(monkeypatch: pytest.MonkeyPatch) -> None:
    """A root configured while in memory mode is carried but does not bind."""
    _set_env(monkeypatch, ("AVA_ATTACHMENT_STORAGE_ROOT", "/data/attachments"))
    settings = Settings()
    assert settings.attachment_storage == "memory"
    assert settings.attachment_storage_root == "/data/attachments"


def test_local_mode_with_configured_root_is_valid(monkeypatch: pytest.MonkeyPatch) -> None:
    """``local`` selects the local adapter when its root is configured."""
    _set_env(
        monkeypatch,
        ("AVA_ATTACHMENT_STORAGE", "local"),
        ("AVA_ATTACHMENT_STORAGE_ROOT", "/data/attachments"),
    )
    settings = Settings()
    assert settings.attachment_storage == "local"
    assert settings.attachment_storage_root == "/data/attachments"
    assert settings.persistence_provider == "memory"


def test_local_mode_without_root_is_a_configuration_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """``local`` without ``AVA_ATTACHMENT_STORAGE_ROOT`` fails clearly."""
    _set_env(monkeypatch, ("AVA_ATTACHMENT_STORAGE", "local"))
    with pytest.raises(ValueError, match="AVA_ATTACHMENT_STORAGE=local requires AVA_ATTACHMENT_STORAGE_ROOT"):
        Settings()


def test_blank_local_root_is_a_configuration_error() -> None:
    """An explicitly blank root in local mode is still an error."""
    with pytest.raises(ValueError, match="AVA_ATTACHMENT_STORAGE=local requires AVA_ATTACHMENT_STORAGE_ROOT"):
        Settings(attachment_storage="local", attachment_storage_root=" ")


def test_unknown_attachment_storage_mode_is_a_configuration_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unimplemented modes (s3/azure/databricks) are never silently downgraded."""
    _set_env(monkeypatch, ("AVA_ATTACHMENT_STORAGE", "s3"))
    with pytest.raises(ValueError, match="AVA_ATTACHMENT_STORAGE must be one of: memory, local"):
        Settings()


# ============================================================
# END: Attachment Content Storage Settings Tests
# ============================================================


# ============================================================
# BEGIN: Model Provider Environment Override Tests
# ============================================================


def test_model_provider_env_override_changes_only_model_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An override of model_provider leaves the agent and model name alone."""
    _set_env(monkeypatch, ("AVA_MODEL_PROVIDER", "provider-a"))
    settings = Settings()
    assert settings.model_provider == "provider-a"
    assert settings.agent_provider == "mock"
    assert settings.model_name == "local-model"
    assert settings.local_model_base_url == "http://localhost:11434/v1"


# ============================================================
# END: Model Provider Environment Override Tests
# ============================================================


# ============================================================
# BEGIN: Local Model Base URL Environment Override Tests
# ============================================================


def test_local_model_base_url_default_is_the_local_ollama_endpoint() -> None:
    """The default local endpoint is Ollama's OpenAI-compatible /v1 base."""
    settings = Settings()
    assert settings.local_model_base_url == "http://localhost:11434/v1"


def test_local_model_base_url_env_override_changes_only_local_base_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An override of local_model_base_url leaves provider/model selection alone."""
    _set_env(monkeypatch, ("AVA_LOCAL_MODEL_BASE_URL", "http://127.0.0.1:9000/v1"))
    settings = Settings()
    assert settings.local_model_base_url == "http://127.0.0.1:9000/v1"
    assert settings.model_provider == "local"
    assert settings.model_name == "local-model"
    assert settings.agent_provider == "mock"


# ============================================================
# END: Local Model Base URL Environment Override Tests
# ============================================================


# ============================================================
# BEGIN: Model Name Environment Override Tests
# ============================================================


def test_model_name_env_override_changes_only_model_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An override of model_name leaves the agent and provider alone."""
    _set_env(monkeypatch, ("AVA_MODEL_NAME", "model-a"))
    settings = Settings()
    assert settings.model_name == "model-a"
    assert settings.agent_provider == "mock"
    assert settings.model_provider == "local"


# ============================================================
# END: Model Name Environment Override Tests
# ============================================================


# ============================================================
# BEGIN: Agent / Model Independence Tests
# ============================================================


def test_agent_and_model_selection_are_independent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """agent_provider, model_provider, and model_name survive independently."""
    _set_env(
        monkeypatch,
        ("AVA_AGENT_PROVIDER", "agent-x"),
        ("AVA_MODEL_PROVIDER", "provider-b"),
        ("AVA_MODEL_NAME", "model-b"),
    )
    settings = Settings()
    assert (settings.agent_provider, settings.model_provider, settings.model_name) == (
        "agent-x",
        "provider-b",
        "model-b",
    )


def test_agent_runtime_override_is_independent(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_env(monkeypatch, ("AVA_AGENT_RUNTIME", "future-runtime"))
    settings = Settings()
    assert settings.agent_runtime == "future-runtime"
    assert settings.agent_provider == "mock"
    assert settings.model_provider == "local"
    assert settings.model_name == "local-model"
    assert settings.local_model_base_url == "http://localhost:11434/v1"


def test_alternate_combinations_are_not_derived(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Settings never derive one selection from another.

    Two unrelated combinations must both resolve exactly as configured.
    """
    _set_env(
        monkeypatch,
        ("AVA_AGENT_PROVIDER", "mock"),
        ("AVA_MODEL_PROVIDER", "provider-a"),
        ("AVA_MODEL_NAME", "model-a"),
    )
    first = Settings()
    assert (first.agent_provider, first.model_provider, first.model_name) == (
        "mock",
        "provider-a",
        "model-a",
    )

    _set_env(
        monkeypatch,
        ("AVA_AGENT_PROVIDER", "other-agent"),
        ("AVA_MODEL_PROVIDER", "provider-b"),
        ("AVA_MODEL_NAME", "model-b"),
    )
    second = Settings()
    assert (second.agent_provider, second.model_provider, second.model_name) == (
        "other-agent",
        "provider-b",
        "model-b",
    )


# ============================================================
# END: Agent / Model Independence Tests
# ============================================================


# ============================================================
# BEGIN: Core Config Mirror Tests
# ============================================================


def test_application_config_mirrors_provider_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The framework-neutral core config carries the same independent values."""
    _set_env(
        monkeypatch,
        ("AVA_AGENT_PROVIDER", "agent-y"),
        ("AVA_MODEL_PROVIDER", "provider-c"),
        ("AVA_MODEL_NAME", "model-c"),
    )
    settings = Settings()
    config = ApplicationConfig(
        application_name=settings.application_name,
        environment=settings.environment,
        agent_provider=settings.agent_provider,
        model_provider=settings.model_provider,
        model_name=settings.model_name,
        agent_runtime=settings.agent_runtime,
    )
    assert config.agent_provider == "agent-y"
    assert config.model_provider == "provider-c"
    assert config.model_name == "model-c"
    assert config.agent_runtime == "native"


def test_default_application_config_has_neutral_model_defaults() -> None:
    """The default core config mirrors the default settings values."""
    config = ApplicationConfig()
    assert config.agent_provider == "mock"
    assert config.model_provider == "local"
    assert config.model_name == "local-model"
    assert config.agent_runtime == "native"


# ============================================================
# END: Core Config Mirror Tests
# ============================================================
