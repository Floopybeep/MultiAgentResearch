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


class ToolFailureConfig(BaseModel):
    """Accidental `read_document` failures: evidence denial at the worker boundary."""

    model_config = ConfigDict(extra="forbid")
    enabled: bool = False
    mode: Literal["immediate", "timeout"] = "immediate"
    document_ids: list[str] = Field(default_factory=list)
    offsets: list[int] = Field(default_factory=list)
    max_failures: int | None = Field(default=1, ge=0)
    failure_probability: float = Field(default=1.0, ge=0, le=1)
    persistent: bool = True
    timeout_margin: float = Field(default=1.5, gt=1.0)
    seed: int = 0
    allow_total_denial: bool = False

    @field_validator("offsets")
    @classmethod
    def nonnegative_offsets(cls, value):
        if any(offset < 0 for offset in value):
            raise ValueError("tool_failure.offsets must be nonnegative character positions")
        return value

    @model_validator(mode="after")
    def require_total_denial_optin(self):
        if (
            self.enabled
            and self.max_failures is None
            and not self.document_ids
            and not self.allow_total_denial
        ):
            raise ValueError(
                "Uncapped failures over every document deny all evidence, so no worker "
                "completes and the Lead raises 'At least one successful worker result is "
                "required'. Set tool_failure.allow_total_denial to opt in, or restrict "
                "max_failures or document_ids"
            )
        return self


class ConnectionDropConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = False
    batch: int = Field(default=1, gt=0)
    num_delivered: int = Field(default=1, ge=0)
    select: Literal["last", "random"] = "last"
    seed: int = 0
    persistent: bool = False


class ResultTimeoutConfig(ConnectionDropConfig):
    # Deadline counted from dispatch; defaults to the standard worker_timeout_seconds.
    timeout_seconds: float = Field(default=180, gt=0)


class RunConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    lead: ModelConfig = Field(
        default_factory=ModelConfig
    )
    worker: ModelConfig = Field(default_factory=ModelConfig)
    judge: ModelConfig = Field(default_factory=lambda: ModelConfig(max_output_tokens=1024))
    verifier: ModelConfig = Field(default_factory=lambda: ModelConfig(max_output_tokens=1024))
    lead_prompt: Path | None = None
    worker_prompt: Path | None = None
    full_restart: bool = False
    always_verify: bool = False
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
    tool_failure: ToolFailureConfig = Field(default_factory=ToolFailureConfig)
    connection_drop: ConnectionDropConfig = Field(default_factory=ConnectionDropConfig)
    result_timeout: ResultTimeoutConfig = Field(default_factory=ResultTimeoutConfig)
    output_dir: Path = Path("runs")

    @model_validator(mode="after")
    def validate_worker_limits(self):
        if self.minimum_worker > self.max_workers_per_batch:
            raise ValueError("minimum_worker must not exceed max_workers_per_batch")
        return self

    @model_validator(mode="after")
    def validate_delivery_faults(self):
        if self.connection_drop.enabled and self.result_timeout.enabled:
            raise ValueError("connection_drop and result_timeout are mutually exclusive")
        if (self.result_timeout.enabled
                and self.result_timeout.timeout_seconds > self.worker_timeout_seconds):
            raise ValueError(
                "result_timeout.timeout_seconds must not exceed worker_timeout_seconds"
            )
        return self

    @model_validator(mode="after")
    def separate_strategies(self):
        if self.full_restart and self.always_verify:
            raise ValueError("full_restart and always_verify are mutually exclusive")
        return self

    @property
    def strategy(self) -> str:
        if self.full_restart:
            return "full-restart"
        return "always-verify" if self.always_verify else "baseline"

    @classmethod
    def load(cls, path: str | Path):
        return cls.model_validate(yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {})
