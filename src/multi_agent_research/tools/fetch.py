"""Bounded HTTP fetching; HTML and plain text only in the first baseline."""

import asyncio
import ipaddress
import socket
from urllib.parse import urlsplit

import httpx
from bs4 import BeautifulSoup


async def validate_url(url):
    parts = urlsplit(url)
    if parts.scheme not in {"https", "http"} or not parts.hostname or parts.username:
        raise ValueError("Expected public HTTP(S) URL")
    addresses = await asyncio.to_thread(socket.getaddrinfo, parts.hostname, parts.port or 443)
    if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
        raise ValueError("Non-public destinations are not supported")


class PageFetcher:
    async def fetch(self, url, max_bytes):
        async with httpx.AsyncClient(timeout=60, follow_redirects=False, trust_env=False) as client:
            for _ in range(6):
                await validate_url(url)
                async with client.stream("GET", url) as response:
                    if response.is_redirect:
                        url = str(response.url.join(response.headers["location"]))
                        continue
                    response.raise_for_status()
                    media = response.headers.get("content-type", "").lower()
                    if not any(
                        t in media for t in ("text/html", "text/plain", "application/xhtml")
                    ):
                        raise ValueError("Only HTML and plain-text documents are supported")
                    data = bytearray()
                    async for chunk in response.aiter_bytes():
                        data.extend(chunk)
                        if len(data) > max_bytes:
                            raise ValueError("Document exceeds download byte limit")
                    raw = bytes(data).decode(response.encoding or "utf-8", errors="replace")
                    if "html" in media:
                        soup = BeautifulSoup(raw, "html.parser")
                        title = soup.title.get_text(" ", strip=True) if soup.title else url
                        for tag in soup(["script", "style", "nav", "footer"]):
                            tag.decompose()
                        text = soup.get_text("\n", strip=True)
                    else:
                        title, text = url, raw
                    return {"url": str(response.url), "title": title, "raw": raw, "text": text}
            raise ValueError("Too many redirects")
