# AVA Test Environment Isolation

Backend tests must produce the same result regardless of the developer's
repository-root `.env`. This records how that guarantee is established, and the
contamination that previously broke it.

## Symptom

A developer's `.env` selects real storage:

```text
AVA_PERSISTENCE=relational
AVA_ATTACHMENT_STORAGE=local
```

During a **full** `pytest` run, tests asserting AVA's default in-memory profile
failed — `test_persistence_activation`, `test_documents`, `test_conversations`,
`test_attachments`, and neighbours. The **same tests passed when run
individually**, and the failure count moved with collection order (11–18
failures between runs).

## Root cause

AVA's `Settings` is a plain dataclass. Every field uses a `default_factory`
lambda that reads `os.environ` **at instantiation time**, and `Settings` never
reads a `.env` file itself. The process environment is therefore the only
configuration source, and whatever is in it when a test constructs `Settings()`
is what the test observes.

The environment was not being left alone. Importing the OpenHands SDK transitively
imports `litellm`, whose module body calls `load_dotenv()`:

```text
ava/runtimes/adapters/openhands/qualification.py:21
  -> ava/runtimes/adapters/openhands/controlled_terminal.py:15
    -> openhands/sdk/__init__.py:5
      -> ... -> openhands/sdk/logger/logger.py:16
        -> litellm/__init__.py:27
          -> dotenv/main.py:429  load_dotenv()
            -> dotenv/main.py:108  set_as_environment_variables  -> os.environ mutated
```

`load_dotenv()` defaults to `override=False`, so it writes every key from the
nearest `.env` into the **global process environment**. Because
`ava/runtimes/adapters/openhands/*` imports the SDK at module scope, merely
*collecting* a test module that touches the OpenHands adapter loads the
repository-root `.env` into the pytest process.

Confirmed directly: `os.environ["AVA_PERSISTENCE"]` was `None` at
`pytest_configure` and `relational` by the end of collection, with
`AVA_ATTACHMENT_STORAGE=local` alongside it.

- **`os.environ` was mutated**: yes, in-process and globally, at import time.
- **Settings cache involvement**: secondary. `ava.configuration.settings` also
  memoizes one instance in a module-level `_settings` behind `get_settings()`,
  so a cached instance could outlive the test that created it — a real but
  separate leak, not the cause of these failures.
- **Settings singleton**: the cache is a module global, not `lru_cache`, and
  there is no public reset API.

### Why isolated tests passed and full-suite tests failed

Running one file collects one module. Unless that module imports the OpenHands
SDK, `load_dotenv()` never runs, the environment stays clean, and the test sees
the memory profile. A full run collects the OpenHands tests too, so the
environment was already rewritten before any test body executed — every later
`Settings()` then read relational. Nothing about the assertions changed; only
what the process had inherited.

## Fix

`backend/conftest.py` — the suite's environment boundary. At conftest import
time (before pytest imports any test module, and therefore before `litellm` is
ever imported) it assigns every `AVA_*` variable the settings layer reads to the
value AVA documents as its default, with `AVA_PERSISTENCE=memory` and
`AVA_ATTACHMENT_STORAGE=memory`.

This works because of two properties, not by luck:

1. conftest is imported before test modules, so the values exist first;
2. `load_dotenv(override=False)` never overwrites a variable that is already
   set, so the SDK's import-time load becomes a no-op for every key AVA reads.

The assignment is unconditional, not `setdefault`: a developer's *exported*
`AVA_PERSISTENCE` is exactly the contamination being removed.

A second autouse fixture clears the cached `Settings` singleton before and
after every test, so no test inherits another's resolved configuration, and
restores the previous value on exit.

The two filesystem settings (`AVA_PERSISTENCE_DATABASE_URL`,
`AVA_ATTACHMENT_STORAGE_ROOT`) point at `tempfile.gettempdir()`, so a test that
opts into durable storage without naming a path no longer creates
`backend/ava.sqlite3` or `backend/.ava/` as a side effect of a run.

## Why this fix and not another

- **Not a production change.** Nothing in `src/ava` moved. Development startup
  loads the repository `.env` through `scripts/dev_backend.sh` and exports it
  into the server process, exactly as before, and a process that imports the
  OpenHands SDK still picks the file up.
- **Not `if "pytest" in sys.modules`.** The task's brief rules that out, and
  rightly: a production module that knows about pytest is a worse dependency
  than a test module that knows about configuration.
- **Not removing `.env` support.** That would break local development to serve
  the test suite.
- **Not clearing the cache alone.** A freshly built `Settings` re-reads the same
  polluted environment; the configuration source had to be fixed first.
- **Not patching `litellm` or pre-importing the SDK.** Setting the variables is
  smaller, and it holds for any future import-time dotenv load rather than this
  one dependency's.

## How tests request other modes

Isolation is a default, not a prohibition. Both established mechanisms work
unchanged:

```python
Settings(persistence_provider="memory")                        # explicit injection
monkeypatch.setenv("AVA_PERSISTENCE", "relational")            # environment override
```

`monkeypatch` wins over the conftest values and restores them on teardown, so a
relational test, a local-attachment test, and an ordinary memory test coexist in
one run. The cache fixture runs around the override, so a test that populates the
singleton cannot affect its neighbours.

## Regression tests

`backend/tests/test_environment_isolation.py` — 11 tests:

| Test | Guards |
| --- | --- |
| `test_the_suite_defines_its_own_configuration` | every `AVA_*` key is stated by the harness, so a new `Settings` field without an entry fails loudly |
| `test_ordinary_settings_use_the_in_memory_profile` | the memory profile is what an ordinary test gets |
| `test_importing_the_openhands_sdk_cannot_change_the_configuration` | the original mechanism is inert |
| `test_the_suite_never_writes_persistence_state_into_the_repository` | no repo-relative storage paths |
| `test_a_repository_env_cannot_reach_the_backend_test_configuration` | a hostile `.env` in a temp CWD loses to the harness, even after the SDK import (subprocess) |
| `test_production_startup_still_honours_the_repository_env` | the same `.env` still configures a bare process (subprocess) |
| `test_a_cached_settings_instance_cannot_outlive_its_test` | the cache reset works when exercised directly |
| `test_configuration_does_not_depend_on_what_was_resolved_first` | memory → relational → memory, both directions |
| `test_explicit_settings_construction_bypasses_the_environment` | injection stays the primary mechanism |
| `test_a_test_can_still_opt_into_relational_persistence` | relational composition still works and is durable |
| `test_a_test_can_still_opt_into_local_attachment_storage` | local content store still works |

The subprocess cases are required rather than decorative: the contamination
happened during collection, so an in-process test body runs strictly too late to
observe it. With the conftest fix disabled, 5 of the 11 fail — including the
hostile-`.env` case.

## Validation

Run with the repository-root `.env` present and unmodified:

```text
Full backend suite:  1679 passed, 2 skipped
Hostile .env swapped in:  1679 passed, 2 skipped
Hostile values exported in the shell:  1679 passed, 2 skipped
Previously failing files, run individually:  all passed
ruff check:  All checks passed
mypy (src + conftest + new tests):  Success, no issues found
git diff --check:  clean
```

Unchanged by this work: persistence repository semantics, SQLite behaviour,
attachment storage behaviour, Settings API behaviour, execution configuration,
application defaults, bootstrap seeding, and frontend behaviour.
