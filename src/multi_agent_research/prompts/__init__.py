"""Pinned prompt loading and strict, non-recursive context substitution."""
import hashlib
import re
from importlib.resources import files
from pathlib import Path

VARIABLE = re.compile(r"{{\s*\.([A-Za-z][A-Za-z0-9_]*)\s*}}")
ROLES = ("lead", "worker", "judge", "verifier")


def load(role, path=None):
    if role not in ROLES:
        raise ValueError(f"Unknown prompt role: {role}")
    if path is not None:
        return Path(path).read_text(encoding="utf-8")
    return files(__package__).joinpath(f"{role}.md").read_text()


def render(template, context):
    # Validate the template, not substituted values: user data is never re-rendered.
    residue = VARIABLE.sub("", template)
    if "{{" in residue or "}}" in residue:
        raise ValueError("Unsupported prompt template expression")

    def replace(match):
        name = match.group(1)
        if name not in context:
            raise ValueError(f"Missing prompt context: {name}")
        return str(context[name])

    return VARIABLE.sub(replace, template)


def context(config, date):
    return {
        "CurrentDate": date,
        "MaxLeadTurns": config.max_lead_turns,
        "MaxBatches": config.max_batches,
        "MaxWorkersPerBatch": config.max_workers_per_batch,
        "MinimumWorker": config.minimum_worker,
        "MaxWorkerTurns": config.max_worker_turns,
        "MaxWorkerToolCalls": config.max_worker_tool_calls,
    }


def hashes(config=None, *, include_verifier: bool = False):
    return {
        role: hashlib.sha256(load(
            role, getattr(config, f"{role}_prompt", None)
        ).encode()).hexdigest()
        for role in ROLES if include_verifier or role != "verifier"
    }
