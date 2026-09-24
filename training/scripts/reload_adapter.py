"""Opt-in fresh-process base-plus-adapter inference validation."""
import gc, json, os, sys, time
from pathlib import Path
if os.getenv("AVA_RUN_LOCAL_MODEL_ADAPTER_RELOAD") != "1": raise SystemExit("set AVA_RUN_LOCAL_MODEL_ADAPTER_RELOAD=1")
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT))
import torch
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
adapter_path=ROOT/"outputs"/"granite-4.2-8b-ava-agent-sft-v1"
config=json.loads((adapter_path/"adapter_config.json").read_text())
base_id=config["base_model_name_or_path"]; revision="7fce579a7fbbad4b1e7703b6850cefd517a4002b"
started=time.monotonic(); torch.cuda.reset_peak_memory_stats()
quant=BitsAndBytesConfig(load_in_4bit=True,bnb_4bit_quant_type="nf4",bnb_4bit_use_double_quant=True,bnb_4bit_compute_dtype=torch.bfloat16)
tokenizer=AutoTokenizer.from_pretrained(adapter_path)
base=AutoModelForCausalLM.from_pretrained(base_id,revision=revision,quantization_config=quant,device_map={"":0},torch_dtype=torch.bfloat16)
model=PeftModel.from_pretrained(base,adapter_path); model.eval()
messages=[{"role":"user","content":"Reply exactly with: AVA ADAPTER RELOAD OK"}]
text=tokenizer.apply_chat_template(messages,tokenize=False,add_generation_prompt=True,enable_thinking=False)
inputs=tokenizer(text,return_tensors="pt").to("cuda")
with torch.no_grad(): output=model.generate(**inputs,max_new_tokens=12,do_sample=False)
generated=tokenizer.decode(output[0][inputs["input_ids"].shape[-1]:],skip_special_tokens=True).strip()
result={"base_model":base_id,"revision":revision,"adapter_path":str(adapter_path),"adapter_active":True,"generated":generated,"duration_seconds":round(time.monotonic()-started,2),"peak_allocated_bytes":torch.cuda.max_memory_allocated(),"peak_reserved_bytes":torch.cuda.max_memory_reserved()}
print(json.dumps(result,sort_keys=True)); del output,inputs,model,base; gc.collect(); torch.cuda.empty_cache()
