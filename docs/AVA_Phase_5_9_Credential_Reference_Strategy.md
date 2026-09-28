# AVA Phase 5.9 — Credential Reference Strategy

Phase 5.9 defines how AVA moves from a persisted
`ProviderConnection.credential_reference` to secret material that only provider
infrastructure ever sees. It adds the AVA-owned vocabulary (reference syntax,
secret wrapper, resolver port) and exactly one backend — the environment.

Nothing about live execution changed. No provider is wired to a persisted
credential, no Settings API or UI exists, and no schema changed.

## 1. Current credential flow discovered

The audit's headline finding: **there is no credential flow.** The field exists
and is inert.

- `Settings` (`ava/configuration/settings.py`) declares **zero** credential
  fields. No API key, token, password, or secret is read from the environment
  anywhere in `ava/`.
- `ProviderConnection.credential_reference` is written and read by exactly one
  place: `RelationalProviderConnectionRepository`, as a column round trip. No
  other module reads it. It is persisted, validated as non-blank, and otherwise
  ignored.
- `composition._create_local_model_provider` hardcodes `api_key=None`, so the
  local OpenAI-compatible provider is always unauthenticated.
- The only non-`None` key in the codebase is a **placeholder**: the OpenHands
  adapter substitutes `_LOCAL_PLACEHOLDER_API_KEY = "local-ava"` whenever
  `binding.api_key` is `None` or blank
  (`runtimes/adapters/openhands/openhands_runtime.py:23-28`). It is also
  hardcoded in `qualification.py`. This exists because the OpenHands SDK's
  `LLM` constructor requires a non-empty `api_key` even for a local,
  unauthenticated endpoint.
- Secret material, once it exists, travels in one internal-only carrier:
  `RuntimeModelBinding.api_key` (`ava/models/bindings.py:209-225`), documented
  as "INTERNAL ONLY … must never be serialized to clients". It is populated
  from `OpenAICompatibleModelProvider._api_key` via
  `create_runtime_model_binding`, consumed by the OpenHands adapter, and
  turned into `Authorization: Bearer <key>` at
  `openai_compatible/provider.py:362-363`.
- Error text is already credential-safe: `ModelProviderError` and
  `ModelProviderPort` docstrings state messages never include credentials, and
  the 401 path emits "The OpenAI-compatible endpoint rejected the configured
  credentials" with no key material.

So the pre-5.9 state is: an opaque column with no reader, one hardcoded
placeholder, and an internal-only string carrier already in place. Phase 5.9's
job was to give that column a *meaning* and a *one-way* escape hatch, not to
build the path that already exists for a real key.

## 2. Credential-reference syntax

```text
credential_reference := scheme ":" location
```

`CredentialReference.parse` enforces that shape and nothing more. The location
stays opaque to AVA core; only the resolver that owns the scheme interprets it.
`text()` returns the canonical form, which is exactly what
`ProviderConnection.credential_reference` stores.

```text
CredentialReference(scheme="env", location="OPENAI_API_KEY")
```

Only `env` is implemented. `aws-secrets:`, `azure-keyvault:`, `databricks:`,
and `vault:` all parse successfully as *syntax* and are then rejected by the
environment resolver as unsupported. That split is deliberate: the parser owns
grammar, the resolver owns availability. A future backend therefore needs no
change to the parser, to `ProviderConnection`, or to the port.

Rejected as malformed (`CredentialReferenceError`): blank text, text with no
`:` separator, `":NAME"`, `"env:"`, `"env:   "`. Surrounding whitespace is
trimmed, so `"  env:OPENAI_API_KEY  "` round-trips to the canonical text.

## 3. The resolver port

`ava.models.credentials.CredentialResolver` — an ABC with one method:

```text
resolve(reference: str) -> SecretValue
```

The port takes the reference **exactly as stored** (`str`), not a parsed
`CredentialReference`. That keeps the port free of grammar: the caller does not
have to know the syntax, and an implementation is free to route on the raw
text. No backend type, no client, no SDK, no environment mapping appears in the
signature. Its module imports only `abc`, `dataclasses`, `hmac`, and
`ava.models.provider_connections` (plus `from __future__ import annotations`) —
asserted by test.

`resolve_connection_credential(connection, resolver)` is the single seam where
a persisted record meets secret material. It returns `None` for a
credential-free connection and never calls the resolver in that case.

Placement: the vocabulary lives in `ava/models/credentials.py`, beside the
`ProviderConnection` that stores the reference. It is deliberately **not** in
`ava/repositories/` — a credential resolver performs no persistence, and
putting it there would have required widening the repository import guards
that 5.3–5.8 tightened.

## 4. Secret-value representation

`SecretValue` was judged worth adding. The pre-existing style
(`api_key: str | None` plus a docstring saying "never serialize") relies on
every future author reading that docstring; a wrapper makes the safe path the
default one.

It is a plain class with `__slots__`, deliberately **not** a dataclass, because
auto-generated `__repr__` and `__eq__` are exactly the leak paths it exists to
close. The surface is four members:

| Member | Behavior |
| --- | --- |
| `reveal() -> str` | The one deliberate exit for the plaintext. |
| `__repr__` | `SecretValue(***)` |
| `__str__` | `***` |
| `__eq__` | Compares via `hmac.compare_digest`; returns `NotImplemented` for non-`SecretValue`. |
| `__hash__` | Raises `TypeError` — hashing would let a secret be confirmed by brute force. |
| `__bool__` | Always `True`; emptiness is a property of the secret, not the reference, and resolvers reject blank values before wrapping. |

No `to_dict`, no `__json__`, no comparison-by-length signal. `SecretValue`
requires a `str`; bytes raise `TypeError`, so a `repr(bytes)` can never be
wrapped by accident.

## 5. Environment resolver

`ava/infrastructure/credentials.py` holds `EnvironmentCredentialResolver`. It
is **infrastructure-side** by design: a secret backend is a place where
credential material physically exists, so it must not be importable from core,
contracts, models, services, repositories, runtimes, or agents. Keeping it
here also keeps `os.environ` out of the domain, where a persisted reference has
no business reading the process environment.

```text
env:NAME -> os.environ["NAME"] -> SecretValue(value)
```

It takes an optional `Mapping[str, str]`, defaulting to `os.environ`. That
injection is what lets the tests exercise every branch without mutating the real
process environment.

Blank values are an error, not a pass-through. The justification is behavioral,
not stylistic: the OpenAI-compatible adapter builds its header with
`if self._api_key is not None: headers["Authorization"] = f"Bearer {self._api_key}"`,
so a whitespace key produces a degenerate `Bearer` header — asserted by a test
that captures a real request. The OpenHands adapter likewise treats a blank key
as "use the local placeholder", which silently changes deployment behavior.
Both mean a blank secret is a misconfiguration, so the resolver refuses it
rather than handing provider infrastructure a value that will not work.

Resolution never degrades to `None`. A caller wanting an unauthenticated
provider asks for a connection with `credential_reference = None`; it does not
receive a silent empty secret from a reference that was supposed to resolve.

## 6. Credential-free connections

`ProviderConnection.credential_reference` stays `str | None`, and `None` remains
valid. The local Ollama/vLLM development path therefore keeps working with no
environment variable at all. A test drives this with a resolver that raises
`AssertionError` on any call, proving `resolve_connection_credential` returns
`None` **without invoking the resolver** — not merely that the resolver tolerates
being called. Another test resolves a local connection against an empty
environment and constructs a real provider with `api_key=None`, then asserts its
runtime binding carries no key.

## 7. Error model

All five errors subclass AVA's own `CredentialError`, so a caller can catch the
family without knowing the backend.

| Error | Raised when | Example message |
| --- | --- | --- |
| `CredentialReferenceError` | text is blank, has no `:`, or has a blank scheme/location | `Credential reference must name a scheme, as in 'env:OPENAI_API_KEY'` |
| `UnsupportedCredentialSchemeError` | scheme is well-formed but this resolver does not serve it | `Credential scheme is not supported by the environment resolver: aws-secrets` |
| `CredentialNotFoundError` | the environment variable is unset | `Credential environment variable is not set: OPENAI_API_KEY` |
| `BlankCredentialError` | the variable holds only whitespace | `Credential environment variable is blank: OPENAI_API_KEY` |
| `CredentialError` | base for all of the above | — |

Messages name the **reference location** (a variable name, never a value). Four
tests assert the message text is stable and safe, and a `caplog` test asserts a
resolved secret never reaches a log record even when passed to `logger.debug`
with `%r`/`%s`.

## 8. Why secret values are not persisted

There is no table, column, or migration for secret material, and none was
needed — `credential_reference` already existed, so **no schema change was
required at all** in Phase 5.9.

Three tests hold the line: `provider_connections` has no
`credential_value`/`api_key`/`password`/`token`/`secret` column; no migration
declares a `TEXT`/`VARCHAR`/`BLOB` column with any of those names; and
`dataclasses.asdict` of a connection with a reference set contains
`credential_reference` and the reference, and not the secret.

The reference is the *only* thing that round-trips through persistence, which
keeps rotation a one-step operation: change the environment variable, and every
connection referencing it picks up the new value on next resolution. A cached
denormalized copy would silently desynchronize — the specific risk flagged in
Phase 5.8's documentation, now closed.

## 9. Provider integration point (for Phase 5.16)

The path, and what already exists versus what is new:

```text
ProviderConnection
        ↓  resolve_connection_credential(connection, resolver)
SecretValue | None
        ↓  .reveal()  — the only reveal, at provider construction
OpenAICompatibleModelProvider(api_key=...)
        ↓  create_runtime_model_binding(...)  [pre-existing, internal-only]
RuntimeModelBinding.api_key
        ↓  Authorization: Bearer <key>       [pre-existing]
provider / OpenHands LLM
```

The last three steps already existed and are unchanged. Phase 5.9 supplies the
top two and the redaction wrapper. One isolated test proves the seam end to end
— resolve a reference, `.reveal()` into a real provider constructor, assert the
provider's internal binding carries it — and it is deliberately not referenced
by any composition function, so **persisted provider connections are not
authoritative for live runs**.

Phase 5.16 will own the decision about *when* a run resolves a credential. Two
constraints it inherits: resolution is a per-run concern, not a startup one
(secrets must not be loaded at boot just to construct a registry), and the
reveal must stay inside provider construction rather than flowing back up into
a domain record.

## 10. Enterprise compatibility

`CredentialResolver` is an ABC with one method, so adding AWS Secrets Manager,
Azure Key Vault, Databricks Secrets, or a corporate vault means adding a class
in `ava/infrastructure/credentials.py` (or a sibling module) and nothing else.
`ProviderConnection`, `CredentialReference`, the port, `ModelConfiguration`,
`RuntimeConfiguration`, and every public contract stay byte-identical.

Two details make that scale without redesign:

1. **Grammar is already backend-neutral.** `aws-secrets:prod/openai` parses
   today and is rejected as *unsupported*, not as *malformed*. A second
   implementation slots in with no parser change.
2. **Multi-backend routing is the one thing 5.9 declines to build.** A later
   deployment may want `env:` for local development and a vault scheme in
   production for the same connection. A `ChainedCredentialResolver` that
   dispatches on `CredentialReference.scheme` is the natural addition, and it
   needs no change to anything in this phase. Building it now would have meant
   guessing at routing, caching, and failure-precedence rules that no
   requirement states.

Each backend will own its own reachability and retry policy; the port stays
synchronous and does not express them, so a network-bound vault backend is
added behind a resolver rather than by widening the contract every caller uses.

## 11. Tests

`backend/tests/test_credentials.py` — 56 tests, grouped by the concern they
protect:

- **Reference syntax** — parse/round-trip, surrounding whitespace, seven
  malformed inputs, blank scheme/location on direct construction, and future
  schemes parsing through the same grammar.
- **SecretValue** — reveal-only access, redacted `repr`/`str`/f-string/
  interpolation, unhashable, non-string rejected, equality without repr leak,
  and an explicit assertion that it is not a dataclass.
- **Environment resolver** — resolution, process-environment default, unset
  variable, three blank values, malformed reference, four unsupported schemes,
  no fallback lookup under an unsupported scheme, shared error base, and
  no-`None`-on-failure.
- **Error and log safety** — every failure message captured and asserted free
  of secret material, names the variable, a `caplog` test with `%r`/`%s`, and a
  traceback rendering check.
- **Credential-free connections** — no reference needed, resolver never invoked
  (exploding-resolver test), resolution through the same seam, and a real local
  provider constructed with no key.
- **Provider seam** — the isolated `reveal()`-into-provider proof, and that
  `RuntimeModelBinding` keeps its documented internal-only `api_key` field with
  no `api_key` anywhere in `ava/contracts/`.
- **No secret persistence** — round-trip stores the reference, the table has no
  secret column, no migration declares one, and `asdict` serialization carries
  the reference but not the secret.
- **Architecture boundaries** — `ProviderConnection` declares no resolved
  secret field, `ModelConfiguration`/`RuntimeConfiguration` declare no
  credential fields, the credentials module imports nothing SDK-shaped, the
  environment resolver stays infrastructure-side, `run_service.py` never
  mentions credential resolution, no contract or repository module mentions
  `SecretValue`/`CredentialResolver`/`reveal(`, and the exports are reachable
  from `ava.models`.

`backend/tests/test_architecture.py` — three narrow additions mirroring the
cross-cutting invariants: secret backends are infrastructure-only,
`RunService → AgentPort` gains no credential dependency, and no migration may
introduce a secret-bearing column.

## 12. Validation

```text
pytest tests/test_credentials.py tests/test_provider_connection_repository.py \
       tests/test_execution_defaults.py tests/test_openai_compatible_model_provider.py \
       tests/test_architecture.py tests/test_persistence_migrations.py \
       tests/test_model_configuration_repository.py \
       tests/test_runtime_configuration_repository.py tests/test_settings.py -q
328 passed

pytest tests/test_credentials.py tests/test_architecture.py -q
143 passed

ruff check src tests
All checks passed!

mypy src
Success: no issues found in 165 source files

git diff --check
Clean
```

Full backend suite: **1485 passed, 2 skipped, 0 failed** with the
repository-root `.env` neutralized (`AVA_PERSISTENCE=memory
AVA_ATTACHMENT_STORAGE=memory`); the 5.8 baseline under the same environment was
1427 passed.

The known `.env` order sensitivity is unchanged: with that file left as-is, the
full run reports **11 failed, 1474 passed** — the same 11 pre-existing
failures, all in tests that assert in-memory default composition while the
`.env` selects relational persistence. No credential test participates, and the
neutralized run is clean, so the 11 remain baseline-only.

## 13. Implications for 5.10 and 5.16

**5.10 (Settings API).** Nothing to change, one constraint to respect: a
provider-connection endpoint must accept and return `credential_reference`
verbatim and must never return resolved material. The reference is safe to
expose — that is the point of making it a location rather than a secret — so
5.10 needs no redaction logic on this field, and no endpoint should call
`resolve()`. If 5.10 wants to show a user whether a credential *resolves*, that
is a boolean derived from catching `CredentialNotFoundError`/`BlankCredentialError`
and discarding the message, not a returned value. 5.10 will also be the first
code allowed to *write* `credential_reference` from user input, so
`CredentialReference.parse` is the validation to apply on input rather than
accepting arbitrary text.

**5.16 (execution configuration resolver).** Three things to build on:

1. Resolve per run, not at startup. The resolver is constructed with an
   injectable environment mapping, so a run can resolve against a
   process-scoped snapshot if one is ever needed.
2. Reveal exactly once, inside provider construction. `resolve_connection_credential`
   already returns `None` for credential-free connections, so a resolver that
   handles both authenticated and local providers needs no separate path.
3. Expect a record to be disabled *after* a default referenced it. 5.9 rejects
   disabled references at write time; nothing re-validates at read time, so a
   disabled connection with a still-valid reference will still resolve. That is
   a read-time concern for 5.16, not a 5.9 gap.

The precedence question Phase 5.8 left open — persisted default versus
environment value — remains 5.17's, and 5.9 does not narrow it.
