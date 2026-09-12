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

# ============================================================
# BEGIN: Settings
# ============================================================


def _env_str(name: str, default: str) -> str:
    """Read a string from the environment with a default."""
    return os.getenv(name, default)


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

    # Provider selection (configuration-driven; not functional yet)
    agent_provider: str = field(default_factory=lambda: _env_str("AVA_AGENT_PROVIDER", "mock"))
    model_provider: str = field(default_factory=lambda: _env_str("AVA_MODEL_PROVIDER", "local"))

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