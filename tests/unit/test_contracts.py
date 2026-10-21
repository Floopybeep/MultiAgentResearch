import json
import sqlite3

import pytest
from pydantic import ValidationError

from multi_agent_research.config import ModelConfig, RunConfig
from multi_agent_research.graphs.citations import validate_citations
from multi_agent_research.observability.events import EventLogger
from multi_agent_research.schemas import SourceDocument, merge_results
from multi_agent_research.storage.artifacts import ArtifactStore
from multi_agent_research.storage.database import Database
from multi_agent_research.tools.fetch import validate_url
from multi_agent_research.tools.memory import PlanMemory


def test_artifacts_immutable_and_verified(tmp_path):
    store = ArtifactStore(tmp_path)
    ref = store.put({"text": "evidence"})
    assert ref == store.put({"text": "evidence"})
    (tmp_path / f"{ref}.json").write_text("corrupt")
    with pytest.raises(ValueError):
        store.get(ref)
    with pytest.raises(ValueError):
        store.get("../outside")


def test_citation_validation():
    source = SourceDocument(
        source_id="s123",
        url="https://example.org",
        final_url="https://example.org",
        title="x",
        retrieved_at="today",
        raw_ref="x",
        paragraphs={"p1": "Fact."},
    )
    assert validate_citations("Fact.", "Fact.[[cite:s123:p1]]", {"s123": source}) == 1
    for bad in (
        "Fact [[cite:s123:p1]]",
        "Fact.[[cite:s123:p2]]",
        "Fact.[[cite:missing:p1]]",
        "Fact.[[cite:broken]]",
    ):
        with pytest.raises(ValueError):
            validate_citations("Fact.", bad, {"s123": source})


def test_config_validation():
    with pytest.raises(ValidationError):
        RunConfig(max_workers_per_batch=0)
    with pytest.raises(ValidationError):
        ModelConfig(options={"api_key": "secret"})


def test_merge_rejects_conflicting_results():
    assert merge_results({"a": 1}, {"b": 2}) == {"a": 1, "b": 2}
    with pytest.raises(ValueError):
        merge_results({"a": 1}, {"a": 2})


def test_logging_redacts_credentials_and_memory_is_persisted(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-secret-credential")
    db = Database(tmp_path / "events.sqlite")
    store = ArtifactStore(tmp_path / "artifacts")
    logger = EventLogger(db, store, "run")
    logger.emit("error", "lead", {"detail": "bad test-secret-credential", "api_key": "anything"})
    payload = json.loads(db.connection.execute("SELECT body FROM events").fetchone()[0])
    assert store.get(payload["payload_ref"]) == {
        "detail": "bad [REDACTED]",
        "api_key": "[REDACTED]",
    }
    memory = PlanMemory(db, store)
    memory.write("Investigate the claim")
    assert memory.read()["plan"] == "Investigate the claim"
    db.close()
    with sqlite3.connect(tmp_path / "events.sqlite") as conn:
        assert conn.execute("SELECT body FROM records WHERE key='plan'").fetchone()


async def test_fetch_rejects_private_destination():
    with pytest.raises(ValueError):
        await validate_url("http://127.0.0.1/secret")
    with pytest.raises(ValueError):
        await validate_url("file:///etc/passwd")
