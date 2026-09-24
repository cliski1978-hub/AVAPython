"""Model catalog discovery service.

Answers "what models does AVA know about?" over the read-only ``ModelRegistry``.
Discovery is metadata-only: it reads configured ``ModelProfile``s and exposes
only the public-safe ``ModelInfo`` (identity, provider id, hosting placement,
declared capabilities, enabled flag). It never resolves a provider, never
contacts a provider or endpoint, never constructs a ``RuntimeModelBinding``,
and never exposes the provider-native model name or any credential.

``/models`` describes configured models; it does **not** decide eligibility for
a task — that filtering belongs to a future orchestrator.
"""

from ava.contracts.models import ModelInfo, ModelQualificationInfo
from ava.contracts.responses import ModelDiscoveryResponse
from ava.models.model_registry import ModelRegistry
from ava.models.qualifications import ModelQualificationStore


class ModelDiscoveryService:
    """Enumerate configured models as safe public metadata."""

    def __init__(self, *, registry: ModelRegistry, qualification_store: ModelQualificationStore | None = None) -> None:
        """Construct discovery over the catalog it and resolution share.

        Args:
            registry: The application's ``ModelRegistry``. The service reads it
                only through its public ``list()`` surface and never mutates it.
        """
        self._registry = registry
        self._qualification_store = qualification_store

    def discover(self) -> ModelDiscoveryResponse:
        """Build a deterministic catalog snapshot.

        Models are returned sorted by stable ``model_id`` so the response is
        stable regardless of composition/insertion order. Disabled profiles are
        included (with ``enabled=False``) so admin/UI tooling can observe them;
        the execution path still rejects disabled models.
        """
        models = [
            ModelInfo(
                provider_name=profile.provider_id,
                provider_id=profile.provider_id,
                model_id=profile.model_id,
                display_name=profile.display_name,
                capabilities=profile.capabilities,
                hosting_mode=profile.hosting_mode,
                enabled=profile.enabled,
                qualifications=self._qualifications_for(profile.model_id),
            )
            for profile in sorted(self._registry.list(), key=lambda profile: profile.model_id)
        ]
        return ModelDiscoveryResponse(models=models)

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
