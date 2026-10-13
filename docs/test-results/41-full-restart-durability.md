# #41 Full Restart / Durability

**Result: PASS** — AVA's backend and web frontend were fully stopped, restarted, and the saved Phase 5 data remained available.

## Fixture identity

- Project: `R41 Project 20261012` (`cfb5a31e-0188-4680-bc34-079e1870e185`)
- Project conversation: `R41 durability run one. Read the attache…` (`ef3ad2c2-0064-478f-b971-209384a273fa`)
- Folder: `R41 Folder 20261012`
- Folder conversation: `R41 folder history message 1. Reply exac…` (`ef528568-d850-4faf-9743-4b856333132e`)
- Project file: `r41-project-file.txt`
- Conversation attachment: `r41-conversation-attachment.txt` (`ec46d7f5-0a7e-40cd-86f5-66be9ae61fd4`)
- Historical run: `7ac81437-4ae5-410f-8601-3f73e94f86b2`
- Post-restart run: `66dd318a-12bb-4ef2-9cd2-649d57d3ef69`
- CORE prompt: `AVA PRIME DIRECTIVES` (`6848a0a0-95d7-4e16-90b1-300c3b528231`)

## Restart verification

Stopped the AVA uvicorn backend process tree and Vite frontend process tree, confirmed those PIDs had exited, then restarted with `./scripts/dev_backend.sh` and `pnpm --filter @ava/web dev`. The frontend reloaded with AVA connected.

After restart, verified:

- Project, project membership, Folder membership, Project instructions, Project file, and conversation attachment were present.
- Folder conversation retained two user/assistant exchanges (`FOLDER-ONE`, `FOLDER-TWO`).
- Historical run remained selectable in Run Inspector and retained its CORE prompt, Project instructions, attachment extraction/inclusion record, and run context.
- CORE prompt definition and global prompt list remained present.
- Provider connection `Ollama Local` (`ollama-local`), model `Qwen 2.5 Coder 7B` (`qwen25-coder-7b`), and runtime `Native Runtime` (`native`) remained configured and enabled.
- Application defaults remained Ollama Local / Qwen 2.5 Coder 7B / Native Runtime. Project defaults remained Qwen 2.5 Coder 7B / Native Runtime.
- Project instructions remained “For restart verification, include the CORE prompt baseline and identify this Project as the instruction source.”

## Post-restart run

Sent a new prompt in the Project conversation asking AVA to read the attached marker and follow Project instructions. It completed with `R41-READY — Core Project Instructions`.

The new run Inspector recorded:

- CORE prompt `AVA PRIME DIRECTIVES` and the saved Project instructions.
- Attachment `r41-conversation-attachment.txt`: included, text extraction succeeded, 101 estimated tokens.
- Context window: 32,768 tokens; input budget: 31,744; attachment contribution: 101 tokens.
- Runtime `native`; model `qwen25-coder-7b`; provider connection `ollama-local`; execution sources `project`.
- Run status `completed`; Project ID and conversation ID matched the pre-restart fixtures.

The R41 fixture runs did not need compaction (Inspector reported “Not needed” and zero summary tokens). A separate existing conversation, `Controlled context-window compaction test` (`0f1da894-6dcd-40e8-87b4-3ad3ea661c25`), did have a saved summary after restart: summary `50e498c2-4f89-4fc2-9aff-661d2ff00635` v1, 456 tokens, used by historical run `5aed18ea-c3d9-4016-9f16-550a32e805a0`. That historical compaction state survived the restart.
