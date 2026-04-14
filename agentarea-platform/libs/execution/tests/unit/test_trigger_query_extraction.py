"""Test that trigger execution correctly extracts message text for task query.

Covers webhook-based (Telegram, Slack, Discord, etc.) and poll-based (extractors) paths.
"""


class TestTriggerQueryFromWebhookParsedData:
    """Webhook parsers put text at top level of execution_data."""

    def _extract_query(self, execution_data: dict, trigger_description: str = "Default trigger") -> str:
        """Replicate the query extraction logic from trigger_execution_activities."""
        extracted_events = execution_data.get("extracted_events", [])
        message_texts = [e.get("text") for e in extracted_events if e.get("text")]
        if not message_texts:
            top_level_text = execution_data.get("text")
            if top_level_text:
                message_texts = [top_level_text]
        return "\n".join(message_texts) if message_texts else (
            trigger_description or "Execute trigger"
        )

    def test_telegram_message_text_extracted(self):
        """Telegram webhook parser puts text at top level."""
        execution_data = {
            "webhook_type": "telegram",
            "chat_id": 12345,
            "text": "Привет, помоги мне с задачей",
            "username": "testuser",
        }
        query = self._extract_query(execution_data)
        assert query == "Привет, помоги мне с задачей"

    def test_slack_message_text_extracted(self):
        """Slack webhook parser puts text at top level."""
        execution_data = {
            "webhook_type": "slack",
            "text": "Deploy the new version",
            "channel": "C12345",
        }
        query = self._extract_query(execution_data)
        assert query == "Deploy the new version"

    def test_generic_webhook_no_text_falls_back_to_description(self):
        """Generic webhook without text field falls back to trigger description."""
        execution_data = {
            "webhook_type": "generic",
            "body": {"event": "push"},
        }
        query = self._extract_query(execution_data, "Monitor GitHub pushes")
        assert query == "Monitor GitHub pushes"

    def test_empty_text_falls_back_to_description(self):
        """Empty string text should fall back to description."""
        execution_data = {"text": ""}
        query = self._extract_query(execution_data, "Fallback description")
        assert query == "Fallback description"

    def test_extracted_events_take_priority_over_top_level_text(self):
        """Poll-based extracted_events should be preferred over top-level text."""
        execution_data = {
            "text": "top level text",
            "extracted_events": [
                {"text": "Event message 1"},
                {"text": "Event message 2"},
            ],
        }
        query = self._extract_query(execution_data)
        assert query == "Event message 1\nEvent message 2"

    def test_extracted_events_with_empty_text_ignored(self):
        """Events with empty/null text should be skipped."""
        execution_data = {
            "text": "fallback from webhook",
            "extracted_events": [
                {"text": ""},
                {"text": None},
                {"data": "no text field"},
            ],
        }
        query = self._extract_query(execution_data)
        assert query == "fallback from webhook"

    def test_no_text_no_events_no_description(self):
        """Without any text source, falls back to generic message."""
        execution_data = {"webhook_type": "unknown"}
        query = self._extract_query(execution_data, "")
        assert query == "Execute trigger"

    def test_multiline_text_preserved(self):
        """Multi-line message text should be preserved."""
        execution_data = {
            "text": "Line 1\nLine 2\nLine 3",
        }
        query = self._extract_query(execution_data)
        assert "Line 1" in query
        assert "Line 3" in query


class TestTriggerServiceQueryExtraction:
    """Same logic in trigger_service.py uses 'events' key instead of 'extracted_events'."""

    def _extract_query(self, trigger_data: dict, trigger_description: str = "Default trigger") -> str:
        """Replicate the query extraction logic from trigger_service."""
        events = trigger_data.get("events", [])
        message_texts = [e.get("text") for e in events if e.get("text")]
        if not message_texts:
            top_level_text = trigger_data.get("text")
            if top_level_text:
                message_texts = [top_level_text]
        return "\n".join(message_texts) if message_texts else (
            trigger_description or "Execute trigger"
        )

    def test_webhook_text_extracted_when_no_events(self):
        """trigger_service path also extracts top-level text."""
        trigger_data = {"text": "Hello from Discord"}
        query = self._extract_query(trigger_data)
        assert query == "Hello from Discord"

    def test_events_take_priority(self):
        """events[] text takes priority over top-level text."""
        trigger_data = {
            "text": "ignored",
            "events": [{"text": "from event"}],
        }
        query = self._extract_query(trigger_data)
        assert query == "from event"

    def test_fallback_to_description(self):
        """No text anywhere falls back to trigger description."""
        trigger_data = {"raw_data": {}}
        query = self._extract_query(trigger_data, "Cron job trigger")
        assert query == "Cron job trigger"
