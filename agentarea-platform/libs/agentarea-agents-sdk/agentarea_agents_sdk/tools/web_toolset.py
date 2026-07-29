"""Web fetch toolset.

Tools that pull bytes from the public internet route binary responses through
the same canonical task-workspace repository the file and shell tools use. The LLM never sees raw bytes — for
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
from urllib.parse import urljoin, urlparse

import httpx

from .decorator_tool import Toolset, tool_method
from .file_toolset import StorageClient, WorkspaceRepositoryClient
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


@toolset(
    namespace="agentarea/web",
    display_name="Web Tools",
    description="Fetch URLs; binary responses are stored as task artifacts.",
    category="information",
    requires_user_confirmation=True,
)
class WebToolset(Toolset):
    """Fetch URLs and route binary responses to artifact storage.

    Workspace scoping mirrors ``FileToolset``: every production binary write
    becomes ``downloads/{filename}`` in the task manifest. ``StorageClient``
    remains available for standalone SDK use; text-only mode needs neither.
    """

    def __init__(
        self,
        storage: StorageClient | None = None,
        workspace_repository: WorkspaceRepositoryClient | None = None,
        workspace_id: str | None = None,
        task_id: str | None = None,
        lease_owner: str | None = None,
        base_prefix: str = "",
        fetch_webpage: bool = True,
        extract_text: bool = True,
    ) -> None:
        super().__init__()
        self.storage = storage
        self.workspace_repository = workspace_repository
        self.workspace_id = workspace_id or "_standalone"
        self.task_id = task_id or ""
        self.lease_owner = lease_owner or ""
        self.base_prefix = base_prefix.strip("/")
        self._fetch_enabled = fetch_webpage
        self._extract_enabled = extract_text

    def _artifact_path(self, file_name: str) -> str:
        clean = file_name.lstrip("/").replace("..", "_")
        if self.workspace_repository is not None:
            return f"downloads/{clean}"
        if self.base_prefix:
            return f"{self.base_prefix}/downloads/{clean}"
        return f"downloads/{clean}"

    def _public_artifact_path(self, relative_path: str) -> str:
        if self.workspace_repository is not None:
            return f"tasks/{self.task_id}/workspace/{relative_path}"
        return relative_path

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
            async with httpx.AsyncClient(timeout=timeout_seconds, follow_redirects=True) as client:
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
            payload: dict[str, Any] = {
                "url": str(resp.url),
                "status": resp.status_code,
                "content_type": content_type,
                "kind": "text",
                "truncated": len(text) > _INLINE_TEXT_CHAR_LIMIT,
            }
            if _is_html_content_type(content_type):
                extractor = _HTMLSummaryExtractor(str(resp.url))
                try:
                    extractor.feed(text)
                    payload["extracted_text"] = extractor.text()[:_INLINE_TEXT_CHAR_LIMIT]
                    payload["links"] = extractor.links[:100]
                except Exception:
                    payload["extracted_text"] = ""
                    payload["links"] = []
            payload["text"] = text[:_INLINE_TEXT_CHAR_LIMIT]
            return json.dumps(payload)

        # Binary: must persist to an artifact.
        if self.storage is None and self.workspace_repository is None:
            return (
                "Error: response is binary "
                f"({content_type or 'unknown'}) but no artifact storage "
                "is configured for this toolset"
            )

        file_name = _filename_from_url(url, content_type)
        artifact_path = self._artifact_path(file_name)
        try:
            if self.workspace_repository is not None:
                if not self.task_id:
                    return "Error: task_id is required for canonical workspace writes"
                await self.workspace_repository.put(
                    self.workspace_id,
                    self.task_id,
                    artifact_path,
                    body,
                    content_type,
                    owner=self.lease_owner or None,
                )
            else:
                assert self.storage is not None
                await self.storage.put(self.workspace_id, artifact_path, body, content_type)
        except Exception as e:
            return f"Error writing artifact {artifact_path}: {e}"

        return json.dumps(
            {
                "url": str(resp.url),
                "status": resp.status_code,
                "content_type": content_type,
                "kind": "binary",
                "artifact_path": self._public_artifact_path(artifact_path),
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
