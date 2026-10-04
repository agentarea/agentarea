"""Web toolset: search the public web and read pages into the conversation.

``search_web`` asks the deployment's SearXNG-compatible search service.
``fetch_webpage`` reads one page and returns its text inline, the way hosted
fetch tools (Anthropic ``web_fetch``, Gemini ``url_context``) do: nothing is
written to storage or to the sandbox. Downloading a file is a different
capability with a different boundary, the sandbox shell and its egress policy.

The page is requested through a client the caller supplies. In agent execution
that client resolves, vets and pins the address of every hop, so an
agent-supplied URL cannot reach the platform's own network. Without one, fetch
fails closed.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from html.parser import HTMLParser
from typing import Any, ClassVar
from urllib.parse import urljoin

import httpx

from .decorator_tool import Toolset, tool_method
from .tool_authz import unrestricted
from .tool_definition import toolset

_TEXT_CONTENT_TYPES: tuple[str, ...] = (
    "text/",
    "application/json",
    "application/xml",
    "application/xhtml",
    "application/javascript",
    "application/ld+json",
)
_DEFAULT_TIMEOUT_SECONDS: float = 15.0
_INLINE_TEXT_CHAR_LIMIT: int = 50_000
_MAX_FETCH_BYTES: int = 5 * 1024 * 1024  # raw page ceiling; the inline text is far smaller
_MAX_REDIRECTS: int = 5
_USER_AGENT: str = "Mozilla/5.0 (compatible; AgentArea/1.0; +https://agentarea.ai)"

FetchClientFactory = Callable[..., httpx.AsyncClient]


class _TextExtractor(HTMLParser):
    """Tiny stdlib-only HTML→text. Drops <script>/<style> bodies."""

    _DROP_TAGS: ClassVar[frozenset[str]] = frozenset({"script", "style", "noscript", "head"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._chunks: list[str] = []
        self._skip_depth: int = 0

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        if tag in self._DROP_TAGS:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in self._DROP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0:
            self._chunks.append(data)

    def text(self) -> str:
        return re.sub(r"\s+", " ", "".join(self._chunks)).strip()


class _HTMLSummaryExtractor(_TextExtractor):
    """Extract visible text plus a compact list of links from HTML."""

    def __init__(self, base_url: str) -> None:
        super().__init__()
        self._base_url = base_url
        self._current_href: str | None = None
        self._current_text: list[str] = []
        self.links: list[dict[str, str]] = []

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        super().handle_starttag(tag, attrs)
        if tag != "a" or self._skip_depth != 0:
            return
        href = next((value for name, value in attrs if name == "href"), None)
        if href:
            self._current_href = urljoin(self._base_url, href)
            self._current_text = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._current_href:
            link_text = re.sub(r"\s+", " ", "".join(self._current_text)).strip()
            self.links.append({"href": self._current_href, "text": link_text})
            self._current_href = None
            self._current_text = []
        super().handle_endtag(tag)

    def handle_data(self, data: str) -> None:
        super().handle_data(data)
        if self._skip_depth == 0 and self._current_href:
            self._current_text.append(data)


def _is_text_content_type(content_type: str | None) -> bool:
    if not content_type:
        return False
    ct = content_type.lower().split(";", 1)[0].strip()
    return any(ct.startswith(p) for p in _TEXT_CONTENT_TYPES)


def _is_html_content_type(content_type: str | None) -> bool:
    if not content_type:
        return False
    ct = content_type.lower().split(";", 1)[0].strip()
    return ct in ("text/html", "application/xhtml+xml")


@toolset(
    namespace="agentarea/web",
    display_name="Web Tools",
    description="Search the web and read web pages into the conversation.",
    category="information",
    plane="runtime",
    requires_user_confirmation=True,
)
class WebToolset(Toolset):
    """Search the web and read pages inline; never persists what it fetches."""

    def __init__(
        self,
        search_web: bool = True,
        fetch_webpage: bool = True,
        search_base_url: str | None = None,
        http_client_factory: FetchClientFactory | None = None,
    ) -> None:
        super().__init__()
        self._search_enabled = search_web
        self._fetch_enabled = fetch_webpage
        self.search_base_url = search_base_url.rstrip("/") if search_base_url else None
        self._http_client_factory = http_client_factory

    @tool_method(effect="read")
    @unrestricted("the public web; reads and writes no workspace state")
    async def search_web(
        self,
        query: str,
        max_results: int = 8,
    ) -> str:
        """Search the public web through the deployment's configured search service."""
        if not self._search_enabled:
            return "Error: search_web is disabled for this toolset instance"
        if self.search_base_url is None:
            return (
                "Error: web search is not configured; set AGENTAREA_TOOL_SEARCH_URL "
                "to a SearXNG-compatible endpoint"
            )
        if not query or not query.strip():
            return "Error: query must be non-empty"
        if isinstance(max_results, bool) or not 1 <= max_results <= 20:
            return "Error: max_results must be between 1 and 20"

        try:
            async with httpx.AsyncClient(
                timeout=_DEFAULT_TIMEOUT_SECONDS,
                follow_redirects=True,
            ) as client:
                response = await client.get(
                    f"{self.search_base_url}/search",
                    params={"q": query.strip(), "format": "json"},
                    headers={"Accept": "application/json"},
                )
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            return f"Error searching the web: {exc}"

        raw_results = payload.get("results")
        if not isinstance(raw_results, list):
            return "Error: search service returned an invalid response"

        results: list[dict[str, Any]] = []
        for item in raw_results[:max_results]:
            if not isinstance(item, dict):
                continue
            url = item.get("url")
            title = item.get("title")
            if not isinstance(url, str) or not isinstance(title, str):
                continue
            results.append(
                {
                    "title": title,
                    "url": url,
                    "snippet": str(item.get("content") or ""),
                    "engine": str(item.get("engine") or ""),
                }
            )
        return json.dumps(
            {"query": query.strip(), "results": results},
            ensure_ascii=False,
        )

    @tool_method(effect="read")
    @unrestricted("the public web; reads and writes no workspace state")
    async def fetch_webpage(
        self,
        url: str,
        timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
    ) -> str:
        """Read a web page (HTML, text or JSON) and return its text and links.

        Only links that already appeared in this task can be opened: the
        request itself, search results, or pages fetched earlier. Images,
        PDFs, archives and other binary content are refused; download those
        with the sandbox shell instead.

        Returns a JSON envelope:

            { "url": ..., "status": int, "content_type": str,
              "truncated": bool, "text": "...",
              "extracted_text": "...", "links": [...] }   # last two for HTML
        """
        if not self._fetch_enabled:
            return "Error: fetch_webpage is disabled for this toolset instance"
        if not url or not (url.startswith("http://") or url.startswith("https://")):
            return f"Error: url must be http(s); got {url!r}"
        if self._http_client_factory is None:
            return "Error: web fetching is not configured for this toolset instance"

        try:
            async with (
                self._http_client_factory(
                    timeout=timeout_seconds,
                    follow_redirects=True,
                    max_redirects=_MAX_REDIRECTS,
                ) as client,
                client.stream(
                    "GET",
                    url,
                    headers={
                        "Accept": "text/html,application/xhtml+xml,text/plain,application/json;q=0.9,*/*;q=0.1",
                        "User-Agent": _USER_AGENT,
                    },
                ) as resp,
            ):
                content_type = resp.headers.get("content-type")
                if not _is_text_content_type(content_type):
                    return (
                        f"Error: {url} returned {content_type or 'an unknown content type'}; "
                        "fetch_webpage reads text pages only. Download files with the "
                        "sandbox shell instead."
                    )
                body = bytearray()
                async for chunk in resp.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > _MAX_FETCH_BYTES:
                        return f"Error: {url} is larger than {_MAX_FETCH_BYTES} bytes"
                final_url = str(resp.url)
                status = resp.status_code
                encoding = resp.charset_encoding or "utf-8"
        except httpx.HTTPError as e:
            return f"Error fetching {url}: {e}"

        try:
            text = bytes(body).decode(encoding, errors="replace")
        except LookupError:  # the server named a charset Python does not know
            text = bytes(body).decode("utf-8", errors="replace")

        payload: dict[str, Any] = {
            "url": final_url,
            "status": status,
            "content_type": content_type,
            "truncated": len(text) > _INLINE_TEXT_CHAR_LIMIT,
        }
        if _is_html_content_type(content_type):
            extractor = _HTMLSummaryExtractor(final_url)
            try:
                extractor.feed(text)
                payload["extracted_text"] = extractor.text()[:_INLINE_TEXT_CHAR_LIMIT]
                payload["links"] = extractor.links[:100]
            except Exception:
                payload["extracted_text"] = ""
                payload["links"] = []
        payload["text"] = text[:_INLINE_TEXT_CHAR_LIMIT]
        # Unescaped, so the links a later fetch may follow read in the
        # conversation exactly as they will be requested.
        return json.dumps(payload, ensure_ascii=False)
