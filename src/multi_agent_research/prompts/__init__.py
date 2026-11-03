"""Pinned prompt loading and strict, non-recursive context substitution."""
import hashlib
import re
from importlib.resources import files

VARIABLE = re.compile(r"{{\s*\.([A-Za-z][A-Za-z0-9_]*)\s*}}")
ROLES = ("lead", "worker", "citation")


def load(role):
    if role not in ROLES:
        raise ValueError(f"Unknown prompt role: {role}")
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
        "MaxWorkerTurns": config.max_worker_turns,
        "MaxWorkerToolCalls": config.max_worker_tool_calls,
    }


def hashes():
    return {r: hashlib.sha256(load(r).encode()).hexdigest() for r in ("lead", "worker", "judge")}
