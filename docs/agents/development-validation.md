# Development validation

Apply this owner-approved policy to AVA implementation phases. A phase may add
targeted acceptance checks, but Linux acceptance remains local and does not
require a GitHub Actions Linux job.

## Routine validation

- Run Linux validation locally on the Ubuntu development workstation. Do not
  require a Linux GitHub Actions job for phase acceptance.
- Run targeted tests for the changed behavior and applicable Ruff, mypy,
  TypeScript, frontend, and build checks.
- Reserve comprehensive regression suites for major integration milestones,
  significant shared-contract changes, and final acceptance.
- Report the checks that ran, the checks intentionally deferred, and any actual
  failures. A deferred Windows run is not a phase failure unless Windows
  compatibility is an explicit acceptance requirement.

## Windows and CI

- Use GitHub Actions with a native Windows runner when Windows-specific behavior
  or a major cross-platform integration requires verification.
- Schedule Windows CI at meaningful compatibility and integration checkpoints;
  do not trigger it after every phase.
- Do not push automatically or trigger CI unless the current assignment
  explicitly requires it.
- When the assignment requires Windows validation, use the existing native
  Windows Actions infrastructure and report its actual result.

This guidance governs validation only. It does not replace or amend the
architectural development plan.
