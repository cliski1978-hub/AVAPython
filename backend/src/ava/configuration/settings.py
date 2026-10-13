"""Application settings.

Environment-driven configuration for the AVA backend. Kept separate from the
framework-neutral core.ApplicationConfig.

The transports section (host, port, debug, log level) is operational. The
application section (name, environment) and provider selection fields mirror
the framework-neutral core configuration so provider choices remain
configuration-driven.
"""

import os
from dataclasses import dataclass, field

from ava.contracts.models import ModelHostingMode

# ============================================================
# BEGIN: Settings
# ============================================================


def _env_str(name: str, default: str) -> str:
    """Read a string from the environment with a default."""
    return os.getenv(name, default)


def _env_hosting_mode(name: str, default: ModelHostingMode) -> ModelHostingMode:
    """Read a strictly validated model hosting mode from the environment.

    An absent/blank value uses ``default``; an unrecognized explicit value is a
    configuration error and is never silently downgraded or inferred.
    """
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return default
    try:
        return ModelHostingMode(raw)
    except ValueError as exc:
        valid = ", ".join(mode.value for mode in ModelHostingMode)
        raise ValueError(f"{name} must be one of: {valid}") from exc


def _env_persistence_provider(name: str, default: str) -> str:
    """Read a strictly validated persistence provider from the environment.

    As with hosting mode, an absent/blank value uses ``default`` and an
    unrecognized explicit value is a configuration error — never silently
    downgraded. ``memory`` keeps the in-memory stores (the default);
    ``relational`` selects the durable SQLite adapters that cover every Phase 4
    domain (run, run-event, conversation, message, document, document revision,
    and attachment) over one shared database.
    """
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return default
    if raw not in {"memory", "relational"}:
        raise ValueError(f"{name} must be one of: memory, relational")
    return raw


def _env_attachment_storage(name: str, default: str) -> str:
    """Read a strictly validated attachment storage provider from the environment.

    Mirrors persistence selection: an absent/blank value uses ``default`` and
    an unrecognized explicit value is a configuration error — never silently
    downgraded or fallen back to memory. ``memory`` keeps the in-memory content
    store (the default); ``local`` selects the local-filesystem content adapter
    and requires ``AVA_ATTACHMENT_STORAGE_ROOT``. Selection is independent of
    the metadata persistence provider (``AVA_PERSISTENCE``).
    """
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return default
    if raw not in {"memory", "local"}:
        raise ValueError(f"{name} must be one of: memory, local")
    return raw


def _env_project_file_storage(name: str, default: str) -> str:
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return default
    if raw not in {"memory", "local"}:
        raise ValueError(f"{name} must be one of: memory, local")
    return raw


def _env_int(name: str, default: int) -> int:
    """Read an int from the environment with a default."""
    raw = os.getenv(name, "")
    return int(raw) if raw else default


def _env_bool(name: str, default: bool) -> bool:
    """Read a bool from the environment with a default."""
    raw = os.getenv(name, "")
    if not raw:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    """Application settings loaded from the environment."""

    # Application
    application_name: str = field(default_factory=lambda: _env_str("AVA_APPLICATION", "AVA"))
    environment: str = field(default_factory=lambda: _env_str("AVA_ENVIRONMENT", "development"))

    # API transport
    host: str = field(default_factory=lambda: _env_str("AVA_HOST", "127.0.0.1"))
    port: int = field(default_factory=lambda: _env_int("AVA_PORT", 8000))
    debug: bool = field(default_factory=lambda: _env_bool("AVA_DEBUG", True))
    log_level: str = field(default_factory=lambda: _env_str("AVA_LOG_LEVEL", "info"))

    # Provider selection (configuration-driven)
    agent_provider: str = field(default_factory=lambda: _env_str("AVA_AGENT_PROVIDER", "mock"))
    agent_runtime: str = field(default_factory=lambda: _env_str("AVA_AGENT_RUNTIME", "native"))
    model_provider: str = field(default_factory=lambda: _env_str("AVA_MODEL_PROVIDER", "local"))
    model_name: str = field(default_factory=lambda: _env_str("AVA_MODEL_NAME", "local-model"))
    # Stable AVA model identity (provider-neutral). Blank derives a legacy id
    # from provider + model name so existing deployments need no reconfiguration.
    model_id: str = field(default_factory=lambda: _env_str("AVA_MODEL_ID", ""))
    # Server-owned deployment placement. The bootstrap local path defaults to
    # LOCAL; it is never inferred from the provider id, protocol, or endpoint.
    model_hosting_mode: ModelHostingMode = field(
        default_factory=lambda: _env_hosting_mode("AVA_MODEL_HOSTING_MODE", ModelHostingMode.LOCAL)
    )

    # Model provider transport (endpoint-level, not carried into core config)
    local_model_base_url: str = field(
        default_factory=lambda: _env_str("AVA_LOCAL_MODEL_BASE_URL", "http://localhost:11434/v1")
    )

    # Persistence provider (Phase 4). "memory" (the default) keeps the
    # in-memory stores; "relational" activates the durable SQLite adapters for
    # every Phase 4 domain over one shared database.
    persistence_provider: str = field(default_factory=lambda: _env_persistence_provider("AVA_PERSISTENCE", "memory"))
    # Database location used when ``persistence_provider`` is ``relational``.
    persistence_database_url: str = field(
        default_factory=lambda: _env_str("AVA_PERSISTENCE_DATABASE_URL", "ava.sqlite3")
    )

    # Attachment content storage (Step 4.14.D). Independent of the metadata
    # persistence provider: ``AVA_PERSISTENCE`` and ``AVA_ATTACHMENT_STORAGE``
    # are orthogonal selections. ``memory`` (the default) keeps the in-memory
    # content store; ``local`` selects the local-filesystem adapter and requires
    # an explicit ``AVA_ATTACHMENT_STORAGE_ROOT``. In ``memory`` mode the root
    # may be absent and is ignored.
    attachment_storage: str = field(default_factory=lambda: _env_attachment_storage("AVA_ATTACHMENT_STORAGE", "memory"))
    # Filesystem root used when ``attachment_storage`` is ``local``.
    attachment_storage_root: str = field(default_factory=lambda: _env_str("AVA_ATTACHMENT_STORAGE_ROOT", ""))
    # Maximum accepted size for one uploaded attachment (default 25 MiB).
    attachment_max_size_bytes: int = field(
        default_factory=lambda: _env_int("AVA_ATTACHMENT_MAX_SIZE_BYTES", 25 * 1024 * 1024)
    )

    # Project files use a distinct content lifecycle and storage root.
    project_file_storage: str = field(
        default_factory=lambda: _env_project_file_storage("AVA_PROJECT_FILE_STORAGE", "memory")
    )
    project_file_storage_root: str = field(default_factory=lambda: _env_str("AVA_PROJECT_FILE_STORAGE_ROOT", ""))

    def __post_init__(self) -> None:
        if self.attachment_storage == "local" and not self.attachment_storage_root.strip():
            raise ValueError("AVA_ATTACHMENT_STORAGE=local requires AVA_ATTACHMENT_STORAGE_ROOT to be set")
        if self.attachment_max_size_bytes <= 0:
            raise ValueError("AVA_ATTACHMENT_MAX_SIZE_BYTES must be positive")
        if self.project_file_storage == "local" and not self.project_file_storage_root.strip():
            raise ValueError("AVA_PROJECT_FILE_STORAGE=local requires AVA_PROJECT_FILE_STORAGE_ROOT to be set")

    @property
    def resolved_model_id(self) -> str:
        """Return the stable AVA model identity, deriving a legacy id if unset."""
        if self.model_id.strip():
            return self.model_id
        return f"{self.model_provider}-{self.model_name}"

    @property
    def is_debug(self) -> bool:
        """Return whether debug mode is enabled."""
        return self.debug


# ============================================================
# END: Settings
# ============================================================


_settings: Settings | None = None


def get_settings() -> Settings:
    """Return a cached application settings instance."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
