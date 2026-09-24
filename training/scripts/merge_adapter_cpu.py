"""Opt-in CPU merge of the exact Granite HF revision and saved PEFT adapter."""
import os, sys
from pathlib import Path
if os.getenv("AVA_RUN_LOCAL_MODEL_DEPLOYMENT") != "1": raise SystemExit("set AVA_RUN_LOCAL_MODEL_DEPLOYMENT=1")
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT))
import torch
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer
base_id="ibm-granite/granite-4.2-8b"; revision="7fce579a7fbbad4b1e7703b6850cefd517a4002b"
adapter=ROOT/"outputs"/"granite-4.2-8b-ava-agent-sft-v1"; out=ROOT/"deployment"/"granite-4.2-8b-ava-agent-sft-v1-merged"; out.mkdir(parents=True,exist_ok=True)
base=AutoModelForCausalLM.from_pretrained(base_id,revision=revision,torch_dtype=torch.bfloat16,device_map="cpu",low_cpu_mem_usage=True)
merged=PeftModel.from_pretrained(base,adapter).merge_and_unload(); merged.save_pretrained(out,safe_serialization=True,max_shard_size="5GB")
AutoTokenizer.from_pretrained(adapter).save_pretrained(out)
print(out)
