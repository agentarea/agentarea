"""Tests for the data-extractor framework.

The framework is the generic plug-point that poll-based triggers use (a Temporal
activity resolves an extractor by name and calls ``extract``). It ships with no
concrete extractor by default — a real one (e.g. IMAP, or an inbound webhook)
would register itself the same way the fake below does.
"""

from typing import Any

import pytest
from agentarea_triggers.extractors import (
    ExtractionResult,
    get_extractor,
    list_extractors,
    register_extractor,
)


class _FakeExtractor:
    """Minimal extractor satisfying the DataExtractor protocol, for registry tests."""

    async def extract(
        self, config: dict[str, Any], state: dict[str, Any] | None
    ) -> ExtractionResult:
        return ExtractionResult(has_new_data=False, updated_state=state or {})


class TestExtractionResult:
    """Test ExtractionResult dataclass."""

    def test_defaults(self):
        result = ExtractionResult(has_new_data=False)
        assert result.has_new_data is False
        assert result.events == []
        assert result.updated_state == {}
        assert result.channel_origin == {}

    def test_with_data(self):
        result = ExtractionResult(
            has_new_data=True,
            events=[{"type": "email", "subject": "Test"}],
            updated_state={"last_seen_id": "abc"},
            channel_origin={"type": "email", "reply_to": "user@test.com"},
        )
        assert result.has_new_data is True
        assert len(result.events) == 1
        assert result.updated_state["last_seen_id"] == "abc"


class TestExtractorRegistry:
    """Test extractor registry."""

    def test_register_and_get(self):
        register_extractor("test_ext", _FakeExtractor)
        assert get_extractor("test_ext") is _FakeExtractor

    def test_get_nonexistent(self):
        assert get_extractor("nonexistent") is None

    def test_list_extractors(self):
        register_extractor("listed_ext", _FakeExtractor)
        names = list_extractors()
        assert "listed_ext" in names


class TestFakeExtractor:
    """Test the protocol contract via the fake extractor."""

    @pytest.mark.asyncio
    async def test_extract_returns_result(self):
        result = await _FakeExtractor().extract({}, None)
        assert isinstance(result, ExtractionResult)
        assert result.has_new_data is False
        assert result.updated_state == {}

    @pytest.mark.asyncio
    async def test_extract_preserves_state(self):
        result = await _FakeExtractor().extract({}, {"last_seen_id": "abc"})
        assert result.updated_state == {"last_seen_id": "abc"}
