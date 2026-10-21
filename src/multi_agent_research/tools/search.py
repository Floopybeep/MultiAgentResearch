import os

import httpx


class TavilySearch:
    async def search(self, query, limit):
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": os.environ["TAVILY_API_KEY"],
                    "query": query,
                    "max_results": limit,
                    "include_answer": False,
                    "include_raw_content": False,
                },
            )
            response.raise_for_status()
            return [
                {"title": r["title"], "url": r["url"], "snippet": r["content"]}
                for r in response.json()["results"]
            ]
