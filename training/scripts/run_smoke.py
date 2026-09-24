"""Opt-in 4-bit Granite QLoRA forward/backward/update/save/reload smoke."""
import json
import os
import platform
import sys
import time
import gc
from pathlib import Path

if os.getenv("AVA_RUN_LOCAL_MODEL_TRAINING") != "1":
    raise SystemExit("set AVA_RUN_LOCAL_MODEL_TRAINING=1 to run the local QLoRA smoke")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ava_agent_training.config import SmokeConfig
from ava_agent_training.dataset import granite_messages, load_jsonl

import torch
from peft import LoraConfig, PeftModel, TaskType, get_peft_model
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

cfg = SmokeConfig()
out = ROOT / "outputs" / "granite-4.2-8b-ava-agent-smoke"
out.mkdir(parents=True, exist_ok=True)
started = time.monotonic()
quant = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_use_double_quant=True, bnb_4bit_compute_dtype=torch.bfloat16)
tokenizer = AutoTokenizer.from_pretrained(cfg.base_model, revision=cfg.revision)
sample = granite_messages(load_jsonl(ROOT / "datasets" / "train.jsonl")[0])
serialized = tokenizer.apply_chat_template(sample, tokenize=False, add_generation_prompt=False, enable_thinking=False)
inputs = tokenizer(serialized, return_tensors="pt", truncation=True, max_length=cfg.sequence_length).to("cuda")
inputs["labels"] = inputs["input_ids"].clone()
model = AutoModelForCausalLM.from_pretrained(cfg.base_model, revision=cfg.revision, quantization_config=quant, device_map={"": 0}, torch_dtype=torch.bfloat16)
model.config.use_cache = False
# PEFT's generic preparation upcasts all non-quantized parameters to FP32,
# which exceeded the available 8 GiB VRAM on this machine. Keep frozen 4-bit
# base weights resident and enable only the input gradient needed by LoRA.
model.enable_input_require_grads()
model.gradient_checkpointing_enable()
lora = LoraConfig(r=cfg.lora_rank, lora_alpha=cfg.lora_alpha, lora_dropout=cfg.lora_dropout, target_modules=cfg.target_modules, task_type=TaskType.CAUSAL_LM)
model = get_peft_model(model, lora)
optimizer = torch.optim.AdamW((p for p in model.parameters() if p.requires_grad), lr=cfg.learning_rate)
model.train(); optimizer.zero_grad(set_to_none=True)
loss = model(**inputs).loss
loss.backward(); optimizer.step(); optimizer.zero_grad(set_to_none=True)
loss_value = float(loss.detach().cpu())
model.save_pretrained(out); tokenizer.save_pretrained(out)
peak_allocated = torch.cuda.max_memory_allocated(); peak_reserved = torch.cuda.max_memory_reserved()
del optimizer, inputs, loss, model
gc.collect(); torch.cuda.empty_cache()
base = AutoModelForCausalLM.from_pretrained(cfg.base_model, revision=cfg.revision, quantization_config=quant, device_map={"": 0}, torch_dtype=torch.bfloat16)
reloaded = PeftModel.from_pretrained(base, out)
reload_inputs = tokenizer(serialized, return_tensors="pt", truncation=True, max_length=cfg.sequence_length).to("cuda")
with torch.no_grad(): reloaded(**reload_inputs)
metadata = {**cfg.metadata(), "loss": loss_value, "duration_seconds": round(time.monotonic()-started, 2), "peak_allocated_bytes": peak_allocated, "peak_reserved_bytes": peak_reserved, "python": platform.python_version(), "torch": torch.__version__, "cuda": torch.version.cuda, "adapter_reloaded": True}
(out / "metadata.json").write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n")
print(json.dumps(metadata, sort_keys=True))
