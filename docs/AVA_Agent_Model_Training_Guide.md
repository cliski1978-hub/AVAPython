# AVA agent-model training guide

AVA runtime, standalone `training/`, independent qualification, and a future
deployment pipeline are separate systems. Training starts from the official HF
Safetensors checkpoint, produces a LoRA adapter, then later may be independently
evaluated and exported. Ollama GGUF artifacts are deployment-only.

Examples use role-preserving messages and native `file_editor` or `ava_terminal`
calls. `ava_terminal` always supplies a bare `executable` and a string-list
`arguments`; JSON-looking assistant prose is rejected. Generate and validate
the synthetic JSONL before training. Keep train and validation scenario IDs
separate and never place the Step 35 qualification fixture in either split.

Create the isolated environment from `training/requirements.txt`. The smoke is
explicitly gated by `AVA_RUN_LOCAL_MODEL_TRAINING=1`; it uses 4-bit NF4,
double-quantization, BF16 compute, batch size one, checkpointing, rank-16 LoRA,
and a 1024-token maximum. It saves an experimental adapter and metadata only.
Larger SFT, base-versus-adapter qualification, merging/quantizing, and registry
identity remain future work.

After GPU-heavy SFT, exit the training process before validating an adapter:
loading a second 8B base in the same process can OOM despite a valid adapter.
The Granite v1 adapter reloads successfully in a fresh NF4 inference process.
The original Granite PEFT adapter cannot be imported directly by the installed
Ollama version, so deployment merges the adapter on CPU, converts both the
control and merged checkpoints to F16 GGUF, quantizes both to Q4_K_M with the
same llama.cpp commit, and imports a matched Ollama pair. Both deployments use
the official Granite `{{ .Prompt }}` template, `num_ctx=8192`, temperature 1,
and top-p 0.95. Native tool support is then qualified through the unchanged
OpenHands → native ActionEvent → `ava_terminal` → Bubblewrap path, never by
parsing assistant text.

For paired quantized comparisons, inspect exact GGUF tensor inventories and
byte sizes after both quantizations finish. Human-readable GiB rounding can
make an in-progress output appear different; compare output head, embedding,
GGML type distribution, and exact `stat` size before treating artifacts as
asymmetric.

Never compare base and trained Q4 artifacts until quantization has fully
completed and paired tensor inventories have been verified. The complete
deployment lineage and the recorded Q4 checksums are in
`training/deployment/manifest.json`; the detailed tensor evidence is in
`training/deployment/reports/paired-gguf-forensics.json`.

The frozen Step 35D.3 comparison did not show a long-loop completion gain from
the bounded 12-step, 512-token SFT-v1 run: neither candidate completed the
holdout autonomous repair under five iterations and 60 seconds. A future
controlled v2 experiment should first target longer edit→test→result-consumption
trajectories and stop-after-success behavior; this is a direction for
evaluation, not evidence that retraining alone will solve the failure.
