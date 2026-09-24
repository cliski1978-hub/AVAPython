"""Validate synthetic datasets without downloading a model."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ava_agent_training.dataset import load_jsonl, validate_splits

train = load_jsonl(ROOT / "datasets" / "train.jsonl")
validation = load_jsonl(ROOT / "datasets" / "validation.jsonl")
validate_splits(train, validation)
print(f"validated dataset: train={len(train)} validation={len(validation)}")
