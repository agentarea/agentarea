"""Content-Disposition/nosniff headers for content served back to a browser.

A response whose Content-Type a browser will execute inline (HTML, XML, SVG)
must never render on the API's own origin, regardless of the filename or
what an upstream service already set — see issue #483.
"""

from __future__ import annotations

import pytest
from agentarea_common.artifacts.content_security import (
    ACTIVE_CONTENT_TYPES,
    attachment_content_disposition,
    secure_download_headers,
)


def test_attachment_content_disposition_is_always_an_attachment() -> None:
    value = attachment_content_disposition("notes.txt")

    assert value.startswith("attachment;")
    assert 'filename="notes.txt"' in value
    assert "filename*=UTF-8''notes.txt" in value


def test_attachment_content_disposition_encodes_non_ascii_names() -> None:
    value = attachment_content_disposition("bericht_ü.txt")

    assert 'filename="bericht_u.txt"' in value
    assert "filename*=UTF-8''bericht_%C3%BC.txt" in value


def test_attachment_content_disposition_falls_back_when_name_has_no_ascii() -> None:
    value = attachment_content_disposition("日本語", fallback="download.bin")

    assert 'filename="download.bin"' in value


@pytest.mark.parametrize(
    "content_type",
    sorted(ACTIVE_CONTENT_TYPES),
)
def test_secure_download_headers_forces_attachment_for_active_types(content_type) -> None:
    headers = secure_download_headers(
        content_type=content_type,
        filename="report.txt",
        disposition="inline",
    )

    assert headers["Content-Disposition"].startswith("attachment;")
    assert headers["X-Content-Type-Options"] == "nosniff"


def test_secure_download_headers_ignores_content_type_parameters() -> None:
    headers = secure_download_headers(
        content_type="text/html; charset=utf-8",
        filename="page.txt",
        disposition="inline",
    )

    assert headers["Content-Disposition"].startswith("attachment;")


def test_secure_download_headers_keeps_upstream_disposition_for_inert_types() -> None:
    headers = secure_download_headers(
        content_type="text/plain",
        filename="notes.txt",
        disposition='attachment; filename="already-set.txt"',
    )

    assert headers["Content-Disposition"] == 'attachment; filename="already-set.txt"'
    assert headers["X-Content-Type-Options"] == "nosniff"


def test_secure_download_headers_computes_disposition_when_missing() -> None:
    headers = secure_download_headers(content_type="text/plain", filename="notes.txt")

    assert headers["Content-Disposition"].startswith("attachment;")
    assert headers["X-Content-Type-Options"] == "nosniff"


def test_secure_download_headers_always_sets_nosniff() -> None:
    headers = secure_download_headers(content_type=None, filename="notes.txt")

    assert headers["X-Content-Type-Options"] == "nosniff"
