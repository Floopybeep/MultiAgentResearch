"""Validated, credential-free run settings."""

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator


class ModelConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model: str = "glm-5.3-flash"
    max_output_tokens: int = Field(default=4096, gt=0)
    options: dict[str, Any] = Field(default_factory=dict)
    input_cost_per_million: float | None = Field(default=None, ge=0)
    cached_input_cost_per_million: float | None = Field(default=None, ge=0)
    output_cost_per_million: float | None = Field(default=None, ge=0)

    @field_validator("options")
    @classmethod
    def no_credentials(cls, value):
        allowed = {
            "temperature", "top_p", "seed", "stop", "presence_penalty",
            "frequency_penalty", "reasoning_effort", "logprobs", "top_logprobs",
        }
        if set(value) - allowed:
            raise ValueError(
                "Only Chat Completions generation options are allowed: "
                + ", ".join(sorted(allowed))
            )
        return value


class PipelineFaultConfig(BaseModel):
    """Assignment IDs are stable batchN-workerM positions within each question."""

    model_config = ConfigDict(extra="forbid")
    enabled: bool = False
    fault_type: Literal["dropped_result", "dispatch_failure", "timeout"] = "dropped_result"
    assignment_ids: list[str] = Field(default_factory=list)
    probability: float = Field(default=1.0, ge=0, le=1)
    seed: int = 0


class RunConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    lead: ModelConfig = Field(
        default_factory=ModelConfig
    )
    worker: ModelConfig = Field(default_factory=ModelConfig)
    judge: ModelConfig = Field(default_factory=lambda: ModelConfig(max_output_tokens=1024))
    max_lead_turns: int = Field(default=20, gt=0)
    max_worker_turns: int = Field(default=12, gt=0)
    max_worker_tool_calls: int = Field(default=20, gt=0)
    max_batches: int = Field(default=6, gt=0)
    max_workers_per_batch: int = Field(default=4, gt=0)
    max_run_tokens: int = Field(default=200000, gt=0)
    run_timeout_seconds: float = Field(default=900, gt=0)
    worker_timeout_seconds: float = Field(default=180, gt=0)
    call_timeout_seconds: float = Field(default=60, gt=0)
    max_document_chars: int = Field(default=24000, gt=0)
    pipeline_fault: PipelineFaultConfig = Field(default_factory=PipelineFaultConfig)
    output_dir: Path = Path("runs")

    @classmethod
    def load(cls, path: str | Path):
        return cls.model_validate(yaml.safe_load(Path(path).read_text()) or {})
