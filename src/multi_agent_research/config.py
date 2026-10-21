"""Validated, credential-free run settings."""

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator


class ModelConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model: str = "gpt-6-luna"
    max_output_tokens: int = Field(default=4096, gt=0)
    options: dict[str, Any] = Field(default_factory=dict)
    input_cost_per_million: float | None = Field(default=None, ge=0)
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


class RunConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    lead: ModelConfig = Field(
        default_factory=lambda: ModelConfig(model="gpt-6-luna")
    )
    worker: ModelConfig = Field(default_factory=ModelConfig)
    citation: ModelConfig = Field(default_factory=lambda: ModelConfig(max_output_tokens=8192))
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
    max_citation_chars: int = Field(default=160000, gt=0)
    max_download_bytes: int = Field(default=2000000, gt=0)
    search_results: int = Field(default=5, ge=1, le=20)
    output_dir: Path = Path("runs")

    @classmethod
    def load(cls, path: str | Path):
        return cls.model_validate(yaml.safe_load(Path(path).read_text()) or {})
