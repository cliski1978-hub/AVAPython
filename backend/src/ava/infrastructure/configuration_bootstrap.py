"""One-time materialization of valid legacy settings in an empty durable store."""

import logging
from collections.abc import Callable
from contextlib import AbstractContextManager
from enum import StrEnum

from ava.configuration.execution_defaults import ApplicationExecutionDefaults
from ava.configuration.settings import Settings
from ava.contracts.models import ModelCapabilities
from ava.execution.configuration_resolver import ConfigurationRepositories
from ava.infrastructure.model_provider_factory import bootstrap_provider_config_valid
from ava.models.model_configurations import ModelConfiguration
from ava.models.provider_connections import ProviderConnection
from ava.runtimes.configurations import RuntimeConfiguration
from ava.runtimes.registry import RuntimeRegistry

logger = logging.getLogger(__name__)


class BootstrapStatus(StrEnum):
    SEEDED = "seeded"
    PERSISTED_DEFAULTS = "persisted_defaults"
    EXISTING_RECORDS = "existing_records"
    COMPATIBILITY_ONLY = "compatibility_only"
    INVALID_BOOTSTRAP = "invalid_bootstrap"


class ConfigurationBootstrapError(RuntimeError):
    """Startup materialization failed; no partial write may be published."""


def seed_execution_configuration(
    settings: Settings,
    repositories: ConfigurationRepositories,
    *,
    transaction: Callable[[], AbstractContextManager[object]] | None,
    runtime_registry: RuntimeRegistry,
) -> BootstrapStatus:
    """Seed only empty durable native installations, never synchronize them.

    The emptiness check and all four repository writes share BEGIN IMMEDIATE.
    Nested repository transactions use savepoints and cannot commit this unit.
    Any existing record prevents seeding, including matching bootstrap ids.
    Memory and mock installations preserve their legacy development behavior.
    """
    if transaction is None or settings.agent_provider != "native":
        return BootstrapStatus.COMPATIBILITY_ONLY
    try:
        with transaction():
            if repositories.execution_defaults.get() is not None:
                return BootstrapStatus.PERSISTED_DEFAULTS
            if (
                repositories.provider_connections.list()
                or repositories.model_configurations.list()
                or repositories.runtime_configurations.list()
            ):
                logger.info("Execution bootstrap skipped: existing configuration records; choose defaults in Settings")
                return BootstrapStatus.EXISTING_RECORDS
            if runtime_registry.get(settings.agent_runtime) is None or not bootstrap_provider_config_valid(
                settings.model_provider, settings.local_model_base_url
            ):
                logger.warning(
                    "Execution bootstrap unavailable; configure Providers, Models, Runtimes and Defaults in Settings"
                )
                return BootstrapStatus.INVALID_BOOTSTRAP
            try:
                connection = ProviderConnection(
                    provider_connection_id=f"bootstrap-provider-{settings.model_provider}",
                    provider_id=settings.model_provider,
                    display_name=f"Bootstrap {settings.model_provider}",
                    endpoint=settings.local_model_base_url,
                    credential_reference=None,
                )
                model = ModelConfiguration(
                    model_id=settings.resolved_model_id,
                    provider_connection_id=connection.provider_connection_id,
                    provider_model_name=settings.model_name,
                    display_name=settings.model_name,
                    hosting_mode=settings.model_hosting_mode,
                    capabilities=ModelCapabilities(chat=True),
                )
                runtime = RuntimeConfiguration(
                    runtime_configuration_id=f"bootstrap-runtime-{settings.agent_runtime}",
                    runtime_type=settings.agent_runtime,
                    display_name=f"Bootstrap {settings.agent_runtime}",
                )
                defaults = ApplicationExecutionDefaults(
                    connection.provider_connection_id, model.model_id, runtime.runtime_configuration_id
                )
            except ValueError:
                logger.warning("Execution bootstrap invalid; configure execution defaults in Settings")
                return BootstrapStatus.INVALID_BOOTSTRAP
            repositories.provider_connections.create(connection)
            repositories.model_configurations.create(model)
            repositories.runtime_configurations.create(runtime)
            repositories.execution_defaults.set(defaults)
        logger.info("Materialized initial execution settings; subsequent startups preserve persisted values")
        return BootstrapStatus.SEEDED
    except Exception:
        raise ConfigurationBootstrapError(
            "Could not initialize execution settings; bootstrap transaction rolled back"
        ) from None
