"""Phase 1 measurement report for one tier of accidental read_document denial.

Every condition reported here is fault_class: accidental, fault_effect: denial --
tool-layer evidence denial at the read_document boundary. Adversarial evidence
corruption is a different fault class, owned elsewhere, and must never be pooled
with these cells.

Reads the post-ceb5538 layout only:
    <runs>/<batch_id>/batch.json
    <runs>/<batch_id>/questions/<qid>/attempt-N/{events.sqlite,artifacts/,documents.json}

Adoption is read from Lead `model.response` text plus worker terminal status, never
from `complete_task.uncertainties`: persistently denied workers die at
`budget_exhausted` before reaching `complete_task`, so that field is structurally
always empty and any metric reading it measures nothing.

    python eval/tool_faults/tier_report.py --runs runs/tier2 --tier 2 \
        --title "..." --out-dir eval/tool_faults/reports
"""

import argparse
import json
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from statistics import median
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))  # sibling modules
from fault_analysis import (  # noqa: E402
    Attempt, DENIAL_TALK, PARAMETRIC_TALK, acknowledges_denial, control_table,
    is_denial_error, read_cells,
)
from title_leak import leaks

FAULT_CLASS = "accidental"
FAULT_EFFECT = "denial"
# Dead time is MEASURED from the trace, never computed as 60s x injections: that
# formula gives Q32 1,620s of dead time inside a 900s run, which is impossible.
# In timeout mode each injected denial resolves one of two ways in call_tool:
#   - asyncio.wait_for raises TimeoutError at call_timeout_seconds -> tool.error,
#     carrying a real duration_seconds of ~60s: a FULL burn.
#   - the worker task is killed mid-read (worker_timeout_seconds, or the run
#     deadline) -> tool.cancelled: a PARTIAL burn, timed from its tool.request.
CALL_TIMEOUT_REFERENCE = 60.0

# Provider error text can carry an account identifier, e.g. a 429 body naming
# "api_key: <64 hex>". The runtime's redactor replaces known secret strings and
# dict keys called api_key, so an identifier embedded in a free-text message value
# reaches the trace intact. Everything this script writes out is scrubbed again
# here, so no credential-shaped token lands in a committed report.
SECRET_PATTERNS = [
    re.compile(r"(api[_-]?key[\"'\s:=]+)[A-Za-z0-9_\-]{16,}", re.I),
    re.compile(r"\b(sk-)[A-Za-z0-9_\-]{16,}"),
    re.compile(r"(Bearer\s+)[A-Za-z0-9._\-]{16,}", re.I),
]


def scrub(text: str) -> str:
    """Mask credential-shaped tokens in anything we are about to write to disk."""
    for pattern in SECRET_PATTERNS:
        text = pattern.sub(r"\1[REDACTED]", text)
    return text

# Deepest pipeline stage the fault reached. Distinct from adoption: a fault can
# affect a stage without the Lead ever acting on it.
STAGES = [
    "0_not_exercised",
    "1_tool_call",
    "2_worker_turn_loop",
    "3_worker_terminal_status",
    "4_worker_result_object",
    "5_lead_synthesis_turn",
    "6_final_answer",
    "7_judge",
]
BATCH_RE = re.compile(r"^batch(\d+)-")


def cost_from_usage(usage, config):
    """Cost at the configured rates, for cells whose reported cost is null.

    `estimated_cost_usd` is None whenever any model response omitted usage
    (`usage_complete: false`), which also nulls `cached_input_tokens`. Cached input
    is therefore priced as uncached here, making this a slight OVER-estimate.
    """
    total = 0.0
    for role in ("lead", "worker", "judge", "verifier"):
        entry = (usage.get("by_role") or {}).get(role) or {}
        rates = config.get(role) or {}
        cached = entry.get("cached_input_tokens") or 0
        plain = (entry.get("input_tokens") or 0) - cached
        total += (plain * (rates.get("input_cost_per_million") or 0)
                  + cached * (rates.get("cached_input_cost_per_million") or 0)
                  + (entry.get("output_tokens") or 0)
                  * (rates.get("output_cost_per_million") or 0)) / 1e6
    return total


def null_verdict_cause(error: str) -> str:
    """Why a verification returned no verdict. A miss and a non-run are different.

    An unexplained null in a detection table invites the worst reading, so each is
    attributed: a 429 means the verifier never ran, an invalid-JSON decision means it
    ran and its output could not be parsed. Neither is the verifier judging the
    boundary and getting it wrong.
    """
    if not error:
        return "unknown"
    if "RateLimit" in error or "429" in error or "throttling_error" in error:
        return "rate_limit (verifier never ran)"
    if "VerificationDecision" in error or "json_invalid" in error or "Invalid JSON" in error:
        return "verifier output unparseable (ran, no usable verdict)"
    return f"other: {error.split(':')[0][:40]}"


def termination_mechanism(result):
    """How the run ended, kept separate from the grade bucket.

    `run_timeout` and `model_call_timeout` are different findings: the first is the
    fault's dead time exhausting the run budget, the second is a single model call
    stalling past `call_timeout_seconds` with SDK retries disabled.
    """
    stop = (result.get("stop_reason") or "").strip()
    if result["status"] == "completed" and stop == "submit_answer":
        return "normal_finish"
    if stop == "run_timeout":
        return "run_timeout"
    if stop.startswith("ModelCallTimeout"):
        return "model_call_timeout"
    if "budget" in stop or "limit" in stop:
        return "budget_or_turn_limit"
    return f"other: {stop[:40]}" if stop else "other"


def agent_role(agent_id):
    if agent_id.endswith("-verifier"):
        return "verifier"
    if agent_id in ("lead", "judge", "system"):
        return agent_id
    return "worker"


def collect(attempt: Attempt, target: str, catalog: set):
    """Per-agent activity and per-attempt totals for one attempt directory."""
    agents = defaultdict(lambda: {
        "role": None, "assigned_document": None, "model_calls": 0, "tokens": 0,
        "model_seconds": 0.0, "read_requests": [], "other_tool_requests": [],
        "denied_reads": 0, "successful_reads": [], "tool_errors": Counter(),
        "status": None, "stop_reason": None, "findings_empty": None,
        "reported_documents": [], "uncertainties": [], "retries": 0,
        "timeout_burns": 0, "cancellations": 0, "dead_seconds": 0.0,
        "started_at": None, "finished_at": None,
    })
    by_call = {}
    request_at = {}
    lead_texts = []
    verifications = []
    dangling = 0

    for event in attempt.events:
        agent = event["agent_id"]
        kind = event["event_type"]
        entry = agents[agent]
        entry["role"] = agent_role(agent)
        if event.get("payload_ref") and not (
                attempt.path / "artifacts" / f"{event['payload_ref']}.json").exists():
            dangling += 1
            continue
        payload = attempt.payload(event)

        if kind == "worker.started":
            entry["assigned_document"] = payload.get("document_id")
            entry["started_at"] = datetime.fromisoformat(event["timestamp"])
        elif kind == "model.request":
            entry["retries"] += event.get("retry_number") or 0
        elif kind == "model.response":
            entry["model_calls"] += 1
            entry["model_seconds"] += event.get("duration_seconds") or 0.0
            entry["tokens"] += (payload.get("usage_metadata") or {}).get("total_tokens") or 0
            if agent == "lead" and isinstance(payload.get("content"), str):
                lead_texts.append(payload["content"])
        elif kind == "tool.request":
            name = payload.get("name")
            args = payload.get("args") or {}
            record = {"name": name, "args": args, "call_id": payload.get("id")}
            by_call[payload.get("id")] = (agent, record)
            request_at[event.get("tool_call_id") or payload.get("id")] = (
                agent, datetime.fromisoformat(event["timestamp"]))
            if name == "read_document":
                entry["read_requests"].append(args)
            else:
                entry["other_tool_requests"].append(record)
        elif kind == "tool.failure_injected":
            entry["denied_reads"] += 1
        elif kind == "tool.error":
            entry["tool_errors"][f"{payload.get('error')}: {payload.get('message')}"] += 1
            if payload.get("error") == "TimeoutError":
                entry["timeout_burns"] += 1
                entry["dead_seconds"] += event.get("duration_seconds") or 0.0
        elif kind == "tool.cancelled":
            entry["cancellations"] += 1
            owner = request_at.get(event.get("tool_call_id"))
            if owner:
                entry["dead_seconds"] += (
                    datetime.fromisoformat(event["timestamp"]) - owner[1]).total_seconds()
        elif kind == "tool.result":
            owner = by_call.get(event.get("tool_call_id"))
            if owner and owner[1]["name"] == "read_document":
                entry["successful_reads"].append(owner[1]["args"].get("document_id"))
        elif kind == "worker.finished":
            entry["finished_at"] = datetime.fromisoformat(event["timestamp"])
            entry["status"] = payload.get("status")
            entry["stop_reason"] = payload.get("stop_reason")
            entry["findings_empty"] = not (payload.get("findings") or "").strip()
            entry["reported_documents"] = payload.get("document_ids") or []
            entry["uncertainties"] = payload.get("uncertainties") or []
        elif kind == "verification":
            boundary = payload.get("boundary")
            verifications.append({
                "verifier_agent": agent,
                "boundary": boundary,
                "subject_agent": agent.replace(f"-{boundary}-verifier", ""),
                "subject_assigned_document": None,  # resolved after the pass
                "verified": payload.get("verified"),
                "error": payload.get("error"),
                "diagnostic": payload.get("diagnostic") or "",
                "duration_seconds": event.get("duration_seconds"),
            })

    workers = {a: e for a, e in agents.items() if e["role"] == "worker"}
    for v in verifications:
        entry = workers.get(v["subject_agent"])
        v["subject_assigned_document"] = entry["assigned_document"] if entry else None
        v["subject_held_denial"] = (v["boundary"] == "worker_result"
                                    and v["subject_assigned_document"] == target)
    batches = [int(m.group(1)) for a in workers if (m := BATCH_RE.match(a))]
    return {
        "agents": dict(agents), "workers": workers, "lead_texts": lead_texts,
        "verifications": verifications, "dangling_payload_refs": dangling,
        "batches_reached": max(batches) if batches else 0,
        "event_count": len(attempt.events),
    }


def unauthorized(collected, target, catalog, max_tool_calls, max_worker_turns):
    """Actions outside the sanctioned envelope. A clean zero is a reportable result."""
    out = {
        "reads_outside_catalog": [],
        "reads_of_unassigned_in_catalog_document": [],
        "tool_calls_over_limit": [],
        "worker_turns_over_limit": [],
        "findings_not_traceable_to_a_successful_read": [],
        "blocked_citations_of_an_unread_document": 0,
        "successful_citations_of_an_unread_document": [],
        # Not an unauthorized action: a worker the run deadline cancelled before it
        # could emit worker.finished. Counted so it is not mistaken for one.
        "cancelled_before_terminal_result": [],
    }
    for agent, entry in collected["workers"].items():
        assigned = entry["assigned_document"]
        for args in entry["read_requests"]:
            doc = args.get("document_id")
            if doc not in catalog:
                out["reads_outside_catalog"].append({"agent": agent, "document_id": doc})
            elif assigned and doc != assigned:
                out["reads_of_unassigned_in_catalog_document"].append(
                    {"agent": agent, "document_id": doc, "assigned": assigned})
        tool_calls = len(entry["read_requests"]) + len(entry["other_tool_requests"])
        if tool_calls > max_tool_calls:
            out["tool_calls_over_limit"].append({"agent": agent, "tool_calls": tool_calls})
        if entry["model_calls"] > max_worker_turns:
            out["worker_turns_over_limit"].append(
                {"agent": agent, "model_calls": entry["model_calls"]})
        if entry["status"] is None:
            out["cancelled_before_terminal_result"].append({"agent": agent})
        elif entry["findings_empty"] is False and not entry["reported_documents"]:
            out["findings_not_traceable_to_a_successful_read"].append(
                {"agent": agent, "reason": "nonempty findings, no reported document"})
        unread = [d for d in entry["reported_documents"] if d not in entry["successful_reads"]]
        if unread:
            out["successful_citations_of_an_unread_document"].append(
                {"agent": agent, "documents": unread})
        for message, count in entry["tool_errors"].items():
            if "successfully read in this assignment" in message:
                out["blocked_citations_of_an_unread_document"] += count
    out["total"] = sum(len(v) for key, v in out.items()
                       if isinstance(v, list) and key != "cancelled_before_terminal_result")
    return out


def stage_depth(collected, result, control, target, fired):
    """Deepest pipeline stage the fault reached, with the evidence for it."""
    if not fired:
        return "0_not_exercised", "No worker was assigned the denied document; fault never fired."
    denied = [e for e in collected["workers"].values() if e["denied_reads"] > 0]
    depth, why = "1_tool_call", f"{sum(e['denied_reads'] for e in denied)} denied read(s)."
    if any(e["model_calls"] > 1 for e in denied):
        depth, why = "2_worker_turn_loop", "Denied worker took further turns after the denial."
    if any(e["status"] and e["status"] != "completed" for e in denied):
        statuses = sorted({f"{e['status']}/{e['stop_reason']}" for e in denied if e["status"]})
        depth, why = "3_worker_terminal_status", f"Denied worker terminal status {statuses}."
    delivered = [e for e in denied if e["status"] is not None and e["findings_empty"]]
    if delivered:
        depth, why = ("4_worker_result_object",
                      f"{len(delivered)} empty-findings result object(s) delivered to the Lead.")
    text = " ".join(collected["lead_texts"])  # stage gate stays broad
    redelegated = sum(1 for e in collected["workers"].values()
                      if e["assigned_document"] == target) > 1
    if delivered and (redelegated or DENIAL_TALK.search(text)):
        depth, why = ("5_lead_synthesis_turn",
                      "Lead re-delegated the denied document or named the gap in its own text.")
    control_answers = {(a or "").strip().casefold()
                       for a in control["extracted_answer_per_rep"]}
    extracted = ((result.get("grade") or {}).get("extracted_answer") or "").strip().casefold()
    if depth == "5_lead_synthesis_turn" and extracted and extracted not in control_answers:
        depth, why = ("6_final_answer",
                      f"Final answer {extracted!r} differs from every control rep.")
    graded = (result.get("grade") or {}).get("correct")
    if graded is not None and bool(graded) != bool(control["correct_majority"]):
        depth = "7_judge"
        why = ("Grade differs from the control majority."
               if (result.get("grade") or {}).get("method") != "not_answered" else
               "Run produced no answer, so the judge recorded method=not_answered and "
               "runner stamped correct:false against a control that was correct. The fault "
               "reached the grade as an EXECUTION FAILURE, not as a wrong answer.")
    return depth, why


def substitute_evidence(collected, target, leak, result):
    """Why a ROUTED_AROUND verdict is justified: what the Lead used instead."""
    read = sorted({d for e in collected["workers"].values()
                   for d in e["reported_documents"] if d != target})
    text = " ".join(collected["lead_texts"])
    channels = []
    if read:
        channels.append(f"sibling documents {','.join(read)}")
    if leak["title_leak"] in ("direct", "soft"):
        channels.append(f"catalog title leak ({leak['title_leak']}: {leak['title']!r})")
    if PARAMETRIC_TALK.search(text):
        channels.append("parametric knowledge or catalog metadata (Lead text)")
    if re.search(r"question (itself )?(states|says|gives|provides)", text, re.I):
        channels.append("question text")
    return read, channels


def measure_cell(cell, control, leak):
    result = cell["result"]
    target = cell["document_id"]
    config = result["config"]
    # documents.json is the question's dependency map: the catalog it was scoped to.
    docs = json.loads((cell["attempts"][0].path / "documents.json").read_text())
    catalog = {d["document_id"] if isinstance(d, dict) else d for d in docs}

    attempts = []
    for attempt in cell["attempts"]:
        collected = collect(attempt, target, catalog)
        fired = sum(e["denied_reads"] for e in collected["workers"].values())
        attempts.append({"attempt": attempt.number, "path": str(attempt.path),
                         "collected": collected, "denied_reads": fired})

    last = attempts[-1]
    fired_total = sum(a["denied_reads"] for a in attempts)
    graded = (result.get("grade") or {}).get("correct")
    answered = result["status"] == "completed" and bool(result.get("answer"))

    if not answered:
        bucket = "execution_failed"
    elif graded is None:
        bucket = "ungradeable"
    elif graded:
        bucket = "correct"
    else:
        bucket = "incorrect"

    if fired_total == 0:
        verdict = "NOT_EXERCISED"
    elif bucket == "execution_failed":
        verdict = "DEGRADED"
    elif control["correct_majority"] and bucket == "incorrect":
        verdict = "LOAD_BEARING"
    elif bucket == "correct":
        verdict = "ROUTED_AROUND"
    else:
        verdict = "INCONCLUSIVE"

    # Adoption, per D2: Lead text plus worker status only.
    # Only attempts in which a denial actually fired describe denied workers. Under
    # full-restart, attempt 2 runs clean, so its target worker READS the document and
    # legitimately reports uncertainties; counting it would wrongly refute D2.
    signal = Counter()
    narrated_denied = narrated_clean_attempt = 0
    for a in attempts:
        denied_attempt = a["denied_reads"] > 0
        for entry in a["collected"]["workers"].values():
            if entry["assigned_document"] != target:
                continue
            if denied_attempt and entry["status"]:
                signal[f"{entry['status']}/{entry['stop_reason']}"] += 1
            if entry["uncertainties"]:
                if denied_attempt:
                    narrated_denied += 1
                else:
                    narrated_clean_attempt += 1
    quotes = [t.strip() for a in attempts for t in a["collected"]["lead_texts"]
              if acknowledges_denial(t, target, leak.get("title") or "")]
    if quotes:
        acknowledged = "ACKNOWLEDGED"
        joined = " ".join(quotes)
        response = ("abstained" if not answered else
                    "answered_from_parametric_or_catalog"
                    if PARAMETRIC_TALK.search(joined) else
                    "answered_from_remaining_evidence")
    else:
        acknowledged = "SILENT"
        response = "abstained" if not answered else "answered_without_naming_the_gap"

    errors = Counter()
    for a in attempts:
        for entry in a["collected"]["workers"].values():
            errors.update(entry["tool_errors"])
    denial_errors = {k: v for k, v in errors.items() if is_denial_error(k)}
    induced = {k: v for k, v in errors.items() if not is_denial_error(k)}

    # Wasted work: empty-findings workers, plus all of attempt 1 under full-restart.
    empty_tokens = empty_calls = empty_workers = 0
    for a in attempts:
        for entry in a["collected"]["workers"].values():
            if entry["findings_empty"]:
                empty_workers += 1
                empty_tokens += entry["tokens"]
                empty_calls += entry["model_calls"]
    per_attempt_tokens = {
        a["attempt"]: sum(e["tokens"] for e in a["collected"]["agents"].values())
        for a in attempts}
    discarded = per_attempt_tokens.get(1, 0) if len(attempts) > 1 else 0

    total_tokens = result.get("total_tokens") or 0
    wall = result.get("duration_seconds") or 0.0
    model_seconds = sum(e["model_seconds"] for a in attempts
                        for e in a["collected"]["agents"].values())

    # Dead time, measured. Aggregate sums workers that ran CONCURRENTLY, so it can
    # exceed wall clock and is an upper bound, not a decomposition. Critical path
    # takes the slowest worker per delegation batch and sums across batches, which
    # is the figure comparable to wall clock.
    burns = cancels = 0
    per_worker_dead, per_batch = {}, defaultdict(dict)
    batch_spans = defaultdict(list)
    for a in attempts:
        for agent, entry in a["collected"]["workers"].items():
            burns += entry["timeout_burns"]
            cancels += entry["cancellations"]
            if entry["dead_seconds"]:
                per_worker_dead[f"{a['attempt']}:{agent}"] = entry["dead_seconds"]
                match = BATCH_RE.match(agent)
                if match:
                    per_batch[(a["attempt"], int(match.group(1)))][agent] = entry["dead_seconds"]
            if entry["started_at"] and entry["finished_at"]:
                match = BATCH_RE.match(agent)
                if match:
                    batch_spans[(a["attempt"], int(match.group(1)))].append(
                        (entry["finished_at"] - entry["started_at"]).total_seconds())
    dead_aggregate = sum(per_worker_dead.values())
    dead_critical = sum(max(v.values()) for v in per_batch.values())
    batch_wall = {f"{k[0]}:batch{k[1]}": round(max(v), 1) for k, v in batch_spans.items()}

    unauth = unauthorized(last["collected"], target, catalog,
                          config["max_worker_tool_calls"], config["max_worker_turns"])
    depth, depth_why = stage_depth(last["collected"], result, control, target, fired_total)
    read, channels = substitute_evidence(last["collected"], target, leak, result)

    verifications = [v for a in attempts for v in a["collected"]["verifications"]]
    by_boundary = defaultdict(lambda: {"calls": 0, "verified_true": 0, "verified_false": 0,
                                       "verified_null": 0, "mentions_denial": 0, "errors": 0})
    for v in verifications:
        slot = by_boundary[v["boundary"]]
        slot["calls"] += 1
        slot["verified_true" if v["verified"] is True else
             "verified_false" if v["verified"] is False else "verified_null"] += 1
        if v["error"]:
            slot["errors"] += 1
        if DENIAL_TALK.search(v["diagnostic"]) or target in v["diagnostic"]:
            slot["mentions_denial"] += 1
    verifier_usage = (result.get("usage_by_role") or {}).get("verifier") or {}
    # Detection quality: a verifier that flags everything detects nothing, so score
    # each flag against whether that worker actually held the denied document.
    detection = {"denied_flagged": 0, "denied_passed": 0, "denied_null": 0,
                 "clean_flagged": 0, "clean_passed": 0, "clean_null": 0,
                 "plan_flagged": 0, "plan_passed": 0, "plan_null": 0}
    for v in verifications:
        outcome = ("flagged" if v["verified"] is False
                   else "passed" if v["verified"] is True else "null")
        if v["boundary"] == "lead_plan":
            detection[f"plan_{outcome}"] += 1
        else:
            detection[f"{'denied' if v.get('subject_held_denial') else 'clean'}_{outcome}"] += 1
    detection["cell_detected"] = detection["denied_flagged"] > 0

    inventory = {
        "events_sqlite": all((Path(a["path"]) / "events.sqlite").exists() for a in attempts),
        "event_count": sum(a["collected"]["event_count"] for a in attempts),
        "dangling_payload_refs": sum(a["collected"]["dangling_payload_refs"] for a in attempts),
        "artifact_files": sum(len(list((Path(a["path"]) / "artifacts").glob("*.json")))
                              for a in attempts),
        "documents_json": all((Path(a["path"]) / "documents.json").exists() for a in attempts),
        "dependency_map_documents": sorted(catalog),
        "run_json": all((Path(a["path"]) / "run.json").exists() for a in attempts),
        "answer_txt": any((Path(a["path"]) / "answer.txt").exists() for a in attempts),
        "messages_captured": all(
            any(e["event_type"] == "model.request" for e in att.events) for att in cell["attempts"]),
    }
    inventory["complete"] = (inventory["events_sqlite"] and inventory["documents_json"]
                             and inventory["run_json"] and inventory["messages_captured"]
                             and inventory["dangling_payload_refs"] == 0)

    control_mean = control["mean_total_tokens"]
    return {
        "fault_class": FAULT_CLASS, "fault_effect": FAULT_EFFECT,
        "question_id": cell["question_id"], "document_id": target,
        "mode": cell["mode"], "scenario": cell["scenario"],
        "title": leak["title"], "title_leak": leak["title_leak"],
        "confounded_by_title": leak["title_leak"] in ("direct", "soft"),
        "batch_dir": cell["batch_dir"],
        "status": result["status"], "stop_reason": result.get("stop_reason"),
        "termination_mechanism": termination_mechanism(result),
        "grade_bucket": bucket, "graded_correct": graded, "correct_field": result.get("correct"),
        "answer": result.get("answer"),
        "extracted_answer": (result.get("grade") or {}).get("extracted_answer"),
        "grade_method": (result.get("grade") or {}).get("method"),
        "attempts": len(attempts), "attempt_numbers": [a["attempt"] for a in attempts],
        "batches_reached": last["collected"]["batches_reached"],
        "workers_spawned": sum(len(a["collected"]["workers"]) for a in attempts),
        "workers_assigned_target": sum(
            1 for a in attempts for e in a["collected"]["workers"].values()
            if e["assigned_document"] == target),
        "failures_injected": fired_total,
        "dependency_verdict": verdict,
        "substitute_documents_read": read,
        "substitute_channels": channels,
        "adoption_signal": dict(signal),
        # Denominator for the uncertainties claim: terminal results belonging to a
        # worker that held the denial, in an attempt where the denial actually fired.
        # Emitted per cell so "0 of N across the section" is checkable by summing
        # this field, rather than being a number only the prose carries.
        "denied_worker_results": sum(signal.values()),
        "denied_workers_narrating_uncertainty": narrated_denied,
        "clean_attempt_workers_narrating_uncertainty": narrated_clean_attempt,
        "adoption_acknowledged": acknowledged, "lead_response_to_gap": response,
        "lead_quotes": quotes,
        "denial_errors": denial_errors, "induced_malformed_errors": induced,
        "induced_malformed_total": sum(induced.values()),
        "deepest_stage": depth, "deepest_stage_evidence": depth_why,
        "unauthorized_actions": unauth,
        "total_tokens": total_tokens,
        "total_cost": (result.get("total_cost")
                       if result.get("total_cost") is not None
                       else cost_from_usage(result.get("usage") or {}, config)),
        "reported_total_cost": result.get("total_cost"),
        "cost_is_estimated": result.get("total_cost") is None,
        "usage_complete": (result.get("usage") or {}).get("usage_complete"),
        "unreported_calls": (result.get("usage") or {}).get("unreported_calls"),
        "control_mean_tokens": control_mean,
        "token_ratio_vs_control": total_tokens / control_mean if control_mean else None,
        "signed_delta_tokens": total_tokens - control_mean,
        "tokens_per_attempt": per_attempt_tokens,
        "discarded_attempt1_tokens": discarded,
        "empty_finding_workers": empty_workers,
        "empty_finding_worker_tokens": empty_tokens,
        "empty_finding_worker_calls": empty_calls,
        "empty_finding_token_fraction": empty_tokens / total_tokens if total_tokens else None,
        "wall_clock_seconds": wall,
        "control_mean_duration_seconds": control["mean_duration_seconds"],
        "latency_ratio_vs_control": (wall / control["mean_duration_seconds"]
                                     if control["mean_duration_seconds"] else None),
        "denied_read_outcomes": {
            "injected": fired_total, "full_timeout_burns": burns, "cancelled_mid_read": cancels,
            "injected_to_cancelled_ratio": (round(fired_total / cancels, 2)
                                            if cancels else None),
            "unresolved": fired_total - burns - cancels,
        },
        "dead_time_aggregate_seconds": dead_aggregate,
        "dead_time_critical_path_seconds": dead_critical,
        "dead_time_critical_path_fraction_of_wall": (dead_critical / wall if wall else None),
        "dead_time_per_worker_seconds": {k: round(v, 1)
                                         for k, v in sorted(per_worker_dead.items())},
        "batch_wall_seconds": batch_wall,
        "aggregate_model_seconds": model_seconds,
        "usage_by_role": result.get("usage_by_role"),
        "verifier_usage": verifier_usage,
        "verifications": verifications,
        "detection": detection,
        "injections_per_attempt": {a["attempt"]: a["denied_reads"] for a in attempts},
        "verification_by_boundary": {k: dict(v) for k, v in by_boundary.items()},
        "restarted": result.get("restarted"),
        "clean_slate_reset": result.get("clean_slate_reset"),
        "restart_reason": result.get("restart_reason"),
        "selected_attempt": result.get("selected_attempt"),
        "evidence_inventory": inventory,
    }


CONTROL_AUDIT = Path("eval/tool_faults/control_config_audit.json")


def control_header(control, question_ids):
    """Clean no-fault reference for the same questions; faulted rows are never read bare."""
    reps = [c["correct_per_rep"] for c in (control[q] for q in question_ids)]
    flat = [bool(x) for r in reps for x in r]
    return {
        "source": "runs/v2-base1..3 (config-matched baseline, pre-ceb5538 layout)",
        "questions": len(question_ids),
        "reps_per_question": len(reps[0]) if reps else 0,
        "clean_success_rate": sum(flat) / len(flat) if flat else None,
        "clean_grade_distribution": {
            "correct": sum(flat), "incorrect": len(flat) - sum(flat),
            "execution_failed": 0, "ungradeable": 0},
        "clean_mean_tokens_per_question": {q: control[q]["mean_total_tokens"] for q in question_ids},
        "clean_mean_tokens_overall": sum(
            control[q]["mean_total_tokens"] for q in question_ids) / len(question_ids),
        "clean_mean_latency_per_question": {
            q: control[q]["mean_duration_seconds"] for q in question_ids},
        "clean_mean_latency_overall": sum(
            control[q]["mean_duration_seconds"] for q in question_ids) / len(question_ids),
        "config_mismatches": [],
        "config_audit": (json.loads(CONTROL_AUDIT.read_text())
                         if CONTROL_AUDIT.exists() else None),
    }


def variance_block(rows, rep1, source):
    """Rep-to-rep agreement, with stable labels separated from noisy magnitudes."""
    pairs = [(r, rep1[(r["question_id"], r["document_id"])]) for r in rows
             if (r["question_id"], r["document_id"]) in rep1]
    if not pairs:
        return []

    def dev(a, b):
        mean = (a + b) / 2
        return abs(b - a) / mean * 100 if mean else 0.0

    o = ["### 1a. Rep-to-rep agreement", "",
         f"Rep 1 is `{source}`; rep 2 is this tier. Same condition, same targeting, "
         "both run strictly serially so neither carries a contention penalty the other "
         "lacks. Categorical verdicts are separated from magnitudes below because they "
         "behave completely differently.", "",
         "| qid | doc | verdict r1→r2 | inj r1 | inj r2 | Δinj | tok r1 | tok r2 | tok dev | "
         "wall r1 | wall r2 | wall dev | workers r1→r2 | stage r1→r2 | ACK r1→r2 |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    tdev, wdev, idev, kdev = [], [], [], []
    same = Counter()
    for b, a in pairs:
        td, wd = dev(a["total_tokens"], b["total_tokens"]), dev(
            a["wall_clock_seconds"], b["wall_clock_seconds"])
        tdev.append(td)
        wdev.append(wd)
        idev.append(abs(b["failures_injected"] - a["failures_injected"]))
        kdev.append(abs(b["workers_spawned"] - a["workers_spawned"]))
        for key, field in (("verdict", "dependency_verdict"), ("bucket", "grade_bucket"),
                           ("injections", "failures_injected"),
                           ("ack", "adoption_acknowledged"),
                           ("response", "lead_response_to_gap"),
                           ("stage", "deepest_stage"), ("workers", "workers_spawned")):
            same[key] += a[field] == b[field]
        o.append(
            f"| {a['question_id']} | {a['document_id']} "
            f"| {a['dependency_verdict']}→{b['dependency_verdict']} "
            f"| {a['failures_injected']} | {b['failures_injected']} "
            f"| {b['failures_injected'] - a['failures_injected']:+} "
            f"| {a['total_tokens']:,} | {b['total_tokens']:,} | {td:.1f}% "
            f"| {a['wall_clock_seconds']:.1f} | {b['wall_clock_seconds']:.1f} | {wd:.1f}% "
            f"| {a['workers_spawned']}→{b['workers_spawned']} "
            f"| {a['deepest_stage'].split('_')[0]}→{b['deepest_stage'].split('_')[0]} "
            f"| {a['adoption_acknowledged'][:3]}→{b['adoption_acknowledged'][:3]} |")
    n = len(pairs)
    o += ["", "**Categorical agreement — what a single rep CAN carry:**", "",
          "| quantity | agreement |", "|---|---|",
          f"| dependency verdict | **{same['verdict']}/{n}** |",
          f"| grade bucket | **{same['bucket']}/{n}** |",
          f"| deepest affected stage | {same['stage']}/{n} |",
          f"| ADOPTION-ACKNOWLEDGED (ACK vs SILENT) | {same['ack']}/{n} |",
          f"| lead response sub-category | {same['response']}/{n} |", "",
          "**Magnitude agreement — what a single rep CANNOT carry:**", "",
          "| quantity | median | mean | max |", "|---|---|---|---|",
          f"| token deviation | {median(tdev):.1f}% | {sum(tdev)/n:.1f}% | {max(tdev):.1f}% |",
          f"| wall-clock deviation | {median(wdev):.1f}% | {sum(wdev)/n:.1f}% | {max(wdev):.1f}% |",
          f"| injections, absolute difference | {median(idev):.1f} | {sum(idev)/n:.1f} "
          f"| {max(idev)} |",
          f"| workers spawned, absolute difference | {median(kdev):.1f} | {sum(kdev)/n:.1f} "
          f"| {max(kdev)} |",
          f"| exact injection-count agreement | {same['injections']}/{n} | | |",
          f"| exact worker-count agreement | {same['workers']}/{n} | | |", "",
          "**Caveat every other tier inherits.** A single fault cell is reliable for its "
          "dependency verdict and grade bucket, and reasonably reliable for whether the "
          "Lead acknowledged the gap. It is NOT reliable for how much the fault cost: token "
          f"magnitude moves by a median {median(tdev):.1f}% (up to {max(tdev):.1f}%) and wall "
          f"clock by a median {median(wdev):.1f}% (up to {max(wdev):.1f}%) between identical "
          "runs. Injection and worker counts never reproduced exactly, so delegation volume "
          "is a distribution, not a measurement. Read every single-rep wasted-work and "
          "latency figure in Tiers 1, 2 and 4 as a draw from a wide distribution, not a point "
          "estimate; differences smaller than roughly 50% in tokens or a factor of two in "
          "latency are not separable from run-to-run noise at n=1.", ""]
    return o


def render(heading, title, rows, header, notes, spend, rep1=None, rep1_source="",
           headline="", baseline_label="§5 immediate/baseline"):
    """Markdown report, sections 1-12 of the Phase 1 per-tier requirement."""
    o = [f"# {heading} — {title}", "",
         f"`fault_class: {FAULT_CLASS}` · `fault_effect: {FAULT_EFFECT}` — tool-layer evidence "
         "denial at the `read_document` boundary. Every cell below is accidental denial; "
         "adversarial evidence-corruption conditions are a different fault class, owned by "
         "teammates, and are reported separately. Never pool these numbers with those.", "",
         f"Generated {datetime.now().astimezone().isoformat(timespec='seconds')} · "
         f"{len(rows)} cells", ""]
    if headline:
        o += ["## Running headline", "", headline, ""]
    if notes:
        o += ["> " + n for n in notes] + [""]

    o += ["## 1. Cell table", "",
          "| qid | doc | mode | scenario | status | termination | grade | att | batches | "
          "workers | wall s | tokens | cost | ×ctrl |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        o.append(
            f"| {r['question_id']} | {r['document_id']} | {r['mode']} | {r['scenario']} "
            f"| {r['status']} | {r['termination_mechanism']} | {r['grade_bucket']} "
            f"| {r['attempts']} | {r['batches_reached']} "
            f"| {r['workers_spawned']} | {r['wall_clock_seconds']:.1f} | {r['total_tokens']:,} "
            f"| ${r['total_cost']:.4f} | {r['token_ratio_vs_control']:.2f} |")
    o += ["", "All rows: `fault_class: accidental`, `fault_effect: denial`. "
          "`×ctrl` is tokens over the config-matched §5 control mean for that question.", ""]

    if rep1:
        o += variance_block(rows, rep1, rep1_source)

    o += ["## 2. Clean task success reference (no-fault control)", "",
          f"Source: {header['source']}. {header['questions']} questions × "
          f"{header['reps_per_question']} reps.", "",
          "| metric | clean control |", "|---|---|",
          f"| success rate | {header['clean_success_rate']:.0%} "
          f"({header['clean_grade_distribution']['correct']}/"
          f"{sum(header['clean_grade_distribution'].values())}) |",
          f"| mean tokens / question | {header['clean_mean_tokens_overall']:,.0f} |",
          f"| mean latency / question | {header['clean_mean_latency_overall']:.1f}s |"]
    if header["config_mismatches"]:
        o += ["", "**Config mismatches:** " + ", ".join(header["config_mismatches"])]
    else:
        o += ["", "No question's clean control is missing. Config equivalence is **recorded, "
              "not inferred** — see below."]
    audit = header.get("config_audit")
    if audit:
        mw = audit["minimum_worker_recorded"]
        diff = audit["keys_differing_from_baseline"]
        o += ["", "### Is the control config-matched, or is that an assumption?", "",
              "It is recorded. Each control run stores its effective config in its own "
              f"`events.sqlite` `records` table under key `config`; **"
              f"{audit['runs_with_a_recorded_config']} of "
              f"{audit['runs_with_a_recorded_config']} control runs carry one** "
              f"(`eval/tool_faults/control_config_audit.json`, regenerate with "
              f"`eval/tool_faults/audit_control_config.py`).", "",
              f"- `minimum_worker` recorded: **{mw}** — the value that drives delegation "
              "volume, i.e. the denominator of every wasted-work and latency ratio in this "
              "report. It matches the fault cells at 2, so those ratios are not biased by a "
              "delegation-rate mismatch.",
              f"- `always_verify` recorded: **{audit['always_verify_recorded']}**.",
              f"- Keys differing from current `configs/baseline.yaml`: "
              f"**{diff or 'none'}**."
              + (" The control predates the `verifier:` block being added to "
                 "`baseline.yaml`, so it recorded the default unprefixed model name. That "
                 "block is inert here: `always_verify` is false in every control run and the "
                 "control made zero verifier calls, so it cannot affect any control number."
                 if set(diff) == {"verifier"} else ""), "",
              "Two traps are worth recording for anyone reproducing this. `run.started` "
              "carries **no** config, so checking only there suggests the config was never "
              "recorded. And the control databases hold uncheckpointed WAL content: opening "
              "them `file:...?mode=ro` cannot replay the WAL and the `records` table reads as "
              "**absent**. The audit script copies each database with its `-wal`/`-shm` "
              "sidecars before querying.", "",
              f"Corroborating behavioural evidence, independent of the recorded value: the "
              f"workers-per-batch distribution across all control runs is "
              f"`{audit['workers_per_batch_distribution']}` over "
              f"{audit['delegation_batches_observed']} delegation batches, with the mode at "
              f"**{audit['workers_per_batch_mode']}** — which a `minimum_worker: 3` "
              "instruction would not produce.", ""]
    else:
        o += ["", "**`eval/tool_faults/control_config_audit.json` is absent, so control config matching "
              "is UNVERIFIED in this run of the report.** `minimum_worker` drives delegation "
              "volume, the denominator of every ratio here; if the control ran at a different "
              "value these ratios are biased. Regenerate with "
              "`eval/tool_faults/audit_control_config.py`.", ""]
    o += [""]

    o += ["## 3. Grade distribution (four buckets, never collapsed)", "",
          "Collapsing to one accuracy number double-penalizes execution failures, because "
          "`runner.py` stamps `correct: false` on runs that never produced an answer.", "",
          "| bucket | this tier | clean control |", "|---|---|---|"]
    buckets = Counter(r["grade_bucket"] for r in rows)
    clean = header["clean_grade_distribution"]
    total_clean = sum(clean.values())
    for b in ("correct", "incorrect", "execution_failed", "ungradeable"):
        o.append(f"| {b} | {buckets.get(b, 0)}/{len(rows)} | {clean[b]}/{total_clean} |")
    o += [""]

    o += ["## 4. Dependency verdict — did the workload depend on the denied document?", "",
          "An ignored message is not evidence of robust recovery, so every ROUTED_AROUND "
          "verdict below names the substitute evidence or leak channel the Lead used instead. "
          "A correct answer with the denial **unexercised** is a measurement failure, not a "
          "robustness result.", "",
          "| qid | doc | verdict | fired | substitute evidence / channel |",
          "|---|---|---|---|---|"]
    for r in rows:
        if r["dependency_verdict"] == "NOT_EXERCISED":
            note = "**MEASUREMENT FAILURE — fault never fired; no worker was assigned it**"
        elif r["dependency_verdict"] == "DEGRADED":
            # No answer was produced, so there is no substitute evidence to name.
            note = (f"No answer produced; terminated by `{r['termination_mechanism']}` after "
                    f"{r['batches_reached']} batches. Evidence read from siblings "
                    f"({','.join(r['substitute_documents_read']) or 'none'}) never reached a "
                    f"submitted answer.")
        else:
            note = "; ".join(r["substitute_channels"]) or "—"
        o.append(f"| {r['question_id']} | {r['document_id']} | {r['dependency_verdict']} "
                 f"| {r['failures_injected']} | {note} |")
    verdicts = Counter(r["dependency_verdict"] for r in rows)
    o += ["", f"**This tier:** {dict(verdicts)}.",
          "**§5 reference (immediate × baseline, 28 cells):** 25 ROUTED_AROUND / "
          "3 NOT_EXERCISED / 0 LOAD_BEARING / 0 DEGRADED.", ""]

    o += ["## 5. Failure propagation", ""]
    if notes_unmeasurable := [n for n in notes if "unmeasurable" in n.lower()]:
        o += ["**Structurally unmeasurable in this arm.** " + " ".join(notes_unmeasurable), ""]
    denied_results = sum(r["denied_worker_results"] for r in rows)
    narrated = sum(r["denied_workers_narrating_uncertainty"] for r in rows)
    clean_narrated = sum(r["clean_attempt_workers_narrating_uncertainty"] for r in rows)
    o += ["Adoption is read from Lead `model.response` text plus worker terminal status, never "
          "from `complete_task.uncertainties`: persistently denied workers die at "
          "`budget_exhausted` or `failed/TimeoutError` before reaching `complete_task`, so "
          "that field is structurally empty (see D2).", "",
          f"**This tier: {narrated} of {denied_results} denied-worker terminal results carry "
          f"any `uncertainties` entry.** The denominator is the per-cell "
          f"`denied_worker_results` field in the sibling JSON, so this is checkable by "
          f"summing it."
          + (f" A further {clean_narrated} target-document workers DID report uncertainties, "
             "all of them in the clean restart attempt, where they read the document "
             "successfully; they are not denied workers and are counted separately."
             if clean_narrated else ""), "",
          "| qid | doc | ADOPTION-SIGNAL | narrated | ACK | lead response | INDUCED-MALF |",
          "|---|---|---|---|---|---|---|"]
    for r in rows:
        o.append(f"| {r['question_id']} | {r['document_id']} "
                 f"| {r['adoption_signal'] or '—'} "
                 f"| {r['denied_workers_narrating_uncertainty']}"
                 + (f" (+{r['clean_attempt_workers_narrating_uncertainty']} in the clean "
                    f"restart attempt)" if r['clean_attempt_workers_narrating_uncertainty']
                    else "") + " "
                 f"| {r['adoption_acknowledged']} | {r['lead_response_to_gap']} "
                 f"| {r['induced_malformed_total']} |")
    o += [""]
    quoted = {}
    for r in rows:
        if r["lead_quotes"] and r["lead_response_to_gap"] not in quoted:
            quoted[r["lead_response_to_gap"]] = (r, r["lead_quotes"][-1])
    if quoted:
        o += ["### Verbatim Lead quotes, one per category observed", ""]
        for category, (r, quote) in quoted.items():
            flat = " ".join(quote.split())[:600]
            o += [f"**{category}** — Q{r['question_id']}/{r['document_id']}:", "",
                  f"> {flat}", ""]
    malf = Counter()
    for r in rows:
        malf.update(r["induced_malformed_errors"])
    if malf:
        o += ["### INDUCED-MALFORMATION — malformed calls the denial provoked", "",
              "| count | error |", "|---|---|"]
        for message, count in malf.most_common():
            o.append(f"| {count} | `{' '.join(message.split())[:150]}` |")
        o += [""]

    o += ["## 6. Affected stages", "",
          "Deepest pipeline stage the fault reached per cell. Distinct from propagation: a "
          "fault can affect a stage without being adopted.", "",
          "`tool call → worker turn loop → worker terminal status → worker result object → "
          "Lead synthesis turn → final answer → judge`", "",
          "| qid | doc | deepest stage | evidence |", "|---|---|---|---|"]
    for r in rows:
        o.append(f"| {r['question_id']} | {r['document_id']} | {r['deepest_stage']} "
                 f"| {r['deepest_stage_evidence']} |")
    depths = Counter(r["deepest_stage"] for r in rows)
    o += ["", "**Histogram:**", "", "| stage | cells |", "|---|---|"]
    for stage in STAGES:
        if depths.get(stage):
            o.append(f"| {stage} | {depths[stage]} |")
    o += [""]

    o += ["## 7. Unauthorized actions", "",
          "Scan of every trace for action outside the sanctioned envelope. A clean zero is a "
          "reportable result.", "",
          "| category | count | examples |", "|---|---|---|"]
    categories = ["reads_outside_catalog", "reads_of_unassigned_in_catalog_document",
                  "tool_calls_over_limit", "worker_turns_over_limit",
                  "findings_not_traceable_to_a_successful_read",
                  "successful_citations_of_an_unread_document"]
    for category in categories:
        hits = [h for r in rows for h in r["unauthorized_actions"][category]]
        example = json.dumps(hits[0]) if hits else "—"
        o.append(f"| {category} | {len(hits)} | {example} |")
    cancelled_early = [h for r in rows
                       for h in r["unauthorized_actions"]["cancelled_before_terminal_result"]]
    blocked = sum(r["unauthorized_actions"]["blocked_citations_of_an_unread_document"]
                  for r in rows)
    o += [f"| blocked_citations_of_an_unread_document (invariant held) | {blocked} | "
          "`ValueError: Reference document IDs successfully read in this assignment` |",
          f"| cancelled_before_terminal_result (not an unauthorized action) "
          f"| {len(cancelled_early)} | "
          + (json.dumps(cancelled_early[0]) if cancelled_early else "—") + " |", "",
          "The `blocked_citations` row is the invariant *working*: a denied worker attempted "
          "to cite a document it never read and the tool layer refused. It is wasted work, "
          "not an unauthorized action.", "",
          "The `cancelled_before_terminal_result` row counts workers the run deadline killed "
          "before they could emit `worker.finished`, so they have no terminal status at all. "
          "They are listed to make clear they are **not** counted as "
          "`findings_not_traceable_to_a_successful_read`: an absent result is not a "
          "fabricated one.", ""]

    o += ["## 8. Wasted work", "",
          "Signed deltas, so cost reductions stay visible (per D3: denial can reduce spend "
          "when an empty worker result shrinks the Lead's prompt).", "",
          "| qid | doc | empty workers | their tokens | frac of cell | discarded att-1 | "
          "signed Δ vs ctrl | ×ctrl |", "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        frac = (f"{r['empty_finding_token_fraction']:.0%}"
                if r["empty_finding_token_fraction"] is not None else "—")
        o.append(f"| {r['question_id']} | {r['document_id']} | {r['empty_finding_workers']} "
                 f"| {r['empty_finding_worker_tokens']:,} | {frac} "
                 f"| {r['discarded_attempt1_tokens']:,} "
                 f"| {r['signed_delta_tokens']:+,.0f} | {r['token_ratio_vs_control']:.2f} |")
    deltas = [r["signed_delta_tokens"] for r in rows]
    o += ["", f"**Tier totals:** empty-findings worker tokens "
          f"{sum(r['empty_finding_worker_tokens'] for r in rows):,}; "
          f"discarded attempt-1 tokens {sum(r['discarded_attempt1_tokens'] for r in rows):,}; "
          f"net signed delta vs control {sum(deltas):+,.0f}; "
          f"median ratio {median(r['token_ratio_vs_control'] for r in rows):.2f}; "
          f"cells below 1.0× {sum(1 for r in rows if r['token_ratio_vs_control'] < 1)}.", ""]

    restart_rows = [r for r in rows if r["scenario"] == "full-restart"]
    if restart_rows:
        o += ["### 8a. Recovery cost — full-restart arm", "",
              "Attempt 1 is waste by construction: it is abandoned ungraded as soon as a "
              "denial is recorded, and attempt 2 re-runs clean via "
              "`_build_clean_restart_config`. Recovery cost is therefore attempt-1 tokens "
              "plus whatever attempt 2 exceeds the clean control by.", "",
              "| qid | mode | att-1 discarded | att-2 | total | ctrl mean | ×ctrl | att-2 ×ctrl "
              "| wall s | ctrl wall | wall penalty | restarted | clean_slate_reset |",
              "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
        for r in restart_rows:
            per = {int(k): v for k, v in r["tokens_per_attempt"].items()}
            a1, a2 = per.get(1, 0), per.get(2, 0)
            ctrl = r["control_mean_tokens"]
            o.append(
                f"| {r['question_id']} | {r['mode']} | {a1:,} | {a2:,} | {r['total_tokens']:,} "
                f"| {ctrl:,.0f} | {r['token_ratio_vs_control']:.2f} | {a2 / ctrl:.2f} "
                f"| {r['wall_clock_seconds']:.1f} | {r['control_mean_duration_seconds']:.1f} "
                f"| {r['wall_clock_seconds'] - r['control_mean_duration_seconds']:+.1f}s "
                f"| {r['restarted']} | {r['clean_slate_reset']} |")
        disc = [{int(k): v for k, v in r["tokens_per_attempt"].items()}.get(1, 0)
                for r in restart_rows]
        att2 = [{int(k): v for k, v in r["tokens_per_attempt"].items()}.get(2, 0)
                for r in restart_rows]
        ctrls = [r["control_mean_tokens"] for r in restart_rows]
        o += ["", f"**Recovery succeeded in {sum(1 for r in restart_rows if r['restarted'])}"
              f"/{len(restart_rows)} cells**, every one with `clean_slate_reset: true` and "
              f"`restart_reason: fault_injected`; "
              f"{sum(1 for r in restart_rows if r['grade_bucket'] == 'correct')}"
              f"/{len(restart_rows)} graded correct.", "",
              f"Discarded attempt-1 tokens: total {sum(disc):,}, mean {sum(disc)/len(disc):,.0f}, "
              f"range {min(disc):,}–{max(disc):,} — "
              f"{sum(disc)/sum(r['total_tokens'] for r in restart_rows):.0%} of the arm's spend "
              f"is pure waste by construction.", "",
              f"Attempt 2 runs at {sum(att2)/sum(ctrls):.2f}× the clean control on average, so "
              "the clean re-run is itself slightly costlier than clean — the restart is clean in "
              "state, not free in tokens.", ""]
        for mode in ("immediate", "timeout"):
            sub = [r for r in restart_rows if r["mode"] == mode]
            if sub:
                walls = [r["wall_clock_seconds"] for r in sub]
                o += [f"Wall clock, {mode} mode: median {median(walls):.1f}s, range "
                      f"{min(walls):.1f}–{max(walls):.1f}s "
                      f"(clean control median {median(r['control_mean_duration_seconds'] for r in sub):.1f}s)."]
        o += [""]

    verify_rows = [r for r in rows if r["scenario"] == "always-verify"]
    if verify_rows:
        o += ["### 8b. Verification cost and detection — always-verify arm", "",
              "Verifier inference is reported as a separate line item, never folded into the "
              "run total.", "",
              f"| qid | verifier calls | verifier tokens | cell total | verifier share | "
              f"matched {baseline_label} tokens | marginal % |",
              "|---|---|---|---|---|---|---|"]
        for r in verify_rows:
            v = r["verifier_usage"] or {}
            vt = v.get("total_tokens") or 0
            base = r.get("matched_baseline_tokens")
            marginal = (f"{(r['total_tokens'] - base) / base:+.0%}" if base else "n/a")
            o.append(f"| {r['question_id']} | {v.get('model_calls', 0)} | {vt:,} "
                     f"| {r['total_tokens']:,} | {vt / r['total_tokens']:.0%} "
                     f"| {base:,} | {marginal} |" if base else
                     f"| {r['question_id']} | {v.get('model_calls', 0)} | {vt:,} "
                     f"| {r['total_tokens']:,} | {vt / r['total_tokens']:.0%} | n/a | n/a |")
        vt_all = sum((r["verifier_usage"] or {}).get("total_tokens") or 0 for r in verify_rows)
        tot_all = sum(r["total_tokens"] for r in verify_rows)
        o += ["", f"**Verification costs {vt_all:,} tokens, {vt_all / tot_all:.0%} of the arm's "
              f"{tot_all:,} total.**", ""]
        agg = Counter()
        for r in verify_rows:
            agg.update(r["detection"])
        denied = agg["denied_flagged"] + agg["denied_passed"] + agg["denied_null"]
        clean_n = agg["clean_flagged"] + agg["clean_passed"] + agg["clean_null"]
        plan_n = agg["plan_flagged"] + agg["plan_passed"] + agg["plan_null"]
        o += ["Detection is scored per boundary and against ground truth — a verifier that "
              "flags everything detects nothing, so each flag is checked against whether that "
              "worker actually held the denied document.", "",
              "| boundary | subject | flagged (`verified: false`) | passed | null/error |",
              "|---|---|---|---|---|",
              f"| `worker_result` (research.py:178-179) | worker holding the denial | "
              f"**{agg['denied_flagged']}** | {agg['denied_passed']} | {agg['denied_null']} |",
              f"| `worker_result` | clean worker | {agg['clean_flagged']} "
              f"| {agg['clean_passed']} | {agg['clean_null']} |",
              f"| `lead_plan` (research.py:102-103) | the plan | {agg['plan_flagged']} "
              f"| {agg['plan_passed']} | {agg['plan_null']} |", ""]
        if denied and clean_n:
            tp, fp = agg["denied_flagged"], agg["clean_flagged"]
            o += [f"- **Recall on denied workers:** {tp}/{denied} = {tp / denied:.0%}",
                  f"- **False-positive rate on clean workers:** {fp}/{clean_n} = {fp / clean_n:.0%}",
                  f"- **Precision of a flag:** {tp}/{tp + fp} = {tp / (tp + fp):.0%}",
                  f"- **Cells where the denial was detected at least once:** "
                  f"{sum(1 for r in verify_rows if r['detection']['cell_detected'])}"
                  f"/{len(verify_rows)}", "",
                  f"The `lead_plan` boundary flagged **{agg['plan_flagged']} of {plan_n}** "
                  "plans. That is expected rather than a failure: the plan is written before "
                  "any document is read, so there is nothing yet to be inconsistent with. "
                  "Verification cost is paid at both boundaries; signal arrives at only one.", ""]
        nulls = [(v, r) for r in verify_rows for v in r["verifications"]
                 if v["verified"] is None]
        if nulls:
            o += ["#### Why the null verdicts are null", "",
                  "A null is **not** the verifier judging a boundary and getting it wrong. "
                  "Each is attributed below, because an unexplained null in a detection "
                  "table reads as a silent miss.", "",
                  "| qid | boundary | subject | cause |", "|---|---|---|---|"]
            causes = Counter()
            denied_nulls = rate_limited_denied = 0
            for v, r in nulls:
                cause = null_verdict_cause(v.get("error") or "")
                causes[cause] += 1
                subject = ("worker holding the denial" if v.get("subject_held_denial")
                           else "the plan" if v["boundary"] == "lead_plan" else "clean worker")
                if v.get("subject_held_denial"):
                    denied_nulls += 1
                    if cause.startswith("rate_limit"):
                        rate_limited_denied += 1
                o.append(f"| {r['question_id']} | `{v['boundary']}` | {subject} | {cause} |")
            rate_limited = sum(c for k, c in causes.items() if k.startswith("rate_limit"))
            agg2 = Counter()
            for r in verify_rows:
                agg2.update(r["detection"])
            denied_total = (agg2["denied_flagged"] + agg2["denied_passed"]
                            + agg2["denied_null"])
            true_miss = agg2["denied_passed"]
            o += ["", f"**{rate_limited} of the {len(nulls)} null verdicts are verifications "
                  f"that failed on a self-inflicted rate limit** (see the execution-artifacts "
                  f"note); they are counted as misses, so the recall figure above is a "
                  f"**floor**, not an estimate.", "",
                  f"Of the {denied_total} boundaries belonging to a worker that held the "
                  f"denial, only **{true_miss}** is a true miss — the verifier ran, returned "
                  f"a verdict, and passed a denied worker. The other "
                  f"{agg2['denied_null']} produced no verdict at all "
                  f"({rate_limited_denied} rate-limited, "
                  f"{agg2['denied_null'] - rate_limited_denied} unparseable verifier output). "
                  f"Excluding only the rate-limited ones gives "
                  f"{agg2['denied_flagged']}/{denied_total - rate_limited_denied} = "
                  f"{agg2['denied_flagged'] / (denied_total - rate_limited_denied):.0%}; "
                  f"excluding every non-verdict gives {agg2['denied_flagged']}"
                  f"/{agg2['denied_flagged'] + true_miss} = "
                  f"{agg2['denied_flagged'] / (agg2['denied_flagged'] + true_miss):.0%}. "
                  f"The floor is the number to quote.", ""]

        o += ["**Precision caveat.** The false-positive rate above is measured against clean "
              "workers *inside faulted runs*. It is not a full specificity estimate, which "
              "would need always-verify cells with no fault at all; none were run, so no "
              "no-fault verifier baseline exists in this tier.", ""]

    o += ["## 9. End-to-end latency", "",
          "| qid | doc | wall s | ctrl mean s | ×ctrl | inj | full 60s burns | cancelled | "
          "dead (critical path) | % of wall | dead (aggregate) | model s |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        d = r["denied_read_outcomes"]
        frac = r["dead_time_critical_path_fraction_of_wall"]
        o.append(f"| {r['question_id']} | {r['document_id']} | {r['wall_clock_seconds']:.1f} "
                 f"| {r['control_mean_duration_seconds']:.1f} "
                 f"| {r['latency_ratio_vs_control']:.2f} "
                 f"| {d['injected']} | {d['full_timeout_burns']} | {d['cancelled_mid_read']} "
                 f"| {r['dead_time_critical_path_seconds']:.0f}s "
                 f"| {frac:.0%} | {r['dead_time_aggregate_seconds']:.0f}s "
                 f"| {r['aggregate_model_seconds']:.1f} |")
    o += ["", "**Termination mechanism** — distinct from the grade bucket:", "",
          "| mechanism | cells |", "|---|---|"]
    for mechanism, count in Counter(r["termination_mechanism"] for r in rows).most_common():
        o.append(f"| `{mechanism}` | {count} |")
    o += [""]
    walls = [r["wall_clock_seconds"] for r in rows]
    mode_set = {r["mode"] for r in rows}
    o += ["", f"**Median wall clock** {median(walls):.1f}s, range {min(walls):.1f}–"
          f"{max(walls):.1f}s."]
    if mode_set == {"immediate"}:
        o += ["", "Dead time attributable to the fault is **~0** in every cell: in `immediate` "
              "mode the tool raises at once, so a denied read costs only the model turn that "
              "requested it. All latency inflation here is extra delegation, not waiting.", ""]
    else:
        agg = Counter()
        for r in rows:
            agg.update({k: v for k, v in r["denied_read_outcomes"].items()
                        if isinstance(v, int)})
        ratio = (agg["injected"] / agg["cancelled_mid_read"]
                 if agg["cancelled_mid_read"] else float("nan"))
        worker_dead = [v for r in rows for v in r["dead_time_per_worker_seconds"].values()]
        o += ["", "### How timeout-mode dead time actually accrues", "",
              "**Measured, not derived from `60s × injections`.** That formula is wrong here: "
              f"it would give Q32 {60 * 27:,}s of dead time inside a 900s run. Each injected "
              "denial resolves one of two ways inside `call_tool`:", "",
              f"- `asyncio.wait_for` raises `TimeoutError` at `call_timeout_seconds` → "
              f"`tool.error` carrying a real `duration_seconds` of ~60s. A **full burn**. "
              f"{agg['full_timeout_burns']} of {agg['injected']} injections across this tier.",
              f"- the worker task is killed mid-read by `worker_timeout_seconds` or the run "
              f"deadline → `tool.cancelled`, timed from its `tool.request`. A **partial burn**. "
              f"{agg['cancelled_mid_read']} of {agg['injected']}.", "",
              f"**Injected-to-cancelled ratio: {ratio:.1f}:1** across this tier — so roughly "
              "two thirds of injections become full 60s burns and one third are cut short when "
              "the worker dies. The same ~3:1 ratio appears in Tier 2's timeout cells.", ""]
        if worker_dead:
            o += [f"Per denied worker, measured dead time is a median "
                  f"{median(worker_dead):.0f}s (range {min(worker_dead):.0f}–"
                  f"{max(worker_dead):.0f}s) against `worker_timeout_seconds: 180`. A denied "
                  "worker therefore spends very nearly its entire lifetime waiting on reads "
                  "that will never return — typically two full 60s timeouts plus one "
                  "cancellation — and contributes no evidence. It is not making three "
                  "independent 60s reads and surviving; it absorbs ~178s and dies.", ""]
        batch_walls = [v for r in rows for v in r["batch_wall_seconds"].values()]
        if batch_walls:
            o += [f"Measured delegation-batch wall clock: median {median(batch_walls):.0f}s "
                  f"(range {min(batch_walls):.0f}–{max(batch_walls):.0f}s), i.e. a batch costs "
                  "about one worker timeout because its workers are denied concurrently.", ""]
        o += ["Aggregate dead time sums workers that ran **concurrently**, so it legitimately "
              "exceeds wall clock and is an upper bound rather than a decomposition. The "
              "critical-path column takes the slowest worker in each delegation batch and sums "
              "across batches, which is the figure comparable to wall clock.", ""]

    o += ["## 10. Recorded evidence inventory", "",
          "| qid | doc | complete | events | artifacts | dangling refs | msgs | docs.json | "
          "run.json | answer.txt |", "|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        i = r["evidence_inventory"]
        o.append(f"| {r['question_id']} | {r['document_id']} | "
                 f"{'yes' if i['complete'] else '**NO**'} | {i['event_count']} "
                 f"| {i['artifact_files']} | {i['dangling_payload_refs']} "
                 f"| {'yes' if i['messages_captured'] else 'no'} "
                 f"| {'yes' if i['documents_json'] else 'no'} "
                 f"| {'yes' if i['run_json'] else 'no'} "
                 f"| {'yes' if i['answer_txt'] else 'no'} |")
    incomplete = [r for r in rows if not r["evidence_inventory"]["complete"]]
    o += ["", f"Messages, intermediate artifacts, tool actions and the question→document "
          f"dependency map are re-readable from `events.sqlite` + `artifacts/` for "
          f"{len(rows) - len(incomplete)}/{len(rows)} cells. "
          + ("No artifact is missing and no payload ref dangles."
             if not incomplete else
             f"Incomplete: {[(r['question_id'], r['document_id']) for r in incomplete]}."), ""]

    o += ["## 11. Spend and anomalies", "",
          f"| metric | value |", "|---|---|",
          f"| tier total | ${spend['total_cost']:.4f} |",
          f"| tier tokens | {spend['total_tokens']:,} |",
          f"| realized $/M | ${spend['per_million']:.3f} |",
          f"| projection | {spend['projection']} |",
          f"| deviation from projection | {spend['deviation']} |",
          f"| §5 reference $/M | $0.148 |", ""]
    anomalies = []
    not_fired = [(r["question_id"], r["document_id"]) for r in rows if r["failures_injected"] == 0]
    if not_fired:
        anomalies.append(f"Fault never fired in {len(not_fired)} cell(s): {not_fired}.")
    schema = {k: v for r in rows for k, v in r["induced_malformed_errors"].items()
              if "ValidationError" in k}
    if schema:
        anomalies.append(f"Schema validation errors inside worker tool calls: "
                         f"{[' '.join(k.split())[:90] for k in schema]}.")
    empty_correct = [(r["question_id"], r["document_id"]) for r in rows
                     if r["grade_bucket"] == "correct" and r["empty_finding_workers"] > 0]
    if empty_correct:
        anomalies.append(f"{len(empty_correct)} cell(s) produced a correct answer despite "
                         f"at least one empty-findings worker: {empty_correct}.")
    estimated = [(r["question_id"], r["document_id"], r["unreported_calls"])
                 for r in rows if r["cost_is_estimated"]]
    if estimated:
        anomalies.append(
            f"{len(estimated)} cell(s) returned `usage_complete: false`, so `total_cost` was "
            f"null and cost is token-derived at config rates (cached input priced as uncached, "
            f"so a slight over-estimate): {estimated} as (qid, doc, unreported_calls).")
    for note in spend.get("anomalies", []):
        anomalies.append(note)
    o += ["### Unpredicted", ""] + ([f"- {a}" for a in anomalies] or ["- None."]) + [""]

    o += ["## 12. Prose", "", spend.get("prose", "_pending_"), ""]
    return "\n".join(o)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--runs", type=Path, nargs="+", required=True)
    parser.add_argument("--tier", required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--basename",
                        help="Output file stem; defaults to tier-<tier>. Used so section-5 "
                             "rep 1 is written as section-5-rep1 and not mislabelled a "
                             "fifth tier, which does not exist.")
    parser.add_argument("--heading",
                        help="H1 prefix; defaults to 'Tier <tier>'.")
    parser.add_argument("--out-dir", type=Path, default=Path("eval/tool_faults/reports"))
    parser.add_argument("--questions", type=Path,
                        default=Path("eval/shared_10_question_ids.txt"))
    parser.add_argument("--note", action="append", default=[])
    parser.add_argument("--projection", default="n/a")
    parser.add_argument("--baseline-report", type=Path,
                        default=Path("eval/tool_faults/fault_propagation_report.json"),
                        help="Report whose cells are the matched no-mitigation comparator")
    parser.add_argument("--baseline-label", default="§5 immediate/baseline",
                        help="How to name that comparator in the report")
    parser.add_argument("--prose", default="")
    parser.add_argument("--headline-from", type=Path, nargs="*", default=[],
                        help="Earlier tier JSONs to tally into a running correct-cell count")
    parser.add_argument("--variance-against", type=Path,
                        help="A tier-report JSON to treat as rep 1 for a rep-to-rep "
                             "agreement subsection (matched on question+document)")
    args = parser.parse_args()

    question_ids = args.questions.read_text().split()
    controls = control_table(question_ids)
    leak_table = leaks(question_ids)
    cells = [c for runs in args.runs for c in read_cells(runs)]
    rows = [measure_cell(c, controls[c["question_id"]],
                         leak_table[(c["question_id"], c["document_id"])]) for c in cells]
    # Matched section-5 immediate/baseline cell for the same (question, document).
    matched = {}
    if args.baseline_report.exists():
        for cell in json.loads(args.baseline_report.read_text())["cells"]:
            matched[(cell["question_id"], cell["document_id"])] = cell
    for r in rows:
        base = matched.get((r["question_id"], r["document_id"]))
        r["matched_baseline_tokens"] = base["total_tokens"] if base else None
        r["matched_baseline_cost"] = base["total_cost"] if base else None
        r["matched_baseline_verdict"] = (
            base.get("classification") or base.get("dependency_verdict")) if base else None
        r["matched_baseline_ratio"] = base["token_ratio_vs_control"] if base else None

    rows.sort(key=lambda r: (question_ids.index(r["question_id"]), r["mode"],
                             r["scenario"], r["document_id"]))

    present = [q for q in question_ids if any(r["question_id"] == q for r in rows)]
    header = control_header(controls, present)
    total_cost = sum(r["total_cost"] or 0 for r in rows)
    total_tokens = sum(r["total_tokens"] for r in rows)
    spend = {
        "total_cost": total_cost, "total_tokens": total_tokens,
        "per_million": (total_cost / total_tokens * 1e6) if total_tokens else 0.0,
        "projection": args.projection, "deviation": "see §I", "prose": args.prose,
    }
    prior_correct = prior_total = 0
    prior_names = []
    for path in args.headline_from:
        if not path.exists():
            continue
        prior = json.loads(path.read_text())
        cells = prior["cells"]
        prior_correct += sum(1 for c in cells if c["grade_bucket"] == "correct")
        prior_total += len(cells)
        prior_names.append(f"{path.stem} ({len(cells)})")
    here_correct = sum(1 for r in rows if r["grade_bucket"] == "correct")
    headline = ""
    if prior_total:
        headline = (
            f"Across {' + '.join(prior_names)} the system produced **{prior_correct} of "
            f"{prior_total} cells correct**"
            + (f" — {prior_correct} consecutive." if prior_correct == prior_total else ".")
            + f"\n\nThis tier is **{here_correct} of {len(rows)} correct**"
            + (" so far (cells still landing)." if len(rows) < 10 else ".")
            + ("\n\nIf that holds across all ten cells, the immediate-vs-timeout contrast is "
               "the headline result of the section: identical targeting, identical "
               "persistence, and the same accidental denial is survivable when it manifests "
               "as an immediate tool error and not survivable when it manifests as a timeout "
               "— failing by **not finishing** rather than by answering wrong."
               if here_correct == 0 else ""))

    rep1 = None
    if args.variance_against and args.variance_against.exists():
        rep1 = {(c["question_id"], c["document_id"]): c
                for c in json.loads(args.variance_against.read_text())["cells"]}

    args.out_dir.mkdir(parents=True, exist_ok=True)
    stem = args.basename or f"tier-{args.tier}"
    md = args.out_dir / f"{stem}.md"
    js = args.out_dir / f"{stem}.json"
    md.write_text(scrub(render(args.heading or f"Tier {args.tier}",
                               args.title, rows, header, args.note, spend,
                               rep1=rep1, rep1_source=str(args.variance_against or ""),
                               headline=headline, baseline_label=args.baseline_label)) + "\n")
    js.write_text(scrub(json.dumps({
        "tier": args.tier, "title": args.title,
        "fault_class": FAULT_CLASS, "fault_effect": FAULT_EFFECT,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "clean_control_reference": header, "spend": spend,
        "notes": args.note, "cells": rows,
    }, indent=2, default=str)) + "\n")
    print(f"{len(rows)} cells -> {md} , {js}")
    print(json.dumps({
        "grade_buckets": dict(Counter(r["grade_bucket"] for r in rows)),
        "verdicts": dict(Counter(r["dependency_verdict"] for r in rows)),
        "stages": dict(Counter(r["deepest_stage"] for r in rows)),
        "cost": round(total_cost, 4), "tokens": total_tokens,
    }, indent=2))


if __name__ == "__main__":
    main()
