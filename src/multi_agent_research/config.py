"""Validated, credential-free run settings."""

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


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


class DocumentInjectionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = False
    num_docs: int = Field(default=1, ge=0)
    prompt: str = ""

    @model_validator(mode="after")
    def require_prompt_when_enabled(self):
        if self.enabled and not self.prompt.strip():
            raise ValueError("document_injection.prompt must be nonempty when enabled")
        return self


class WorkerFaultSelectionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = False
    probability: float = Field(default=1.0, ge=0, le=1)
    target_workers: list[str] = Field(default_factory=list)
    seed: int = 42

    @field_validator("target_workers")
    @classmethod
    def valid_assignments(cls, value):
        import re

        if any(not re.fullmatch(r"batch[1-9]\d*-worker[1-9]\d*", item) for item in value):
            raise ValueError("target_workers entries must be batchN-workerM assignment IDs")
        return value


class GenerationBudgetFaultConfig(WorkerFaultSelectionConfig):
    max_output_tokens: int = Field(default=128, gt=0, strict=True)
    budget_scope: Literal["per_call", "per_worker"] = "per_call"


class ToolCallBudgetFaultConfig(WorkerFaultSelectionConfig):
    max_tool_calls: int = Field(default=1, ge=0, strict=True)


class WorkerBudgetFaultConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    generation_budget: GenerationBudgetFaultConfig = Field(default_factory=GenerationBudgetFaultConfig)
    tool_call_budget: ToolCallBudgetFaultConfig = Field(default_factory=ToolCallBudgetFaultConfig)


class RunConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    lead: ModelConfig = Field(
        default_factory=ModelConfig
    )
    worker: ModelConfig = Field(default_factory=ModelConfig)
    judge: ModelConfig = Field(default_factory=lambda: ModelConfig(max_output_tokens=1024))
    lead_prompt: Path | None = None
    worker_prompt: Path | None = None
    max_lead_turns: int = Field(default=20, gt=0)
    max_worker_turns: int = Field(default=12, gt=0)
    max_worker_tool_calls: int = Field(default=20, gt=0)
    max_batches: int = Field(default=6, gt=0)
    max_workers_per_batch: int = Field(default=4, gt=0)
    minimum_worker: int = Field(default=1, gt=0)
    max_run_tokens: int = Field(default=200000, gt=0)
    run_timeout_seconds: float = Field(default=900, gt=0)
    worker_timeout_seconds: float = Field(default=180, gt=0)
    call_timeout_seconds: float = Field(default=60, gt=0)
    max_document_chars: int = Field(default=24000, gt=0)
    pipeline_fault: PipelineFaultConfig = Field(default_factory=PipelineFaultConfig)
    document_injection: DocumentInjectionConfig = Field(default_factory=DocumentInjectionConfig)
    worker_budget_faults: WorkerBudgetFaultConfig = Field(default_factory=WorkerBudgetFaultConfig)
    output_dir: Path = Path("runs")

    @model_validator(mode="after")
    def validate_worker_limits(self):
        if self.minimum_worker > self.max_workers_per_batch:
            raise ValueError("minimum_worker must not exceed max_workers_per_batch")
        return self

    @classmethod
    def load(cls, path: str | Path):
        return cls.model_validate(yaml.safe_load(Path(path).read_text()) or {})
