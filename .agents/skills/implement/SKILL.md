---
name: implement
description: "Implement a piece of work based on a spec or set of tickets."
disable-model-invocation: true
---

Implement the work described by the user in the spec or tickets.

Use /tdd where possible, at pre-agreed seams.

Run typechecking regularly, single test files regularly, and the full test suite once at the end.

## Long-running validation

When the full suite exceeds the foreground execution window, run the same command in a named tmux session with stdout and stderr redirected to a temporary log and its exit code written to a separate temporary file. Wait for that session to finish, then read the captured exit code and final pytest summary before reporting validation. The suite is complete only when its actual process exit and summary have been observed.

Once done, use /code-review to review the work.

Commit your work to the current branch.
