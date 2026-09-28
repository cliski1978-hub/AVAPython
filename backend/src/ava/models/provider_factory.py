"""Provider adapter construction port for configured provider connections.

Phase 5.16 needs a ``ModelProviderPort`` for a *persisted* connection, and the
existing ``ModelProviderRegistry`` cannot supply one: it holds provider
instances that were constructed once at startup, each already bound to a
specific endpoint and credential. Two connections to the same adapter therefore
need two instances, and neither can be the startup one.

This module defines the missing seam — a factory that constructs an adapter on
demand from a connection's non-secret connection data plus a resolved secret —
without letting any caller learn which concrete adapter is behind a
``provider_id``.

Why a port and not direct construction:

* **Provider construction stays in infrastructure.** The existing architecture
  guard allows ``ava.models.providers.openai_compatible`` to be imported only by
  its own package and by ``ava/infrastructure/composition.py``. Keeping
  construction behind this port preserves that: the resolver names a
  ``provider_id`` and receives a ``ModelProviderPort``, and never learns whether
  that id is served by an HTTP adapter, a subprocess, or something later.
* **No provider-specific branching escapes to callers.** A caller that needed to
  branch on ``provider_id == "openai_compatible"`` to build a provider would have
  re-imported the adapter and undone the boundary.
* **Secrets are revealed exactly once, at the construction boundary.** The
  factory receives a :class:`SecretValue` and is the last place the plaintext is
  available before it lives inside the adapter. Every layer above handles the
  wrapper or the constructed provider, never the plaintext.

The port deliberately takes the endpoint as an opaque optional string. Phase 5.2
kept ``ProviderConnection.endpoint`` opaque and optional, so this port does no
URL parsing, normalization, or validation, and it does not invent a default
endpoint. Infrastructure may apply an existing deployment default when the
connection omits its endpoint. Adapter-specific validation remains in the adapter.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from ava.models.contracts import ModelProviderPort
from ava.models.credentials import SecretValue

# ============================================================
# BEGIN: Errors
# ============================================================


class UnknownProviderAdapterError(ValueError):
    """A ``provider_id`` has no installed provider adapter.

    Distinct from every other provider-connection failure, and specifically
    distinct from "the connection record is missing" or "the connection is
    disabled": here the connection is perfectly valid and it names an adapter
    type this deployment has not installed.

    That state is *reachable by design*. The Settings API does not validate
    ``provider_id`` against the installed set, because a connection for an
    adapter that is temporarily unavailable must still be creatable and
    editable — the same reasoning Phase 5.14 applied to runtime types. So a
    connection can be configured for an adapter that does not exist, and the
    failure surfaces at execution time rather than at configuration time.

    Carries only the non-secret ``provider_id``. Never a resolved secret.
    """

    def __init__(self, provider_id: str) -> None:
        self.provider_id = provider_id
        super().__init__(f"Unknown provider adapter: {provider_id!r}")


# ============================================================
# END: Errors
# ============================================================


# ============================================================
# BEGIN: Model Provider Factory
# ============================================================


class ModelProviderFactory(ABC):
    """Construct a ``ModelProviderPort`` for one configured connection.

    Implementations own the concrete adapter and its construction details. A
    caller supplies the connection's non-secret data and, when the connection
    declares one, an already-resolved :class:`SecretValue`.

    The ``credential`` argument is ``None`` for a credential-free connection,
    and implementations must construct an unauthenticated adapter in that case
    rather than substituting a placeholder. Blank-secret handling is the
    credential resolver's decision, made before this call.
    """

    @abstractmethod
    def create(
        self,
        *,
        provider_id: str,
        endpoint: str | None,
        model_name: str,
        credential: SecretValue | None,
    ) -> ModelProviderPort:
        """Construct a provider adapter for one connection.

        Args:
            provider_id: The connection's provider adapter identity. The
                implementation reports it through the adapter's ``name()``.
            endpoint: The connection's opaque endpoint, or ``None`` when the
                connection declares none. Passed through unchanged; no URL
                parsing or normalization happens here.
            model_name: The provider-native model name the adapter should
                target by default.
            credential: The resolved secret for this connection, or ``None``
                when the connection declares no ``credential_reference``. The
                only legitimate consumer of the plaintext is the adapter's own
                construction.

        Raises:
            UnknownProviderAdapterError: If this factory does not serve
                ``provider_id``.
        """
        raise NotImplementedError


# ============================================================
# END: Model Provider Factory
# ============================================================
