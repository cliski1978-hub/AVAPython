# AVA agent-model training

This directory is isolated from `backend/src/ava`: AVA runtime imports no
training dependency. It contains synthetic SFT trajectories, deterministic
validation, and an opt-in 4-bit QLoRA smoke for the official Transformers/
Safetensors checkpoint `ibm-granite/granite-4.2-8b`.

Run `python scripts/generate_dataset.py`, then `python scripts/validate_dataset.py`.
The dataset preserves system/user/assistant-native-tool/tool-result/final roles.
Only the contained `file_editor` and `ava_terminal` schemas are permitted. The
Step 35 `label_normalizer` holdout is forbidden. `AVA_RUN_LOCAL_MODEL_TRAINING=1
.venv/bin/python scripts/run_smoke.py` downloads/loads the HF checkpoint,
performs one QLoRA optimizer step, saves an experimental adapter, and reloads it.

This is feasibility work only: never train an Ollama GGUF, merge an adapter,
deploy to Ollama, or interpret smoke loss as quality. Future evaluation compares
base and adapter on the unchanged Step 35 holdout.
