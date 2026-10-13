# AVA Phase 6.11 — Initial Tool Implementations

## Outcome and status

Phase 6.11 adds three AVA-owned, versioned, read-only Workspace tool
definitions, a tested Linux local-filesystem adapter, and a Windows-native
handle-based adapter implementation. The definitions are registered
explicitly, but remain disabled by the master feature gate and individual tool
gates. The production `ToolExecutionService` still has no trusted
execution-authority issuer, executor mapping, or durable invocation
reservation adapter, so production dispatch remains unavailable.

Linux adapter behavior passed the focused functional and adversarial tests on
the current Linux host. Windows handle-based implementation and native
security tests are now present, but the Windows tests could not run because no
Windows host or verified remote workflow target was available in this
environment. **Phase 6.11 acceptance is PARTIAL** until mandatory Windows
Actions validation passes. Do not claim certified local Windows, Windows EC2,
or Windows Azure VM Workspace access before that validation.

The owner-supplied Phase 6.11 briefs govern this work. The checked-in
`AVA_PHASE_6_IMPLEMENTATION_OUTLINE.md` retains historical numbering that calls
6.11 persistence/Run Inspector and 6.12 final validation; the supplied 6.11
brief instead assigns initial tools. The outline and owner-locked canonical
plan were left unchanged.

## Implemented catalog and contracts

The catalog registers these definitions through `ToolRegistry` during trusted
backend composition:

| Tool ID | Version | Input | Output | Capability/effect |
|---|---:|---|---|---|
| `workspace.list_files` | `1` | Required relative `path`; optional `limit` (1–100) and decimal `cursor` | Sorted entry names, file/directory type, bounded metadata, optional next cursor | `FILE_READ` / `READ` |
| `workspace.read_file` | `1` | Required relative `path`; optional `max_bytes` (1–1,048,576) | UTF-8 text, encoding, truncation flag, bounded size metadata | `FILE_READ` / `READ` |
| `workspace.file_info` | `1` | Required relative `path` | Regular-file type, bounded size metadata, UTC modification time | `FILE_READ` / `READ` |

Schemas use the existing Phase 6.2 JSON-schema subset and reject undeclared
arguments. Definitions carry no write, delete, command, network, or
administrative capability. Registration is deterministic, explicit, and
duplicate-safe. Registration is descriptive metadata; it does not enable a
tool or grant authority. Missing configuration leaves the framework and all
three tools disabled.

Tool-specific read options are accepted by the policy parser only after the
definition's schema has rejected unknown fields. `workspace.list_files` is
classified as a directory read during preflight; other initial tools require a
regular file. Preflight is still only eligibility. The normalized execution
service repeats current feature, authority, Workspace, policy, run, approval,
and reservation checks before it can call an executor.

## Execution boundary and adapter port

`AuthorizedToolInvocation` now carries the server-resolved immutable
`RuntimeWorkspaceBinding` alongside its Workspace identity. It remains
constructible only through the `ToolExecutionService` proof boundary. The
filesystem adapter accepts that service-created value; it has no client API for
an absolute root, Workspace identity, execution host, resource provider,
model, or runtime selection.

The platform-neutral `WorkspaceFilesystemSecurityPort` is under AVA's tool
boundary. `WorkspaceReadExecutor` enforces the Chat-mode denial and delegates
to the port. Host-specific filesystem behavior is confined to infrastructure.
Backend composition selects an adapter from the backend execution host; there
is no browser/client platform selector. Unsupported hosts return a normalized
unavailable result. No SDK, cloud-storage client, OS syscall, or Databricks
dependency enters the tool contracts, registry, execution service, policy,
approval, RunService, or AgentPort.

The existing separation remains:

| Concept | Meaning in this phase |
|---|---|
| Execution host | The OS/process where AVA backend adapter code runs. Host adapter selection is server-side. |
| Resource provider | The system that stores a resource. Only the local filesystem provider is implemented. |
| Authorized Workspace | The security-scoped resource identity and current authority assigned to the run/caller. A Workspace is not inherently a local directory. |

Existing `RuntimeWorkspaceBinding.local_path` and `WorkspaceResolver` semantics
continue to represent local filesystem Workspaces. They were not reinterpreted
or migrated. The minimum future extension point is to evolve trusted Workspace
resolution into a provider-qualified canonical resource binding with a
configuration revision, then add provider-specific infrastructure adapters.
Remote resource identifiers must never be coerced into `local_path`.

## Linux local filesystem design

The Linux adapter was exercised on Linux 6.8, x86_64. It opens and pins the
configured canonical Workspace root, compares the opened directory identity to
the current configured path identity, and checks the root filesystem type.
Only ext2/3/4, XFS, Btrfs, overlayfs, and tmpfs root filesystems are accepted.
Proc/sys/device/security filesystems, network and FUSE filesystems, unknown
filesystem types, and roots on unsupported filesystem providers fail closed.
tmpfs is treated as a local ephemeral filesystem and provides no durability.

Every relative lookup uses Linux `openat2` from the pinned root or directory
descriptor with `RESOLVE_BENEATH`, `RESOLVE_NO_SYMLINKS`,
`RESOLVE_NO_MAGICLINKS`, and `RESOLVE_NO_XDEV`. There is no `Path.resolve()` plus
`open()` fallback. Unsupported kernel/syscall/security capabilities fail
closed. Paths reject absolute and drive-qualified forms, `.`/`..` segments,
empty segments, NUL, backslash, and invalid UTF-8; the root marker `.` is
accepted only for directory listing. Entry access uses
opened-object metadata, rejects symlinks, mount crossings, non-regular files,
special files, and files with multiple hard links. Directory roots and file
handles close in `finally` blocks.

Reads are capped at 1 MiB. A valid UTF-8 prefix is returned when truncation
splits a multibyte code point; invalid UTF-8 elsewhere returns a stable
`decode_failure`. Listings sort valid Unicode names, return at most 100 entries
per page, and inspect at most 10,000 names per request. Oversized directories
return `directory_too_large`. Pagination is offset-based and is not a snapshot
if the Workspace is concurrently modified. No operation creates, modifies, or
deletes a file. Adapter errors are normalized and do not include host paths or
raw exception text.

The bounded read/list work runs synchronously inside the adapter after an
async cancellation checkpoint. Cancellation before the adapter starts
propagates through the execution service and closes any opened handles. Since
there is no await during an individual bounded system call, cancellation cannot
interrupt a blocked kernel/filesystem operation; this remains a limitation for
slow or unhealthy filesystems.

Hard-link count greater than one is rejected, but link-count checks cannot
establish historical file provenance if filesystem state changes concurrently.
`openat2` contains child resolution beneath the pinned Workspace descriptor and
blocks mount crossings below it; it does not isolate a privileged process from
other host-level actors that can mutate mounts or replace the configured root.
The adapter does not inspect file contents for credentials; any such
classification/redaction policy remains a separate security requirement, and
production dispatch stays unavailable.
Workspace/authority revocation is revalidated at the execution-service
boundary, but revocation cannot be made atomic with a subsequent filesystem
read using the current authority contract. These residuals are another reason
production dispatch remains disabled.

## Windows support

`WindowsWorkspaceFilesystemAdapter` targets local fixed NTFS volumes and uses
`CreateFileW`, `NtCreateFile`, `GetFileInformationByHandleEx`,
`GetFinalPathNameByHandleW`, `NtQueryDirectoryFile`, and `ReadFile`. It opens
the configured root by walking from the local drive root one component at a
time, rejects reparse points at every component, checks root file identity
again against a fresh handle, and performs later traversal relative to open
directory handles. Each opened directory and file omits `FILE_SHARE_DELETE` to
prevent replacement while its handle is in use. Metadata and reads come from
opened handles; directory enumeration is handle-based. Files with more than
one hard link, alternate data streams, absolute/drive-relative/UNC/device
paths, unsafe names, special files, and reparse points are rejected. There is
no `Path.resolve()` plus `open()` fallback.

The adapter rejects non-NTFS and non-fixed volumes, including network shares
and unsupported filesystems, and fails closed when native APIs are unavailable.
It pins objects and prevents rename/replacement while handles remain open; it
does not provide a transactional snapshot against a local writer with write
sharing, nor can it prevent privileged host actors from changing filesystem
contents. Native Windows review and execution remain required. Windows tests
are **not validated** and must not be counted as passing based on Linux
compilation or mock behavior.

## Deployment architecture and support matrix

| Environment | Local filesystem adapter | Additional requirements |
|---|---|---|
| Windows workstation | Adapter implemented; **not yet certified** | Native Windows security validation required; production dispatch remains unavailable |
| Linux workstation | Linux `openat2` adapter on supported local filesystems | Kernel/security-capability probe; current-host tests passed |
| Windows EC2 | Adapter implemented; **not yet certified** | Same native Windows validation; host hardening |
| Linux EC2 | Linux `openat2` adapter on supported local filesystems | Host hardening, supported kernel/filesystem, durable production state |
| Windows Azure VM | Adapter implemented; **not yet certified** | Same native Windows validation; host hardening |
| Linux Azure VM | Linux `openat2` adapter on supported local filesystems | Host hardening, supported kernel/filesystem, durable production state |
| Databricks notebook client | Adapter on the AVA backend host | Notebook calls AVA through API/Python SDK; notebook OS does not choose adapter |
| Databricks App | Linux adapter only if the app runtime supports required syscalls/filesystem | Capability probe; approved Workspace mapping; external durable persistence; no assumed unrestricted paths |

The notebook pattern is `Databricks notebook → AVA API/Python SDK → trusted AVA
backend composition → execution-service policy → backend-host adapter`. The
notebook does not embed or select AVA's execution system. Linux EC2/Azure VM
and eligible Linux Databricks App deployments use the Linux adapter based on
the server's actual host capabilities, not the cloud brand. Windows deployment
scenarios remain unavailable pending the native adapter.

Databricks Apps may have ephemeral local storage and restricted syscalls. The
Linux adapter probes `openat2`, filesystem type, and opened directory identity
on each access path and fails closed if the required local conditions do not
hold. Tool execution does not grant Databricks resource permissions. Production
Databricks hosting also requires external durable stores for Runs/conversations,
approval records, Workspace configuration, invocation reservations, and tool
history; none is implemented here. SQLite on ephemeral app storage is not
certified for production durability.

## Remote resource provider boundary

Databricks Unity Catalog Volumes, Databricks Workspace files, S3, Azure Blob,
and enterprise storage are deferred. Future providers should be AVA-owned
infrastructure adapters behind trusted Workspace resolution. They must use
provider-specific canonical resource identities, server-controlled
credentials, explicit resource and operation authorization, version/ETag or
equivalent consistency binding, and provider-native audit/error handling.
Credentials and provider selection must not be tool arguments. An agent cannot
switch provider or execution host to widen authority. Remote resources must not
inherit local filesystem permissions or be represented as arbitrary paths.
No broad storage framework or remote SDK was added in this phase.

## Execution modes and production availability

- **Chat:** denied by `ToolExecutionService`; the executor also denies Chat as
  defense in depth.
- **Plan:** the three definitions are read-only and eligible only under current
  Workspace authority, feature gates, policy, approval rules, and final
  execution checks. The isolated Linux test path succeeded.
- **Agent:** uses the same policy, authority, approval, feature, run, and
  reservation requirements. It does not bypass restrictions.

The production app registers metadata but composes `authority=None`,
`executors={}`, and `reservations=None`. There is no temporary privileged
provider or development bypass. Therefore **authorized production execution is
not available** in any mode. A model/runtime change cannot alter tool identity,
execution host, or Workspace permission.

## Validation evidence

The focused command covered Phase 6.11 filesystem behavior, registry and
feature gates, Phase 6.10 execution-service checks, Phase 6.6 policy, Phase 6.7
Workspace access, Phase 6.8 approvals, and architecture guards:

- **259 passed, 3 skipped** in the current focused backend aggregate on Linux.
- Native Linux adapter tests ran on Linux 6.8 and cover normal reads/listing,
  metadata, empty directories, pagination/order, truncation including UTF-8
  boundaries, invalid UTF-8, path traversal/absolute paths, symlinks and nested
  symlinks, hard links, FIFOs, Chat denial, Plan access, Workspace revision
  drift, cancellation at the adapter boundary, directory replacement and
  symlink-retargeting races, and unsupported adapter behavior.
- Production catalog tests confirm all three definitions are registered,
  feature gates default off, and production executor mappings remain empty.
- Full backend Ruff check: **passed**.
- Strict mypy: **passed** across all 286 `src/ava` files.
- Windows native security test module: **3 skipped** on Linux because native
  Windows APIs are unavailable. This is not Windows validation.
- Frontend validation was not run because this phase changed no frontend
  contracts or UI. Phase 6.9 frontend acceptance remains **PARTIAL — dependency
  installation blocked by missing pnpm cache entries and registry DNS
  failure**; this phase does not change that status.
- The Phase 6.10 handoff records two failures in the separate legacy
  `tests/test_run_service.py` suite because its stub `AgentPort.start_run`
  override omits the current `resolved_execution` parameter. That suite was not
  rerun in Phase 6.11 and the mismatch is outside this phase's changes.
- Cloud provider integrations, Databricks App deployment, and external durable
  persistence are deferred and untested.

No claim of exhaustive race proof follows from the bounded adversarial tests.

## Windows Implementation and GitHub Actions Validation

The Windows adapter implementation is in
`backend/src/ava/infrastructure/workspace_filesystem/windows.py`. It implements
the existing `WorkspaceFilesystemSecurityPort` and the same normalized
`workspace.list_files`, `workspace.read_file`, and `workspace.file_info`
contracts. Trusted backend composition selects it only on Windows. ToolRegistry,
ToolExecutionService, ToolPolicyService, approvals, Runs, tool definitions, and
Workspace authority remain platform-independent.

Windows containment uses component-by-component `NtCreateFile` calls rooted
at open directory handles. Components are opened without following reparse
points and checked with handle metadata. The root is restricted to a fixed
local NTFS drive, and its volume/file identity is compared across two
component walks. Handles omit delete sharing while in use to block rename and
replacement races. `NtQueryDirectoryFile` enumerates from directory handles;
`ReadFile` reads from the pinned regular-file handle. Junctions, symbolic
links, mount-point reparse paths, multi-link files, ADS syntax,
network/device/absolute/drive-relative paths, and unsupported volumes are
rejected. The code has not run on Windows; native API structure layout, NTFS
behavior, runner permissions, and race behavior remain unverified until the
native job passes.

The shared contract suite is
`backend/tests/test_workspace_filesystem_contract.py`; the native Windows
suite is `backend/tests/test_windows_workspace_filesystem.py`. The shared suite
selects the real Linux or Windows adapter based on the test host. Windows tests
require real NTFS junction and symbolic-link fixtures. The workflow has an
explicit capability preflight that fails if those fixtures cannot be created
or the runner volume is not NTFS; it does not silently treat skipped tests as
a pass.

The workflow is
`.github/workflows/ava-phase-6-11-filesystem-security.yml`. It defines
`ubuntu-22.04` and `windows-2025` jobs, uses the supported
`python -m pip install -e ".[dev]"` installation, and runs shared filesystem
and authorization tests, OS-specific security tests, Ruff, and strict mypy. It
is limited to relevant source/test changes plus manual dispatch, grants only
`contents: read`, and pins checkout and setup-python to verified full commit
SHAs. No workflow run link exists yet.

Linux validation on the current host: **259 passed, 3 Windows-only tests
skipped** across filesystem contracts, the Linux adversarial suite, registry,
execution service, policy, feature gates, Workspace access, approvals, and
architecture guards. Ruff passed across `backend/src` and `backend/tests`;
strict mypy passed across all 286 AVA source files. The Linux adapter continues
to use the original `openat2` implementation and passed its adversarial tests.

Windows validation: **not run**. The user-created target repository,
`cliski1978-hub/AVAPython`, was verified to be public and empty, and the user
explicitly authorized using it. The reviewed implementation snapshot was
committed locally as `3ecc2d9` (`Import AVA implementation and Phase 6.11
Windows validation`) on `phase-6.11-windows-validation`; local `master` history
was retained, and local `main` points to the same snapshot. The `origin` remote
is configured for the requested repository. The push was blocked because this
environment has no Git or SSH credential configured and Git could not prompt
for a GitHub username. No remote branch was created and no Actions run was
triggered. The authenticated GitHub connector can inspect the repository but
does not provide Git transport for uploading this local commit and its history.
After GitHub Git credentials are configured in this environment, push `master`,
`main`, and `phase-6.11-windows-validation` without force; the Phase 6.11
workflow will then run on the pushed validation branch.

Production dispatch remains unavailable: no trusted authority issuer,
production executor mapping, or durable invocation reservation adapter has
been added. **Final Phase 6.11 acceptance: PARTIAL** — the native Windows
implementation and validation workflow are present, but required Windows
security validation remains incomplete. No Phase 6.12 implementation was
started.

## Phase 6.12 readiness

The Linux tool catalog, normalized adapter seam, fail-closed production
boundary, and Windows adapter implementation are ready for review. Overall
cross-platform Phase 6.11 acceptance remains **PARTIAL pending native Windows
validation**. No Phase 6.12 implementation was started here.
