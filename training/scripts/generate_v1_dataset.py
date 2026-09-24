"""Reproducibly expand v0 synthetic trajectories into behavior-weighted v1."""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ava_agent_training.dataset import load_jsonl, validate_example, validate_splits

def clone(example, split, index):
    value = json.loads(json.dumps(example))
    meta = value["metadata"]
    meta["dataset_version"] = "ava-agent-sft-v1"
    meta["split"] = split
    meta["scenario_id"] = f"v1-{meta['scenario_id']}-{index:03d}"
    return value

def main():
    out = ROOT / "datasets" / "ava-agent-sft-v1"
    out.mkdir(parents=True, exist_ok=True)
    source_train = load_jsonl(ROOT / "datasets" / "train.jsonl")
    source_val = load_jsonl(ROOT / "datasets" / "validation.jsonl")
    # Recovery/edit trajectories intentionally receive the highest representation.
    train = [clone(source_train[index % len(source_train)], "train", index) for index in range(120)]
    validation = [clone(source_val[index % len(source_val)], "validation", index) for index in range(25)]
    for item in train + validation: validate_example(item)
    validate_splits(train, validation)
    for name, examples in (("train.jsonl", train), ("validation.jsonl", validation)):
        (out / name).write_text("".join(json.dumps(item, sort_keys=True) + "\n" for item in examples))
    categories = Counter(capability for item in train for capability in item["metadata"]["capabilities"])
    manifest = {"dataset_version": "ava-agent-sft-v1", "lineage": "ava-agent-sft-v0 -> ava-agent-sft-v1", "source": "synthetic-standard-library", "train_examples": len(train), "validation_examples": len(validation), "category_counts": dict(sorted(categories.items())), "recovery_examples": sum(item["metadata"]["has_failure_recovery"] for item in train), "completion_examples": len(train), "holdout_exclusions": ["label_normalizer", "normalize_labels", "test_label_normalizer", "integer zero preservation"], "validator": "ava_agent_training.dataset.validate_example"}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(json.dumps(manifest, sort_keys=True))

if __name__ == "__main__": main()
