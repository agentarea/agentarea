"""Tests for data extractors."""

from unittest.mock import AsyncMock, patch

import pytest
from agentarea_triggers.extractors import (
    ExtractionResult,
    get_extractor,
    list_extractors,
    register_extractor,
)
from agentarea_triggers.extractors.mailslurper import MailSlurperExtractor


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
        register_extractor("test_ext", MailSlurperExtractor)
        assert get_extractor("test_ext") is MailSlurperExtractor

    def test_get_nonexistent(self):
        assert get_extractor("nonexistent") is None

    def test_list_extractors(self):
        register_extractor("listed_ext", MailSlurperExtractor)
        names = list_extractors()
        assert "listed_ext" in names

    def test_mailslurper_auto_registered(self):
        """MailSlurper registers itself on import."""
        assert get_extractor("mailslurper") is MailSlurperExtractor


class TestMailSlurperExtractor:
    """Test MailSlurper data extractor."""

    @pytest.fixture
    def extractor(self):
        return MailSlurperExtractor()

    @pytest.fixture
    def config(self):
        return {"api_url": "http://localhost:8085"}

    @pytest.mark.asyncio
    async def test_extract_no_emails(self, extractor, config):
        """Returns no data when mailbox is empty."""
        with patch("agentarea_triggers.extractors.mailslurper.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_resp = AsyncMock()
            mock_resp.json = lambda: {"mailItems": []}
            mock_resp.raise_for_status = lambda: None
            mock_client.get.return_value = mock_resp
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await extractor.extract(config, None)

            assert result.has_new_data is False
            assert result.events == []

    @pytest.mark.asyncio
    async def test_extract_new_emails(self, extractor, config):
        """Returns new emails as normalized events."""
        mail_items = [
            {
                "id": "msg-001",
                "subject": "Hello Agent",
                "fromAddress": "user@test.com",
                "toAddresses": ["agent@agentarea.local"],
                "body": "Please do the thing",
                "dateSent": "2026-03-11T10:00:00Z",
            },
            {
                "id": "msg-002",
                "subject": "Follow up",
                "fromAddress": "user@test.com",
                "toAddresses": ["agent@agentarea.local"],
                "body": "Any update?",
                "dateSent": "2026-03-11T11:00:00Z",
            },
        ]

        with patch("agentarea_triggers.extractors.mailslurper.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_resp = AsyncMock()
            mock_resp.json = lambda: {"mailItems": mail_items}
            mock_resp.raise_for_status = lambda: None
            mock_client.get.return_value = mock_resp
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await extractor.extract(config, None)

            assert result.has_new_data is True
            assert len(result.events) == 2
            assert result.events[0]["subject"] == "Hello Agent"
            assert result.events[0]["from"] == "user@test.com"
            assert result.events[0]["type"] == "email"
            assert result.channel_origin["type"] == "email"
            assert result.channel_origin["reply_to"] == "user@test.com"
            assert result.channel_origin["presentation"] == "summary"
            assert result.updated_state["last_seen_id"] == "msg-002"

    @pytest.mark.asyncio
    async def test_extract_with_state_filters_seen(self, extractor, config):
        """Only returns emails newer than last_seen_id."""
        mail_items = [
            {"id": "msg-001", "subject": "Old", "fromAddress": "a@b.com", "toAddresses": [], "body": "", "dateSent": ""},
            {"id": "msg-003", "subject": "New", "fromAddress": "a@b.com", "toAddresses": [], "body": "", "dateSent": ""},
        ]

        with patch("agentarea_triggers.extractors.mailslurper.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_resp = AsyncMock()
            mock_resp.json = lambda: {"mailItems": mail_items}
            mock_resp.raise_for_status = lambda: None
            mock_client.get.return_value = mock_resp
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await extractor.extract(config, {"last_seen_id": "msg-001"})

            assert result.has_new_data is True
            assert len(result.events) == 1
            assert result.events[0]["subject"] == "New"

    @pytest.mark.asyncio
    async def test_extract_http_error(self, extractor, config):
        """Returns no data on HTTP error."""
        import httpx

        with patch("agentarea_triggers.extractors.mailslurper.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.get.side_effect = httpx.ConnectError("Connection refused")
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await extractor.extract(config, None)

            assert result.has_new_data is False
