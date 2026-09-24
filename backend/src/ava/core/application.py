"""AVA application core.

Framework-neutral application behavior that will coordinate agent runs,
conversations, document operations, approvals, tools, events, model provider
selection, and agent adapter selection.

This stage establishes only the structural foundation.
"""

from dataclasses import dataclass

# ============================================================
# BEGIN: Application Config
# ============================================================


@dataclass(frozen=True)
class ApplicationConfig:
    """Core application configuration.

    Holds only framework-neutral configuration that affects application
    behavior. Transport/technical settings live in configuration.settings.

    Provider selection is configuration-driven: future values such as
    ``model_provider="local"`` or ``model_provider="company_gateway"`` must
    change AVA behavior through configuration, not core rewrites.
    """

    application_name: str = "AVA"
    environment: str = "development"
    agent_provider: str = "mock"
    agent_runtime: str = "native"
    model_provider: str = "local"
    model_name: str = "local-model"

    @property
    def app_name(self) -> str:
        """Return the application name."""
        return self.application_name


# ============================================================
# END: Application Config
# ============================================================


# ============================================================
# BEGIN: Application Root
# ============================================================


class Application:
    """The AVA application root.

    Owns application-level behavior. In this stage it is intentionally
    minimal; future agent runs, events, and coordination will hang off this.
    """

    def __init__(self, config: ApplicationConfig | None = None) -> None:
        """Construct the application root with an optional config."""
        self._config = config or ApplicationConfig()

    @property
    def config(self) -> ApplicationConfig:
        """Return the application configuration."""
        return self._config

    def name(self) -> str:
        """Return the application name for status reporting."""
        return self._config.app_name


# ============================================================
# END: Application Root
# ============================================================
