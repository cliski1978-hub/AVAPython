"""Model catalog discovery service.

Answers "what models does AVA know about?" over two sources: persisted
``ModelConfiguration`` records and the read-only ``ModelRegistry`` bootstrap
catalog. Discovery is metadata-only: it exposes only the public-safe
``ModelInfo`` (identity, provider id, hosting placement, declared capabilities,
enabled flag). It never resolves a provider, never contacts a provider or
endpoint, never constructs a ``RuntimeModelBinding``, and never exposes the
provider-native model name or any credential.

Configured models are the catalog that matters to a user: a model added in
Settings is a configured model, and an execution selector that can only see the
bootstrap catalog cannot offer it. Bootstrap profiles are still reported,
because they are the pre-settings mechanism and still resolve when nothing is
configured.

``/models`` describes configured models; it does **not** decide eligibility for
a task — that filtering belongs to a future orchestrator. Disabled records are
reported with ``enabled=False`` rather than hidden, so a client can show them
and let an explicit selection fail on its own explicit terms.
"""

from ava.contracts.models import ModelInfo, ModelQualificationInfo
from ava.contracts.responses import ModelDiscoveryResponse
from ava.models.model_configurations import ModelConfiguration
from ava.models.model_registry import ModelRegistry
from ava.models.provider_connections import ProviderConnection
from ava.models.qualifications import ModelQualificationStore
from ava.repositories.execution_defaults_repository import ExecutionDefaultsRepository
from ava.repositories.model_configuration_repository import ModelConfigurationRepository
from ava.repositories.provider_connection_repository import ProviderConnectionRepository


class ModelDiscoveryService:
    """Enumerate configured models as safe public metadata."""

    def __init__(
        self,
        *,
        registry: ModelRegistry,
        qualification_store: ModelQualificationStore | None = None,
        model_configurations: ModelConfigurationRepository | None = None,
        provider_connections: ProviderConnectionRepository | None = None,
        execution_defaults: ExecutionDefaultsRepository | None = None,
    ) -> None:
        """Construct discovery over the catalogs it and resolution share.

        Args:
            registry: The application's bootstrap ``ModelRegistry``. The service
                reads it only through its public ``list()`` surface and never
                mutates it.
            qualification_store: Optional qualification evidence store.
            model_configurations: Persisted configured models. When supplied,
                these are the catalog a client selects from.
            provider_connections: Persisted provider connections, used only to
                read the adapter identity a configured model is served through.
                A configured model whose connection cannot be read is reported
                under its own ``model_id`` with the connection id as its provider
                identity rather than dropped, so an operator can see and fix it.
        """
        self._registry = registry
        self._qualification_store = qualification_store
        self._model_configurations = model_configurations
        self._provider_connections = provider_connections
        self._execution_defaults = execution_defaults

    def discover(self) -> ModelDiscoveryResponse:
        """Build a deterministic catalog snapshot.

        Configured models are reported first and win any identity collision with
        a bootstrap profile, because a configured record is the operator's
        explicit choice. Models are returned sorted by stable ``model_id`` so
        the response is stable regardless of composition/insertion order.
        Disabled profiles are included (with ``enabled=False``) so admin/UI
        tooling can observe them; the execution path still rejects disabled
        models.
        """
        by_id: dict[str, ModelInfo] = {}
        for profile in self._registry.list():
            by_id[profile.model_id] = ModelInfo(
                provider_name=profile.provider_id,
                provider_id=profile.provider_id,
                model_id=profile.model_id,
                display_name=profile.display_name,
                capabilities=profile.capabilities,
                hosting_mode=profile.hosting_mode,
                enabled=profile.enabled,
                qualifications=self._qualifications_for(profile.model_id),
            )
        for configuration in self._configured_models():
            by_id[configuration.model_id] = ModelInfo(
                provider_name=self._provider_identity(configuration),
                provider_id=self._provider_identity(configuration),
                model_id=configuration.model_id,
                display_name=configuration.display_name,
                capabilities=configuration.capabilities,
                hosting_mode=configuration.hosting_mode,
                enabled=configuration.enabled,
                qualifications=self._qualifications_for(configuration.model_id),
            )
        return ModelDiscoveryResponse(
            models=[by_id[key] for key in sorted(by_id)],
            default_model_id=self._default_model_id(),
        )

    def _default_model_id(self) -> str | None:
        """Which configured model the application defaults select.

        Read from persisted defaults only. A client uses this to label its
        "application default" option; it is not an eligibility filter, so an
        id that is absent from the catalog is still reported.
        """
        if self._execution_defaults is None:
            return None
        defaults = self._execution_defaults.get()
        return None if defaults is None else defaults.default_model_id

    def _configured_models(self) -> tuple[ModelConfiguration, ...]:
        if self._model_configurations is None:
            return ()
        return tuple(self._model_configurations.list())

    def _provider_identity(self, configuration: ModelConfiguration) -> str:
        """The adapter identity a configured model is served through.

        Only the adapter *type* is public: the connection's endpoint and
        credential never reach discovery.
        """
        if self._provider_connections is not None:
            connection: ProviderConnection | None = self._provider_connections.get(configuration.provider_connection_id)
            if connection is not None:
                return connection.provider_id
        return configuration.provider_connection_id

    def _qualifications_for(self, model_id: str) -> list[ModelQualificationInfo]:
        if self._qualification_store is None:
            return []
        return [
            ModelQualificationInfo(
                qualification_id=item.qualification_id,
                status=item.status,
                runtime_id=item.runtime_id,
                task_class=item.task_class,
                evidence_summary=item.evidence_summary,
                measured_at=item.measured_at,
            )
            for item in self._qualification_store.list_for_model(model_id)
        ]
