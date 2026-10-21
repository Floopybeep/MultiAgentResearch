import json

import httpx
import pytest

from multi_agent_research.tools import fetch, search


def mock_client(monkeypatch, handler):
    client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: client(transport=httpx.MockTransport(handler), **kwargs),
    )


async def test_search_request_and_normalized_results(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "fixture-key")

    def handler(request):
        body = json.loads(request.content)
        assert body["query"] == "topic" and body["max_results"] == 3
        assert body["api_key"] == "fixture-key"
        return httpx.Response(
            200,
            json={
                "results": [
                    {"title": "Evidence", "url": "https://example.org", "content": "Snippet"}
                ]
            },
        )

    mock_client(monkeypatch, handler)
    assert await search.TavilySearch().search("topic", 3) == [
        {"title": "Evidence", "url": "https://example.org", "snippet": "Snippet"}
    ]


async def test_fetch_extraction_and_redirect_validation(monkeypatch):
    visited = []

    async def check(url):
        visited.append(url)

    monkeypatch.setattr(fetch, "validate_url", check)

    def handler(request):
        if request.url.path == "/start":
            return httpx.Response(302, headers={"location": "/page"})
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            text="<title>Title</title><script>ignore()</script><p>Evidence.</p>",
        )

    mock_client(monkeypatch, handler)
    result = await fetch.PageFetcher().fetch("https://example.org/start", 1000)
    assert result["url"] == "https://example.org/page"
    assert result["title"] == "Title"
    assert "ignore()" not in result["text"]
    assert "ignore()" in result["raw"]
    assert visited == ["https://example.org/start", "https://example.org/page"]


async def test_fetch_size_limit(monkeypatch):
    async def check(url):
        pass

    monkeypatch.setattr(fetch, "validate_url", check)
    mock_client(
        monkeypatch,
        lambda request: httpx.Response(200, headers={"content-type": "text/plain"}, text="x" * 100),
    )
    with pytest.raises(ValueError, match="byte limit"):
        await fetch.PageFetcher().fetch("https://example.org", 10)
