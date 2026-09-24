"""Read-only paired GGUF tensor forensics."""
import hashlib,json,sys
from collections import defaultdict
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT/'tools/llama.cpp/gguf-py'))
from gguf import GGUFReader
paths={"base_f16":ROOT/'deployment/granite-base-control-f16.gguf',"adapter_f16":ROOT/'deployment/granite-agent-f16.gguf',"base_q4":ROOT/'deployment/granite-base-control-q4_k_m.gguf',"adapter_q4":ROOT/'deployment/granite-agent-sft-v1-q4_k_m.gguf'}
def digest(path):
 h=hashlib.sha256()
 with path.open('rb') as f:
  for block in iter(lambda:f.read(1024*1024),b''): h.update(block)
 return h.hexdigest()
def read(path):
 r=GGUFReader(path); ts={t.name:{"shape":list(map(int,t.shape)),'type':str(t.tensor_type).split('.')[-1],"bytes":int(t.data.nbytes)} for t in r.tensors}; dist=defaultdict(lambda:[0,0])
 for t in ts.values():dist[t['type']][0]+=1;dist[t['type']][1]+=t['bytes']
 return {"bytes":path.stat().st_size,"sha256":digest(path),"tensors":ts,"distribution":dict(dist)}
values={k:read(v) for k,v in paths.items()}
def compare(a,b):
 x,y=values[a]['tensors'],values[b]['tensors']; common=set(x)&set(y)
 return {"counts":[len(x),len(y)],"only_first":sorted(set(x)-set(y)),"only_second":sorted(set(y)-set(x)),"shape_differences":sorted(n for n in common if x[n]['shape']!=y[n]['shape']),"type_differences":sorted(n for n in common if x[n]['type']!=y[n]['type']),"top_byte_differences":sorted(({"name":n,"first":x[n]['bytes'],"second":y[n]['bytes'],"difference":x[n]['bytes']-y[n]['bytes']} for n in common),key=lambda v:abs(v['difference']),reverse=True)[:15]}
result={"artifacts":values,"f16_comparison":compare('base_f16','adapter_f16'),"q4_comparison":compare('base_q4','adapter_q4')}
(ROOT/'deployment/reports').mkdir(parents=True,exist_ok=True);(ROOT/'deployment/reports/paired-gguf-forensics.json').write_text(json.dumps(result,indent=2,sort_keys=True));print(json.dumps(result,sort_keys=True))
