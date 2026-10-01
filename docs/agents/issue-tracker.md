# Issue tracker: Local Markdown

Issues and specs live under `.scratch/<feature-slug>/`.

## Conventions

- Specs: `spec.md` within the feature directory.
- Tickets: `issues/<NN>-<slug>.md`, numbered from `01`,
  with one file per ticket.
- Triage state: a `Status:` line near the top of each ticket,
  using the roles in `triage-labels.md`.
- Comments: append under `## Comments`.

When publishing, create the appropriate spec or ticket file,
including its parent directories as needed.

When fetching a ticket, read its referenced path. If only a
number is provided, resolve it within the relevant feature.
Ask which feature if the number is ambiguous.

## Wayfinding operations

- Map: `.scratch/<effort>/map.md`, containing Notes,
  Decisions-so-far, and Fog.
- Child ticket: `.scratch/<effort>/issues/<NN>-<slug>.md`.
- Record the question in the body and the ticket type in
  `Type:`: research, prototype, grilling, or task.
- Track execution using `Status: open`, `Status: claimed`,
  or `Status: resolved`.
- Record dependencies as `Blocked by: NN, NN`.
  A ticket is unblocked when all dependencies are resolved.
- Frontier: select the lowest-numbered open, unblocked ticket.
- Claim: save `Status: claimed` before starting work.
- Resolve: append an `## Answer`, set `Status: resolved`,
  and add a summary and link to the map's Decisions-so-far.
