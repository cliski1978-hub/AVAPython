"""Resolved execution configuration: the vocabulary Phase 5.16 introduces.

This module holds the *result* side of persisted-configuration resolution and
nothing else. It deliberately contains no repository import, no persistence
concern, and no adapter construction, so the execution boundary
(``ExecutionSelector``) can depend on the vocabulary without gaining a
dependency on configuration storage. The fan-out implementation lives in
``ava.execution.configuration_resolver``.

The central design decision is that resolution produces **existing execution
abstractions**, not a parallel set of persisted types:

* the runtime is an :class:`AgentRuntimePort` — the same object a bootstrap
  ``RuntimeResolver`` would return;
* the model provider is a :class:`ModelProviderPort`;
* the model is a :class:`ConfiguredModelBinding`, produced by the existing
  ``model_binding_from_profile`` derivation, never reimplemented here;
* the model profile is a :class:`ModelProfile`.

So a persisted run and a bootstrap run converge on one execution path, and the
runtime, orchestrator, resource manager, and runtimes cannot tell them apart.
That is the whole point: Phase 5.16 adapts persisted configuration *into* the
existing architecture rather than adding a second one beside it.

Two configured identities are carried explicitly because nothing else in the
result preserves them. ``runtime_configuration_id`` and
``provider_connection_id`` are the *configured instance* identities, and they
are deliberately different from the adapter identities the execution objects
report (``RuntimeInfo.runtime_id`` and ``ModelProfile.provider_id``). Losing
them would make a run impossible to attribute to the configuration that
selected it. ``model_id`` is not carried separately: ``model_binding.model_id``
already is that value, and duplicating it would invite the two drifting.

Nothing in this module carries a credential. The secret is revealed inside
provider construction and is never a field, a repr, or an error message here.
"""

from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol, runtime_checkable

from ava.agents.contracts import ExecutionConfigurationError
from ava.models.bindings import ConfiguredModelBinding
from ava.models.contracts import ModelProviderPort
from ava.models.model_registry import ModelProfile
from ava.runtimes.contracts import AgentRuntimePort

# ``ExecutionConfigurationError`` is re-exported rather than defined here.
# The failure is raised while resolving persisted execution, but it escapes
# through ``AgentPort`` to the run service, which must classify it into a
# durable error code. Both sides therefore depend on the same object, and the
# service is not allowed to import ``ava.execution`` to obtain it. The base
# lives with the port contract; every concrete subclass stays below. This is
# the same class object, so ``except`` clauses on either import path match.
__all__ = [
    "ExecutionConfigurationError",
    "ExecutionDefaultsNotConfiguredError",
    "ConfiguredReferenceMissingError",
    "ConfiguredReferenceDisabledError",
    "ModelProviderMismatchError",
    "CredentialResolutionFailedError",
    "ConfiguredModelIneligibleError",
    "ProviderConstructionFailedError",
    "RuntimeAdapterNotRegisteredError",
    "ProviderAdapterNotRegisteredError",
    "ExecutionConfigurationSource",
    "PersistedModelConfiguration",
]

# ============================================================
# BEGIN: Resolution Source
# ============================================================


class ExecutionConfigurationSource(StrEnum):
    """Where a run's execution configuration actually came from.

    Phase 5.8 established that AVA had four unrelated default mechanisms plus
    the new persisted one, and left the precedence question open. This enum does
    not settle precedence between *fields*; it records which mechanism supplied
    the selection that was used, so an operator can tell a persisted run from a
    bootstrap run without reading logs.
    """

    PERSISTED = "persisted"
    BOOTSTRAP = "bootstrap"


# ============================================================
# END: Resolution Source
# ============================================================


# ============================================================
# BEGIN: Persisted Execution Configuration
# ============================================================


@dataclass(frozen=True)
class PersistedModelConfiguration:
    """One configured model resolved for execution, without a runtime.

    The model axis of :class:`PersistedExecutionConfiguration`, split out because
    a run may name a model and leave the runtime on the persisted default. The
    provider connection is resolved here, so the caller receives an executable
    provider rather than a record it would have to assemble itself.
    """

    model_provider: ModelProviderPort = field(repr=False)
    model_binding: ConfiguredModelBinding
    model_profile: ModelProfile
    provider_connection_id: str

    @property
    def model_id(self) -> str:
        """The configured model identity, read from the binding's single carrier."""
        return self.model_binding.model_id


@dataclass(frozen=True)
class PersistedExecutionConfiguration:
    """One validated, ready-to-execute selection taken from persisted settings.

    Every field is an existing execution abstraction or a non-secret identity.
    Provider and runtime ports are excluded from repr regardless of their own
    implementations. This internal result is not a serialization contract; the
    provider owns its credential through the existing runtime-binding seam.

    This type is the *only* shape persisted resolution produces. The execution
    boundary maps it onto ``ResolvedExecution``; it does not branch on where the
    configuration came from.
    """

    runtime: AgentRuntimePort = field(repr=False)
    model_provider: ModelProviderPort = field(repr=False)
    model_binding: ConfiguredModelBinding
    model_profile: ModelProfile
    runtime_configuration_id: str
    runtime_type: str
    provider_connection_id: str

    @property
    def model_id(self) -> str:
        """The configured model identity, read from the binding's single carrier."""
        return self.model_binding.model_id


# ============================================================
# END: Persisted Execution Configuration
# ============================================================


# ============================================================
# BEGIN: Resolver Port
# ============================================================


@runtime_checkable
class PersistedExecutionConfigurationResolverPort(Protocol):
    """Read persisted application defaults and resolve them for one execution.

    The port exists so ``ExecutionSelector`` can depend on the capability
    without importing the persisted-defaults domain or any configuration
    repository. An architecture guard already requires the selector to stay
    unaware of both, and this protocol is how that is honored rather than merely
    asserted.

    Implementations must return ``None`` for exactly one situation: no persisted
    defaults have ever been configured. Every other outcome — a repository
    failure, a missing referenced record, a disabled record, an incompatible
    pairing, an unregistered adapter, a credential failure — is an error, and an
    error must never be reported as ``None``. Collapsing the two would silently
    downgrade a broken explicit configuration to bootstrap behaviour, which is
    precisely what Phase 5.16 is required to prevent.
    """

    @abstractmethod
    def resolve_persisted(self) -> PersistedExecutionConfiguration | None:
        """Resolve persisted defaults into an executable configuration.

        Returns:
            The resolved configuration, or ``None`` when no persisted defaults
            are configured and the caller should use its own bootstrap
            configuration.

        Raises:
            ExecutionConfigurationError: For any invalid or unusable persisted
                configuration. Never raised for the absent case.
        """
        raise NotImplementedError

    @abstractmethod
    def resolve_model_configuration(self, model_id: str) -> PersistedModelConfiguration | None:
        """Resolve one configured model by its stable ``model_id``.

        This is the seam that lets a per-run selection name a configured model
        rather than only a bootstrap catalog entry. It is deliberately a
        different answer from :meth:`resolve_persisted`: ``None`` here means
        "this id is not a configured model", which is a normal outcome a caller
        resolves against its other catalog. It never means "configuration
        broken".

        Returns:
            The resolved model, or ``None`` when ``model_id`` is not a configured
            model.

        Raises:
            ExecutionConfigurationError: When ``model_id`` *is* a configured model
                but it cannot be executed — a missing or disabled connection, an
                inconsistent pairing, an ineligible model, a missing adapter, or
                a credential failure. An unusable configured model must fail
                loudly rather than quietly fall back to another model.
        """
        raise NotImplementedError


# ============================================================
# END: Resolver Port
# ============================================================


# ============================================================
# BEGIN: Errors
# ============================================================


# ``ExecutionConfigurationError`` is imported and re-exported at the top of this
# module; only the concrete, persisted-configuration-specific failures are
# defined here.


class ExecutionDefaultsNotConfiguredError(ExecutionConfigurationError):
    """Persisted defaults were required but are absent.

    Distinct from a resolver returning ``None``: this is raised only by callers
    that require persisted configuration, never by the default-aware path. It
    exists so "I asked for persisted configuration and there is none" is not
    silently answered with a bootstrap default.
    """

    reason = "execution_defaults_not_configured"

    def __init__(self) -> None:
        super().__init__("Application execution defaults are not configured")


class ConfiguredReferenceMissingError(ExecutionConfigurationError):
    """A configured record named by the defaults does not exist.

    ``kind`` distinguishes which of the three configured domains is missing
    without needing three near-identical classes, and without a caller parsing
    the message to tell a missing runtime from a missing model.
    """

    reason = "configured_reference_missing"

    def __init__(self, kind: str, reference_id: str) -> None:
        self.kind = kind
        self.reference_id = reference_id
        super().__init__(f"Configured {kind} does not exist: {reference_id!r}")


class ConfiguredReferenceDisabledError(ExecutionConfigurationError):
    """A configured record named by the defaults exists but is disabled.

    Reported separately from the missing case because the operator's repair is
    different: a missing record must be created, a disabled one re-enabled. 5.8
    validated enablement on write, so reaching this state means the record was
    disabled *after* the default was saved.
    """

    reason = "configured_reference_disabled"

    def __init__(self, kind: str, reference_id: str) -> None:
        self.kind = kind
        self.reference_id = reference_id
        super().__init__(f"Configured {kind} is disabled: {reference_id!r}")


class ModelProviderMismatchError(ExecutionConfigurationError):
    """The default model does not belong to the default provider connection.

    Externally edited or restored records could violate the relationship even
    though normal repository writes forbid reassignment.
    """

    reason = "model_provider_mismatch"

    def __init__(self, model_id: str, provider_connection_id: str) -> None:
        self.model_id = model_id
        self.provider_connection_id = provider_connection_id
        super().__init__(
            f"Configured model {model_id!r} does not belong to provider connection "
            f"{provider_connection_id!r}"
        )


class RuntimeAdapterNotRegisteredError(ExecutionConfigurationError):
    """The runtime configuration exists, but its adapter type is not installed.

    This is the case Phase 5.14 made reachable on purpose: a
    ``RuntimeConfiguration`` may name a ``runtime_type`` AVA has no adapter for,
    because the Settings API does not validate runtime types against the
    installed set — a runtime that is temporarily unavailable must stay
    creatable and editable.

    Keeping it distinct from
    :class:`ConfiguredReferenceMissingError` is the point. "The runtime
    configuration is gone" and "the runtime is not installed right now" call for
    different responses, and collapsing them would either hide a broken reference
    or make a temporarily unavailable runtime look deleted. Neither may fall back
    to another runtime.
    """

    reason = "runtime_adapter_not_registered"

    def __init__(self, runtime_configuration_id: str, runtime_type: str) -> None:
        self.runtime_configuration_id = runtime_configuration_id
        self.runtime_type = runtime_type
        super().__init__(
            f"Runtime adapter type {runtime_type!r} for runtime configuration "
            f"{runtime_configuration_id!r} is not registered"
        )


class ProviderAdapterNotRegisteredError(ExecutionConfigurationError):
    """The provider connection exists, but its adapter type is not installed.

    The provider-side counterpart of
    :class:`RuntimeAdapterNotRegisteredError`, and reachable for the same
    reason: ``provider_id`` is not validated against the installed adapter set
    when a connection is saved.
    """

    reason = "provider_adapter_not_registered"

    def __init__(self, provider_connection_id: str, provider_id: str) -> None:
        self.provider_connection_id = provider_connection_id
        self.provider_id = provider_id
        super().__init__(
            f"Provider adapter type {provider_id!r} for provider connection "
            f"{provider_connection_id!r} is not registered"
        )


class CredentialResolutionFailedError(ExecutionConfigurationError):
    """The connection's credential reference could not be resolved to a secret.

    Wraps the credential layer's own failure without restating it. The message
    names the connection and nothing else: the underlying error already names
    only a reference *location*, and a run failure must not become a channel for
    secret-adjacent detail.
    """

    reason = "credential_resolution_failed"

    def __init__(self, provider_connection_id: str) -> None:
        self.provider_connection_id = provider_connection_id
        super().__init__(
            f"Credential for provider connection {provider_connection_id!r} could not be resolved"
        )


class ConfiguredModelIneligibleError(ExecutionConfigurationError):
    """The configured default violates model-selection policy."""

    reason = "configured_model_ineligible"

    def __init__(self, model_id: str) -> None:
        super().__init__(f"Configured model {model_id!r} is not eligible for execution")


class ProviderConstructionFailedError(ExecutionConfigurationError):
    """Provider construction failed without exposing adapter internals."""

    reason = "provider_construction_failed"

    def __init__(self, provider_connection_id: str) -> None:
        super().__init__(f"Provider connection {provider_connection_id!r} could not be constructed")


# ============================================================
# END: Errors
# ============================================================
