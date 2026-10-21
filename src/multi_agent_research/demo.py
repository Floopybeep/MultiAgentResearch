"""Deterministic offline fixtures; exercise the real graphs and persistence."""

import json

from langchain_core.messages import AIMessage, ToolMessage


def call(name, args, number):
    return {"name": name, "args": args, "id": f"call-{number}", "type": "tool_call"}


class DemoModel:
    def __init__(self):
        self.turns = {}

    async def invoke(self, role, agent_id, messages, tools, config):
        turn = self.turns.get(agent_id, 0)
        self.turns[agent_id] = turn + 1
        calls, content = [], ""
        if role == "lead":
            if turn == 0:
                calls = [
                    call("memory_write", {"plan": "Research alpha and beta, then verify a gap."}, 0)
                ]
            elif turn == 1:
                calls = [
                    call(
                        "run_blocking_subagent",
                        {"prompt": f"Research {topic}. Fetch the source."},
                        i,
                    )
                    for i, topic in enumerate(("alpha", "beta"), 1)
                ]
            elif turn == 2:
                calls = [
                    call("run_blocking_subagent", {"prompt": "Verify gamma as a follow-up."}, 3)
                ]
            else:
                calls = [
                    call(
                        "complete_task",
                        {"report": "Alpha is one.\nBeta is two.\nGamma is three."},
                        4,
                    )
                ]
        elif role == "worker":
            if turn == 0:
                calls = [call("web_search", {"query": messages[1].content}, 0)]
            elif turn == 1:
                calls = [call("web_fetch", {"url": "https://example.org/evidence"}, 1)]
            else:
                evidence = next(
                    json.loads(m.content)
                    for m in reversed(messages)
                    if isinstance(m, ToolMessage) and "source_id" in json.loads(m.content)
                )
                calls = [
                    call(
                        "complete_task",
                        {
                            "report": "Alpha is one; beta is two; gamma is three.",
                            "source_ids": [evidence["source_id"]],
                        },
                        2,
                    )
                ]
        else:
            payload = json.loads(messages[-1].content)
            source = payload["sources"][0]["source_id"]
            content = payload["draft"] + f"[[cite:{source}:p1]]"
        return AIMessage(
            content=content,
            tool_calls=calls,
            usage_metadata={"input_tokens": 100, "output_tokens": 20, "total_tokens": 120},
        )


class DemoSearch:
    async def search(self, query, limit):
        return [
            {
                "title": "Fixture evidence",
                "url": "https://example.org/evidence",
                "snippet": "Alpha, beta, and gamma.",
            }
        ]


class DemoFetcher:
    async def fetch(self, url, max_bytes):
        text = "Alpha is one. Beta is two. Gamma is three."
        return {"url": url, "title": "Fixture evidence", "raw": text, "text": text}
