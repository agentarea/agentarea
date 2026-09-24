"""fetch_source digest verification.

Pure-function tests against the real "file" source path (local filesystem,
no network, no DB) — the same function the "url" and "configMap" paths run
through.
"""

from __future__ import annotations

import hashlib

import pytest
from registry_sync import fetch_source

CATALOG_BODY = '{"providers": [{"provider_key": "openai", "name": "OpenAI"}]}'
CATALOG_SHA256 = hashlib.sha256(CATALOG_BODY.encode("utf-8")).hexdigest()


def test_fetch_source_without_a_digest_is_unverified(tmp_path):
    path = tmp_path / "catalog.json"
    path.write_text(CATALOG_BODY)

    data = fetch_source("file", str(path))

    assert data["providers"][0]["provider_key"] == "openai"


def test_fetch_source_accepts_a_matching_digest(tmp_path):
    path = tmp_path / "catalog.json"
    path.write_text(CATALOG_BODY)

    data = fetch_source("file", str(path), expected_sha256=CATALOG_SHA256)

    assert data["providers"][0]["provider_key"] == "openai"


def test_fetch_source_rejects_a_mismatched_digest(tmp_path):
    path = tmp_path / "catalog.json"
    path.write_text(CATALOG_BODY)

    with pytest.raises(ValueError, match="digest mismatch"):
        fetch_source("file", str(path), expected_sha256="0" * 64)


def test_fetch_source_digest_check_is_case_insensitive(tmp_path):
    path = tmp_path / "catalog.json"
    path.write_text(CATALOG_BODY)

    data = fetch_source("file", str(path), expected_sha256=CATALOG_SHA256.upper())

    assert data["providers"][0]["provider_key"] == "openai"


def test_fetch_source_rejects_a_mismatched_digest_for_configmap_sources():
    with pytest.raises(ValueError, match="digest mismatch"):
        fetch_source(
            "configMap",
            location="",
            configmap_body=CATALOG_BODY,
            expected_sha256="0" * 64,
        )
