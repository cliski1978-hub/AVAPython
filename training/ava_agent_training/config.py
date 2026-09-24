"""Conservative, explicit configuration for the opt-in QLoRA smoke."""

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class SmokeConfig:
    base_model: str = "ibm-granite/granite-4.2-8b"
    revision: str = "7fce579a7fbbad4b1e7703b6850cefd517a4002b"
    dataset_version: str = "ava-agent-sft-v0"
    sequence_length: int = 1024
    batch_size: int = 1
    gradient_accumulation: int = 4
    learning_rate: float = 2e-4
    max_steps: int = 1
    lora_rank: int = 16
    lora_alpha: int = 32
    lora_dropout: float = 0.0
    target_modules: str = "all-linear"

    def metadata(self) -> dict[str, object]:
        return asdict(self)
