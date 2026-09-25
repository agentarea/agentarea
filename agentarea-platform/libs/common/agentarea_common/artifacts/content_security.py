"""Response headers for serving stored bytes back to a browser.

Anything a workspace member or an agent wrote can come back through a
download endpoint, so a response whose Content-Type a browser will execute
inline (HTML, XML, SVG) must never render on the API's own origin — the
Content-Disposition is forced to a plain attachment regardless of the
filename or what an upstream service already reported, and every download
also carries ``X-Content-Type-Options: nosniff``. See issue #483.
"""

from __future__ import annotations

import re
import unicodedata
from urllib.parse import quote

ACTIVE_CONTENT_TYPES = frozenset(
    {
        "text/html",
        "application/xhtml+xml",
        "image/svg+xml",
        "text/xml",
        "application/xml",
    }
)


def attachment_content_disposition(filename: str, *, fallback: str = "file.bin") -> str:
    """Return an ASCII fallback plus an RFC 5987 UTF-8 filename, always as an attachment."""
    ascii_fallback = unicodedata.normalize("NFKD", filename).encode("ascii", "ignore").decode()
    ascii_fallback = re.sub(r"[^A-Za-z0-9._-]+", "_", ascii_fallback).strip("._-") or fallback
    encoded = quote(filename, safe="")
    return f"attachment; filename=\"{ascii_fallback}\"; filename*=UTF-8''{encoded}"


def secure_download_headers(
    *,
    content_type: str | None,
    filename: str,
    disposition: str | None = None,
    fallback: str = "file.bin",
) -> dict[str, str]:
    """Content-Disposition + X-Content-Type-Options for a stored-content download.

    ``disposition`` is what the caller (or an upstream service) already
    computed; it is kept only when the content type is not one a browser
    will execute inline. Active types are always forced to a freshly built
    attachment disposition, independent of what upstream reports.
    """
    normalized = (content_type or "").split(";", 1)[0].strip().lower()
    if not disposition or normalized in ACTIVE_CONTENT_TYPES:
        disposition = attachment_content_disposition(filename, fallback=fallback)
    return {
        "Content-Disposition": disposition,
        "X-Content-Type-Options": "nosniff",
    }
