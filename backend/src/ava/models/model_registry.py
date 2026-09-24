"""AVA Model Registry v1: a read-only catalog of configured model profiles.

Step 40 introduces the first actual registry. It is deliberately descriptive:
it answers *what models does AVA know about?* — never *which model should this
task use?*. Orchestration, scoring, ranking, fallback, resource state, and
measured qualification remain future increments.

``ModelProfile`` is the single authoritative record for one configured model
deployment. ``ModelRegistry`` is an immutable, insertion-ordered index over
profiles keyed by the stable AVA ``model_id`` (Step 38). Execution identity is
derived from a profile through ``ava.models.bindings`` — there is no second
independently editable list of configured models.

The registry holds no credentials, endpoints, permissions, or runtime state.
Provider implementations and runtime implementations are never imported here;
connections are resolved separately through provider composition.
"""

import builtins
from collections.abc import Iterable
from dataclasses import dataclass, field

from ava.contracts.models import ModelCapabilities, ModelHostingMode

# ============================================================
# BEGIN: Model Registry Errors
# ============================================================


class UnknownModelError(ValueError):
    """An unknown or blank stable AVA model identity.

    Explicit, AVA-owned failure. Carries only the unresolved identity — never
    profile contents, provider internals, or credentials.
    """

    def __init__(self, model_id: str) -> None:
        self.model_id = model_id
        super().__init__(f"Unknown model: {model_id!r}")


class ModelDisabledError(ValueError):
    """A known model identity that is configured ``enabled=False``.

    Disabled means "not eligible for execution consideration". It says nothing
    about health, residency, or qualification. Exposed as a stable internal
    reason (``model_disabled``); the public run outcome stays sanitized.
    """

    reason = "model_disabled"

    def __init__(self, model_id: str) -> None:
        self.model_id = model_id
        super().__init__(f"Model is disabled: {model_id!r}")


# ============================================================
# END: Model Registry Errors
# ============================================================


# ============================================================
# BEGIN: Model Profile
# ============================================================


@dataclass(frozen=True)
class ModelProfile:
    """One configured model deployment in the AVA catalog (v1).

    Fields are intentionally minimal: stable identity, display label, provider
    deployment identity, hosting placement, *declared* capabilities, and an
    operational catalog flag. Future increments (lineage, licensing, measured
    qualification, resource state) will extend this type additively.

    Security: a profile never carries a shell/write/network/workspace/sandbox
    grant and never carries a credential. ``provider_model_name`` is a
    deployment-native label, not a secret — it is still kept out of the public
    API by default (see the discovery service).
    """

    model_id: str
    display_name: str
    provider_id: str
    provider_model_name: str
    hosting_mode: ModelHostingMode
    capabilities: ModelCapabilities = field(default_factory=ModelCapabilities)
    enabled: bool = True


# ============================================================
# END: Model Profile
# ============================================================


# ============================================================
# BEGIN: Model Registry
# ============================================================


def _validate(profile: ModelProfile) -> None:
    """Reject blank profile identity fields (fail fast at composition)."""
    for name in ("model_id", "display_name", "provider_id", "provider_model_name"):
        value = getattr(profile, name)
        if not value or not value.strip():
            raise ValueError(f"{name} must be a non-blank string")


class ModelRegistry:
    """Immutable, insertion-ordered catalog of configured ``ModelProfile``s.

    A pure descriptive container: it never scores, ranks, selects, loads, or
    mutates profiles. The stable ``model_id`` is the unique key. Duplicate
    identities fail fast at construction/composition. A profile's
    ``provider_model_name`` is *not* required to be globally unique — different
    AVA identities may intentionally alias the same provider deployment.
    """

    def __init__(self, profiles: Iterable[ModelProfile]) -> None:
        """Index the configured profiles by stable ``model_id``.

        Args:
            profiles: The configured model profiles.

        Raises:
            ValueError: If a profile has a blank identity field or two profiles
                share the same ``model_id``.
        """
        indexed: dict[str, ModelProfile] = {}
        for profile in profiles:
            _validate(profile)
            if profile.model_id in indexed:
                raise ValueError(f"Duplicate model_id: {profile.model_id!r}")
            indexed[profile.model_id] = profile
        self._profiles = indexed

    def get(self, model_id: str) -> ModelProfile | None:
        """Return the profile for ``model_id`` or ``None`` if unknown."""
        return self._profiles.get(model_id)

    def contains(self, model_id: str) -> bool:
        """Return whether a profile is configured under ``model_id``."""
        return bool(model_id) and model_id in self._profiles

    def list(self) -> builtins.list[ModelProfile]:
        """Return all configured profiles in insertion order."""
        return list(self._profiles.values())

    def enabled_models(self) -> builtins.list[ModelProfile]:
        """Return only profiles with ``enabled=True``, in insertion order."""
        return [profile for profile in self._profiles.values() if profile.enabled]


# ============================================================
# END: Model Registry
# ============================================================
