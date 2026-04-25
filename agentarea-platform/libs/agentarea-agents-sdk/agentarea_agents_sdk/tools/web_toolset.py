"""Web fetch toolset.

Tools that pull bytes from the public internet route them through the same
``StorageClient`` the file tool uses. The LLM never sees raw bytes — for
binary responses (images, PDFs, archives) the tool persists the payload
under the task's artifact scope and returns a JSON description with the
artifact path. Text responses are returned inline (truncated for context).

The convention matches OpenAI Assistants and Anthropic Files API: tools
return references, callers (or downstream tools) fetch the bytes through
the artifact endpoint.
"""

from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlparse

import httpx

from .decorator_tool import Toolset, tool_method
from .file_toolset import StorageClient


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
_MAX_BINARY_BYTES: int = 25 * 1024 * 1024  # 25 MiB hard ceiling per fetch


class _TextExtractor(HTMLParser):
    """Tiny stdlib-only HTML→text. Drops <script>/<style> bodies."""

    _DROP_TAGS = {"script", "style", "noscript", "head"}

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


def _is_text_content_type(content_type: str | None) -> bool:
    if not content_type:
        return False
    ct = content_type.lower().split(";", 1)[0].strip()
    return any(ct.startswith(p) for p in _TEXT_CONTENT_TYPES)


def _filename_from_url(url: str, content_type: str | None) -> str:
    """Pick a sensible filename from URL path + content-type."""
    path = urlparse(url).path or "/"
    name = path.rsplit("/", 1)[-1] or "index"
    if "." in name:
        return name
    ext_map = {
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/gif": ".gif",
        "image/webp": ".webp",
        "image/svg+xml": ".svg",
        "application/pdf": ".pdf",
        "application/zip": ".zip",
        "application/octet-stream": ".bin",
    }
    ext = ""
    if content_type:
        ext = ext_map.get(content_type.lower().split(";", 1)[0].strip(), "")
    return name + (ext or ".bin")


class WebToolset(Toolset):
    """Fetch URLs and route binary responses to artifact storage.

    Workspace scoping mirrors ``FileToolset``: every binary write goes to
    ``{base_prefix}/downloads/{filename}`` under the configured workspace.
    The toolset is usable without a storage client (text-only mode), but
    binary responses become an error in that mode rather than blowing up.
    """

    def __init__(
        self,
        storage: StorageClient | None = None,
        workspace_id: str | None = None,
        base_prefix: str = "",
        fetch_webpage: bool = True,
        extract_text: bool = True,
    ) -> None:
        super().__init__()
        self.storage = storage
        self.workspace_id = workspace_id or "_standalone"
        self.base_prefix = base_prefix.strip("/")
        self._fetch_enabled = fetch_webpage
        self._extract_enabled = extract_text

    def _artifact_path(self, file_name: str) -> str:
        clean = file_name.lstrip("/").replace("..", "_")
        if self.base_prefix:
            return f"{self.base_prefix}/downloads/{clean}"
        return f"downloads/{clean}"

    @tool_method
    async def fetch_webpage(
        self,
        url: str,
        timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
    ) -> str:
        """Fetch a URL. Text comes back inline; binary becomes an artifact.

        Returns a compact JSON envelope so the LLM gets a uniform shape:

            { "url": ..., "status": int, "content_type": str,
              "kind": "text" | "binary",
              "text": "..." }                # when kind=text
            { ..., "kind": "binary", "artifact_path": "tasks/.../foo.png",
              "size": int }                  # when kind=binary

        Binary responses larger than 25 MiB are refused outright — agents
        shouldn't be pulling huge blobs into a task.
        """
        if not self._fetch_enabled:
            return "Error: fetch_webpage is disabled for this toolset instance"
        if not url or not (url.startswith("http://") or url.startswith("https://")):
            return f"Error: url must be http(s); got {url!r}"

        try:
            async with httpx.AsyncClient(
                timeout=timeout_seconds, follow_redirects=True
            ) as client:
                resp = await client.get(url)
        except httpx.HTTPError as e:
            return f"Error fetching {url}: {e}"

        content_type = resp.headers.get("content-type")
        body = resp.content
        if len(body) > _MAX_BINARY_BYTES:
            return (
                f"Error: response body is {len(body)} bytes which exceeds "
                f"the {_MAX_BINARY_BYTES}-byte ceiling"
            )

        if _is_text_content_type(content_type):
            try:
                text = resp.text
            except Exception as e:  # encoding fail: fall back to raw bytes
                return f"Error decoding text body from {url}: {e}"
            return json.dumps(
                {
                    "url": str(resp.url),
                    "status": resp.status_code,
                    "content_type": content_type,
                    "kind": "text",
                    "truncated": len(text) > _INLINE_TEXT_CHAR_LIMIT,
                    "text": text[:_INLINE_TEXT_CHAR_LIMIT],
                }
            )

        # Binary: must persist to an artifact.
        if self.storage is None:
            return (
                "Error: response is binary "
                f"({content_type or 'unknown'}) but no artifact storage "
                "is configured for this toolset"
            )

        file_name = _filename_from_url(url, content_type)
        artifact_path = self._artifact_path(file_name)
        try:
            await self.storage.put(
                self.workspace_id, artifact_path, body, content_type
            )
        except Exception as e:
            return f"Error writing artifact {artifact_path}: {e}"

        return json.dumps(
            {
                "url": str(resp.url),
                "status": resp.status_code,
                "content_type": content_type,
                "kind": "binary",
                "artifact_path": artifact_path,
                "size": len(body),
            }
        )

    @tool_method
    async def extract_text(self, html: str) -> str:
        """Strip HTML to plain text — useful after ``fetch_webpage`` on HTML.

        Drops <script>/<style>/<noscript>/<head> bodies and collapses
        whitespace. For non-HTML input, returns the input unchanged.
        """
        if not self._extract_enabled:
            return "Error: extract_text is disabled for this toolset instance"
        if not html or "<" not in html:
            return html or ""
        parser = _TextExtractor()
        try:
            parser.feed(html)
        except Exception as e:
            return f"Error extracting text: {e}"
        return parser.text()
