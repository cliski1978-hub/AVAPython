"""Deterministic, runtime-neutral selection over the configured model catalog.

The orchestrator evaluates structured requirements only. It has no access to
prompts, workspaces, credentials, tools, runtimes, or provider implementations.
Selection is descriptive policy: it never grants an execution permission.
"""

from dataclasses import dataclass, field
from enum import StrEnum

from ava.contracts.models import ModelCapabilities, QualificationStatus
from ava.execution.hosting import HostingReason, ModelHostingRequirement
from ava.models.model_registry import ModelProfile, ModelRegistry
from ava.models.qualifications import ModelQualificationStore


class ModelRejectionReason(StrEnum):
    """Stable, compact reason codes for an ineligible catalog profile."""

    MODEL_DISABLED = "model_disabled"
    HOSTING_MODE_NOT_ALLOWED = HostingReason.MODE_NOT_ALLOWED.value
    PROVIDER_MISMATCH = "provider_mismatch"
    CAPABILITY_MISSING = "capability_missing"
    QUALIFICATION_MISSING = "qualification_missing"
    QUALIFICATION_INSUFFICIENT = "qualification_insufficient"


@dataclass(frozen=True)
class QualificationRequirement:
    """A strict measured-evidence requirement for one qualification identity."""

    qualification_id: str
    runtime_id: str | None = None
    required_status: QualificationStatus = QualificationStatus.PASS


@dataclass(frozen=True)
class ModelSelectionRequest:
    """Structured selection inputs; intentionally contains no task content."""

    explicit_model_id: str | None = None
    preferred_provider_id: str | None = None
    runtime_id: str | None = None
    hosting_requirement: ModelHostingRequirement | None = None
    required_capabilities: frozenset[str] = field(default_factory=frozenset)
    qualification_requirements: tuple[QualificationRequirement, ...] = ()

    def __post_init__(self) -> None:
        known = set(ModelCapabilities.model_fields) - {"contract_version"}
        unknown = self.required_capabilities - known
        if unknown:
            raise ValueError(f"Unknown model capabilities: {sorted(unknown)!r}")


@dataclass(frozen=True)
class ModelRejection:
    """Safe diagnostic metadata for a rejected configured model."""

    model_id: str
    reason_code: ModelRejectionReason


@dataclass(frozen=True)
class ModelSelectionDecision:
    """The selected model and bounded deterministic fallback ordering."""

    model_id: str
    candidate_model_ids: tuple[str, ...]
    rejected_candidates: tuple[ModelRejection, ...]
    reason_code: str


class ModelSelectionError(ValueError):
    """Base selection failure carrying only safe rejection metadata."""

    def __init__(self, message: str, rejected_candidates: tuple[ModelRejection, ...] = ()) -> None:
        super().__init__(message)
        self.rejected_candidates = rejected_candidates


class ExplicitModelNotFoundError(ModelSelectionError):
    """An explicit model override does not name a configured profile."""


class ExplicitModelIneligibleError(ModelSelectionError):
    """An explicit model override failed a hard eligibility filter."""


class NoEligibleModelError(ModelSelectionError):
    """No configured profile survived deterministic hard filters."""


class ModelOrchestrator:
    """Select a model after hard filters, then a deterministic preference rule.

    Auto selection ranks eligible candidates by configured default first, then
    lexicographic stable ``model_id``. No score, learned policy, name heuristic,
    or runtime execution fallback is involved.
    """

    def __init__(
        self,
        *,
        registry: ModelRegistry,
        qualification_store: ModelQualificationStore,
        default_model_id: str,
    ) -> None:
        self._registry = registry
        self._qualifications = qualification_store
        self._default_model_id = default_model_id

    def select(
        self, request: ModelSelectionRequest, *, registry: ModelRegistry | None = None
    ) -> ModelSelectionDecision:
        """Apply the same policy to the startup catalog or a per-run snapshot.

        A snapshot lets persisted settings supply profiles without mutating the
        shared bootstrap catalog. Qualification and eligibility policy remain
        owned by this orchestrator, including exact-model rejection semantics.
        """
        registry = registry if registry is not None else self._registry
        if request.explicit_model_id is not None:
            profile = registry.get(request.explicit_model_id)
            if profile is None:
                raise ExplicitModelNotFoundError("Explicit model is not configured")
            rejection = self._rejection_for(profile, request)
            if rejection is not None:
                raise ExplicitModelIneligibleError("Explicit model is not eligible", (rejection,))
            return ModelSelectionDecision(
                model_id=profile.model_id,
                candidate_model_ids=(profile.model_id,),
                rejected_candidates=(),
                reason_code="explicit_model",
            )

        eligible: list[ModelProfile] = []
        rejected: list[ModelRejection] = []
        for profile in sorted(registry.list(), key=lambda item: item.model_id):
            rejection = self._rejection_for(profile, request)
            if rejection is None:
                eligible.append(profile)
            else:
                rejected.append(rejection)
        if not eligible:
            raise NoEligibleModelError("No eligible configured model", tuple(rejected))

        ordered = sorted(
            eligible,
            key=lambda profile: (profile.model_id != self._default_model_id, profile.model_id),
        )
        selected = ordered[0]
        return ModelSelectionDecision(
            model_id=selected.model_id,
            candidate_model_ids=tuple(profile.model_id for profile in ordered),
            rejected_candidates=tuple(rejected),
            reason_code=("configured_default" if selected.model_id == self._default_model_id else "stable_model_id"),
        )

    def _rejection_for(self, profile: ModelProfile, request: ModelSelectionRequest) -> ModelRejection | None:
        if not profile.enabled:
            return ModelRejection(profile.model_id, ModelRejectionReason.MODEL_DISABLED)
        if request.hosting_requirement is not None and not request.hosting_requirement.permits(profile.hosting_mode):
            return ModelRejection(profile.model_id, ModelRejectionReason.HOSTING_MODE_NOT_ALLOWED)
        if request.preferred_provider_id is not None and profile.provider_id != request.preferred_provider_id:
            return ModelRejection(profile.model_id, ModelRejectionReason.PROVIDER_MISMATCH)
        if any(not getattr(profile.capabilities, name) for name in request.required_capabilities):
            return ModelRejection(profile.model_id, ModelRejectionReason.CAPABILITY_MISSING)
        for requirement in request.qualification_requirements:
            qualification = self._qualifications.get(
                profile.model_id, requirement.qualification_id, requirement.runtime_id
            )
            if qualification is None:
                return ModelRejection(profile.model_id, ModelRejectionReason.QUALIFICATION_MISSING)
            if qualification.status is not requirement.required_status:
                return ModelRejection(profile.model_id, ModelRejectionReason.QUALIFICATION_INSUFFICIENT)
        return None
