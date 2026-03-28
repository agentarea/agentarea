"""Tests for A2UI v0.9 response parser."""

import json

from agentarea_execution.workflows.a2ui_parser import (
    A2UI_DELIMITER,
    parse_a2ui_response,
)


class TestParseA2UIResponse:
    """Test the delimiter-based A2UI response parser."""

    def test_no_delimiter_returns_full_text(self):
        result = parse_a2ui_response("Just a normal text response.")
        assert result.text_content == "Just a normal text response."
        assert result.a2ui_events == []
        assert result.parse_error is None

    def test_empty_string(self):
        result = parse_a2ui_response("")
        assert result.text_content == ""
        assert result.a2ui_events == []

    def test_valid_create_surface(self):
        content = f"Here is your form.\n\n{A2UI_DELIMITER}\n" + json.dumps({
            "events": [{
                "type": "A2UICreateSurface",
                "surface_id": "s1",
                "catalog_id": "https://a2ui.org/specification/v0_9/basic_catalog.json",
            }]
        })
        result = parse_a2ui_response(content)
        assert result.text_content == "Here is your form."
        assert len(result.a2ui_events) == 1
        assert result.a2ui_events[0]["type"] == "A2UICreateSurface"
        assert result.a2ui_events[0]["surface_id"] == "s1"
        assert result.parse_error is None

    def test_valid_multiple_events(self):
        content = f"UI ready.\n{A2UI_DELIMITER}\n" + json.dumps({
            "events": [
                {"type": "A2UICreateSurface", "surface_id": "s1"},
                {
                    "type": "A2UIUpdateComponents",
                    "surface_id": "s1",
                    "components": [
                        {"id": "root", "component": "Column", "children": ["title"]},
                        {"id": "title", "component": "Text", "text": "Hello"},
                    ],
                },
                {
                    "type": "A2UIUpdateDataModel",
                    "surface_id": "s1",
                    "path": "/user/name",
                    "value": "Jane",
                },
            ]
        })
        result = parse_a2ui_response(content)
        assert result.text_content == "UI ready."
        assert len(result.a2ui_events) == 3
        assert result.a2ui_events[0]["type"] == "A2UICreateSurface"
        assert result.a2ui_events[1]["type"] == "A2UIUpdateComponents"
        assert result.a2ui_events[2]["type"] == "A2UIUpdateDataModel"

    def test_invalid_json_returns_error(self):
        content = f"text\n{A2UI_DELIMITER}\n{{not valid json}}"
        result = parse_a2ui_response(content)
        assert result.text_content == "text"
        assert result.a2ui_events == []
        assert result.parse_error is not None
        assert "Invalid JSON" in result.parse_error

    def test_empty_json_after_delimiter(self):
        content = f"text\n{A2UI_DELIMITER}\n"
        result = parse_a2ui_response(content)
        assert result.text_content == "text"
        assert result.a2ui_events == []
        assert "Empty" in result.parse_error

    def test_events_not_a_list(self):
        content = f"text\n{A2UI_DELIMITER}\n" + json.dumps({"events": "not a list"})
        result = parse_a2ui_response(content)
        assert result.text_content == "text"
        assert result.a2ui_events == []
        assert "'events' must be a list" in result.parse_error

    def test_unknown_event_type_skipped(self):
        content = f"text\n{A2UI_DELIMITER}\n" + json.dumps({
            "events": [
                {"type": "A2UICreateSurface", "surface_id": "s1"},
                {"type": "UnknownType", "surface_id": "s1"},
            ]
        })
        result = parse_a2ui_response(content)
        assert len(result.a2ui_events) == 1
        assert result.a2ui_events[0]["type"] == "A2UICreateSurface"

    def test_missing_surface_id_skipped(self):
        content = f"text\n{A2UI_DELIMITER}\n" + json.dumps({
            "events": [
                {"type": "A2UICreateSurface"},  # no surface_id
                {"type": "A2UIDeleteSurface", "surface_id": "s1"},
            ]
        })
        result = parse_a2ui_response(content)
        assert len(result.a2ui_events) == 1
        assert result.a2ui_events[0]["type"] == "A2UIDeleteSurface"

    def test_delimiter_at_start_empty_text(self):
        content = f"{A2UI_DELIMITER}\n" + json.dumps({
            "events": [{"type": "A2UICreateSurface", "surface_id": "s1"}]
        })
        result = parse_a2ui_response(content)
        assert result.text_content == ""
        assert len(result.a2ui_events) == 1

    def test_text_whitespace_trimmed(self):
        content = f"Hello world   \n\n\n{A2UI_DELIMITER}\n" + json.dumps({
            "events": [{"type": "A2UICreateSurface", "surface_id": "s1"}]
        })
        result = parse_a2ui_response(content)
        assert result.text_content == "Hello world"

    def test_payload_not_dict(self):
        content = f"text\n{A2UI_DELIMITER}\n[1, 2, 3]"
        result = parse_a2ui_response(content)
        assert result.a2ui_events == []
        assert "must be a JSON object" in result.parse_error

    def test_non_dict_event_skipped(self):
        content = f"text\n{A2UI_DELIMITER}\n" + json.dumps({
            "events": [
                "not an object",
                {"type": "A2UICreateSurface", "surface_id": "s1"},
            ]
        })
        result = parse_a2ui_response(content)
        assert len(result.a2ui_events) == 1

    def test_event_count_within_limit(self):
        events = [
            {"type": "A2UIUpdateComponents", "surface_id": "s1", "components": []}
            for _ in range(30)
        ]
        content = f"text\n{A2UI_DELIMITER}\n" + json.dumps({"events": events})
        result = parse_a2ui_response(content)
        assert len(result.a2ui_events) == 30

    def test_event_count_exceeds_limit_truncated(self):
        events = [
            {"type": "A2UIUpdateComponents", "surface_id": "s1", "components": []}
            for _ in range(100)
        ]
        content = f"text\n{A2UI_DELIMITER}\n" + json.dumps({"events": events})
        result = parse_a2ui_response(content)
        assert len(result.a2ui_events) == 50
        assert result.parse_error is None

    def test_delete_surface_event(self):
        content = f"Removing UI.\n{A2UI_DELIMITER}\n" + json.dumps({
            "events": [{"type": "A2UIDeleteSurface", "surface_id": "s1"}]
        })
        result = parse_a2ui_response(content)
        assert result.text_content == "Removing UI."
        assert len(result.a2ui_events) == 1
        assert result.a2ui_events[0]["type"] == "A2UIDeleteSurface"
