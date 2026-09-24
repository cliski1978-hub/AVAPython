"""Step 42 deterministic model-orchestration tests."""

import pytest

from ava.contracts.models import ModelCapabilities, ModelHostingMode, QualificationStatus
from ava.execution.hosting import ModelHostingRequirement
from ava.execution.model_orchestrator import (
    ExplicitModelIneligibleError,
    ExplicitModelNotFoundError,
    ModelOrchestrator,
    ModelRejectionReason,
    ModelSelectionRequest,
    NoEligibleModelError,
    QualificationRequirement,
)
from ava.models.model_registry import ModelProfile, ModelRegistry
from ava.models.qualifications import ModelQualification, ModelQualificationStore


def _profile(
    model_id: str,
    *,
    provider: str = "local",
    hosting: ModelHostingMode = ModelHostingMode.LOCAL,
    enabled: bool = True,
    tools: bool = False,
) -> ModelProfile:
    return ModelProfile(
        model_id=model_id,
        display_name=model_id,
        provider_id=provider,
        provider_model_name=f"{model_id}-native",
        hosting_mode=hosting,
        capabilities=ModelCapabilities(chat=True, tool_calling=tools),
        enabled=enabled,
    )


def _orchestrator(
    profiles: tuple[ModelProfile, ...],
    *,
    default: str = "ava/a",
    qualifications: tuple[ModelQualification, ...] = (),
) -> ModelOrchestrator:
    registry = ModelRegistry(profiles)
    return ModelOrchestrator(
        registry=registry,
        qualification_store=ModelQualificationStore(registry, qualifications),
        default_model_id=default,
    )


def test_explicit_model_is_authoritative_when_eligible() -> None:
    orchestrator = _orchestrator((_profile("ava/a"), _profile("ava/b")), default="ava/a")

    decision = orchestrator.select(ModelSelectionRequest(explicit_model_id="ava/b"))

    assert decision.model_id == "ava/b"
    assert decision.reason_code == "explicit_model"


@pytest.mark.parametrize(
    ("selection_request", "error"),
    [
        (ModelSelectionRequest(explicit_model_id="ava/missing"), ExplicitModelNotFoundError),
        (ModelSelectionRequest(explicit_model_id="ava/off"), ExplicitModelIneligibleError),
    ],
)
def test_explicit_invalid_model_never_falls_back(
    selection_request: ModelSelectionRequest, error: type[ValueError]
) -> None:
    orchestrator = _orchestrator((_profile("ava/a"), _profile("ava/off", enabled=False)))
    with pytest.raises(error):
        orchestrator.select(selection_request)


def test_explicit_model_rejects_hosting_capability_and_qualification() -> None:
    profile = _profile("ava/external", hosting=ModelHostingMode.EXTERNAL)
    orchestrator = _orchestrator((profile,))
    with pytest.raises(ExplicitModelIneligibleError) as hosting:
        orchestrator.select(
            ModelSelectionRequest(
                explicit_model_id="ava/external", hosting_requirement=ModelHostingRequirement.local_only()
            )
        )
    assert hosting.value.rejected_candidates[0].reason_code is ModelRejectionReason.HOSTING_MODE_NOT_ALLOWED

    with pytest.raises(ExplicitModelIneligibleError) as capability:
        orchestrator.select(
            ModelSelectionRequest(explicit_model_id="ava/external", required_capabilities=frozenset({"tool_calling"}))
        )
    assert capability.value.rejected_candidates[0].reason_code is ModelRejectionReason.CAPABILITY_MISSING

    with pytest.raises(ExplicitModelIneligibleError) as qualification:
        orchestrator.select(
            ModelSelectionRequest(
                explicit_model_id="ava/external", qualification_requirements=(QualificationRequirement("native_tool"),)
            )
        )
    assert qualification.value.rejected_candidates[0].reason_code is ModelRejectionReason.QUALIFICATION_MISSING


def test_partial_qualification_is_not_strict_pass() -> None:
    profile = _profile("ava/a")
    record = ModelQualification("ava/a", "native_tool", QualificationStatus.PARTIAL, "tool_calling")
    orchestrator = _orchestrator((profile,), qualifications=(record,))
    with pytest.raises(ExplicitModelIneligibleError) as error:
        orchestrator.select(
            ModelSelectionRequest(
                explicit_model_id="ava/a", qualification_requirements=(QualificationRequirement("native_tool"),)
            )
        )
    assert error.value.rejected_candidates[0].reason_code is ModelRejectionReason.QUALIFICATION_INSUFFICIENT


def test_auto_filters_then_prefers_default_and_stable_ids() -> None:
    orchestrator = _orchestrator(
        (
            _profile("ava/b", tools=True),
            _profile("ava/a"),
            _profile("ava/c", hosting=ModelHostingMode.EXTERNAL, tools=True),
        ),
        default="ava/a",
    )
    decision = orchestrator.select(
        ModelSelectionRequest(
            hosting_requirement=ModelHostingRequirement.local_only(),
            required_capabilities=frozenset({"tool_calling"}),
        )
    )
    assert decision.model_id == "ava/b"
    assert decision.candidate_model_ids == ("ava/b",)
    assert {item.reason_code for item in decision.rejected_candidates} == {
        ModelRejectionReason.CAPABILITY_MISSING,
        ModelRejectionReason.HOSTING_MODE_NOT_ALLOWED,
    }

    stable = _orchestrator((_profile("ava/z"), _profile("ava/b")), default="ava/missing")
    assert stable.select(ModelSelectionRequest()).candidate_model_ids == ("ava/b", "ava/z")


def test_default_ineligible_uses_next_eligible_and_no_eligible_is_typed() -> None:
    orchestrator = _orchestrator((_profile("ava/a", enabled=False), _profile("ava/b")))
    assert orchestrator.select(ModelSelectionRequest()).model_id == "ava/b"
    with pytest.raises(NoEligibleModelError) as error:
        _orchestrator((_profile("ava/a", enabled=False),)).select(ModelSelectionRequest())
    assert error.value.rejected_candidates[0].reason_code is ModelRejectionReason.MODEL_DISABLED
