"""Opt-in bounded manual SFT retaining the known 8GB QLoRA memory envelope."""
from __future__ import annotations
import gc, json, os, random, statistics, sys, time
from pathlib import Path
if os.getenv("AVA_RUN_LOCAL_MODEL_TRAINING") != "1": raise SystemExit("set AVA_RUN_LOCAL_MODEL_TRAINING=1")
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT))
from ava_agent_training.config import SmokeConfig
from ava_agent_training.dataset import granite_messages, load_jsonl
import torch
from peft import LoraConfig, PeftModel, TaskType, get_peft_model
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
cfg=SmokeConfig(dataset_version="ava-agent-sft-v1", sequence_length=512, max_steps=12)
seed=17; random.seed(seed); torch.manual_seed(seed); torch.cuda.manual_seed_all(seed)
data=ROOT/"datasets"/"ava-agent-sft-v1"; train=load_jsonl(data/"train.jsonl"); val=load_jsonl(data/"validation.jsonl")
tokenizer=AutoTokenizer.from_pretrained(cfg.base_model,revision=cfg.revision)
def encode(item):
    text=tokenizer.apply_chat_template(granite_messages(item),tokenize=False,add_generation_prompt=False,enable_thinking=False)
    result=tokenizer(text,return_tensors="pt",truncation=True,max_length=cfg.sequence_length); result["labels"]=result["input_ids"].clone(); return result
lengths=[len(encode(item)["input_ids"][0]) for item in train+val]
stats={"min":min(lengths),"median":statistics.median(lengths),"p90":sorted(lengths)[int(.9*(len(lengths)-1))],"max":max(lengths),"truncation_count":sum(x>=cfg.sequence_length for x in lengths)}
quant=BitsAndBytesConfig(load_in_4bit=True,bnb_4bit_quant_type="nf4",bnb_4bit_use_double_quant=True,bnb_4bit_compute_dtype=torch.bfloat16)
started=time.monotonic(); torch.cuda.reset_peak_memory_stats()
model=AutoModelForCausalLM.from_pretrained(cfg.base_model,revision=cfg.revision,quantization_config=quant,device_map={"":0},torch_dtype=torch.bfloat16)
model.config.use_cache=False; model.enable_input_require_grads(); model.gradient_checkpointing_enable()
model=get_peft_model(model,LoraConfig(r=16,lora_alpha=32,lora_dropout=0.0,target_modules="all-linear",task_type=TaskType.CAUSAL_LM))
opt=torch.optim.AdamW((p for p in model.parameters() if p.requires_grad),lr=cfg.learning_rate); model.train(); losses=[]
for step in range(cfg.max_steps):
    batch=encode(train[step%len(train)]).to("cuda"); loss=model(**batch).loss/cfg.gradient_accumulation; loss.backward(); losses.append(float(loss.detach().cpu()))
    if (step+1)%cfg.gradient_accumulation==0 or step+1==cfg.max_steps: opt.step(); opt.zero_grad(set_to_none=True)
model.eval(); val_losses=[]
with torch.no_grad():
    for item in val[:5]: val_losses.append(float(model(**encode(item).to("cuda")).loss.detach().cpu()))
out=ROOT/"outputs"/"granite-4.2-8b-ava-agent-sft-v1"; out.mkdir(parents=True,exist_ok=True); model.save_pretrained(out); tokenizer.save_pretrained(out)
peak_a=torch.cuda.max_memory_allocated(); peak_r=torch.cuda.max_memory_reserved(); del opt,model; gc.collect(); torch.cuda.empty_cache()
base=AutoModelForCausalLM.from_pretrained(cfg.base_model,revision=cfg.revision,quantization_config=quant,device_map={"":0},torch_dtype=torch.bfloat16); adapter=PeftModel.from_pretrained(base,out)
with torch.no_grad(): adapter(**encode(val[0]).to("cuda"))
meta={**cfg.metadata(),"dataset_counts":{"train":len(train),"validation":len(val)},"seed":seed,"optimizer":"AdamW","training_steps":cfg.max_steps,"optimizer_steps":3,"training_losses":losses,"final_training_loss":losses[-1],"validation_loss":statistics.mean(val_losses),"token_statistics":stats,"duration_seconds":round(time.monotonic()-started,2),"peak_allocated_bytes":peak_a,"peak_reserved_bytes":peak_r,"adapter_reloaded":True,"torch":torch.__version__}
(out/"metadata.json").write_text(json.dumps(meta,indent=2,sort_keys=True)+"\n"); print(json.dumps(meta,sort_keys=True))
