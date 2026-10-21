import json

import httpx
import pytest
from langchain_core.messages import HumanMessage, ToolMessage
from langchain_openai import ChatOpenAI
from pydantic import ValidationError

from multi_agent_research.config import ModelConfig, RunConfig
from multi_agent_research.models import adapter
from multi_agent_research.schemas import web_search


@pytest.mark.parametrize("missing", ["OPENAI_API_KEY", "OPENAI_BASE_URL"])
def test_required_environment(monkeypatch, missing):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://gateway.example/v1")
    monkeypatch.delenv(missing)
    with pytest.raises(KeyError, match=missing):
        adapter.OpenAIChatCompletionsAdapter()


@pytest.mark.parametrize("key", ["OPENAI_API_KEY", "OPENAI_BASE_URL"])
def test_empty_environment(monkeypatch, key):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://gateway.example/v1")
    monkeypatch.setenv(key, " ")
    with pytest.raises(ValueError, match="nonempty"):
        adapter.OpenAIChatCompletionsAdapter()


@pytest.mark.parametrize("option", [
    "api_key", "openai_api_key", "base_url", "openai_api_base",
    "use_responses_api", "model_provider", "model_kwargs", "extra_body",
    "max_retries", "http_async_client", "default_headers",
])
def test_transport_options_rejected(option):
    with pytest.raises(ValidationError):
        ModelConfig(options={option: "override"})


def test_model_defaults():
    config = RunConfig()
    assert {config.lead.model, config.worker.model, config.citation.model} == {"gpt-6-luna"}
    assert ModelConfig(options={"reasoning_effort": "low"}).options["reasoning_effort"] == "low"


async def test_async_chat_completions_transport(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://gateway.example/v1")
    monkeypatch.setenv("OPENAI_API_BASE", "https://wrong.example/v1")
    requests = []

    async def respond(request):
        assert request.url == "https://gateway.example/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer test-key"
        payload = json.loads(request.content)
        requests.append(payload)
        message = {"role": "assistant", "content": "Done."}
        if len(requests) == 1:
            message = {
                "role": "assistant", "content": None,
                "tool_calls": [{
                    "id": "call_1", "type": "function",
                    "function": {"name": "web_search", "arguments": '{"query":"alpha"}'},
                }],
            }
        return httpx.Response(200, json={
            "id": "chatcmpl-test", "object": "chat.completion", "created": 1,
            "model": payload["model"],
            "choices": [{"index": 0, "message": message,
                         "finish_reason": "tool_calls" if len(requests) == 1 else "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        })

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        def create_model(**kwargs):
            return ChatOpenAI(**kwargs, http_async_client=client)

        monkeypatch.setattr(adapter, "ChatOpenAI", create_model)
        transport = adapter.OpenAIChatCompletionsAdapter()
        config = ModelConfig(max_output_tokens=123)
        messages = [HumanMessage(content="Research alpha.")]
        result = await transport.invoke("lead", "lead", messages, [web_search], config)
        assert result.tool_calls[0]["args"] == {"query": "alpha"}
        assert result.usage_metadata["total_tokens"] == 15
        messages += [result, ToolMessage(content="Evidence.", tool_call_id="call_1")]
        final = await transport.invoke("lead", "lead", messages, [web_search], config)
        assert final.content == "Done."
        # Citation calls omit tools and still use Chat Completions.
        await transport.invoke("citation", "citation", [HumanMessage(content="Cite.")], [], config)
        assert transport.models["lead"].max_retries == 0
        assert transport.models["lead"].use_responses_api is False

    assert requests[0]["model"] == "gpt-6-luna"
    assert requests[0]["max_completion_tokens"] == 123
    assert requests[0]["tools"][0]["function"]["name"] == "web_search"
    assert requests[1]["messages"][-1]["role"] == "tool"
    assert "tools" not in requests[2]
