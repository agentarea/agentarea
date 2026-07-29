from agentarea_execution.workflows.helpers import sanitize_tool_event_value


def test_file_content_and_secrets_are_omitted_from_event_arguments():
    document_body = "confidential document body"
    sanitized = sanitize_tool_event_value(
        {
            "path": "reports/output.txt",
            "content": document_body,
            "api_token": "token-value",
        }
    )

    assert sanitized["path"] == "reports/output.txt"
    assert document_body not in str(sanitized)
    assert "token-value" not in str(sanitized)


def test_shell_heredoc_body_is_not_persisted_in_event_arguments():
    heredoc = "python - <<'PY'\nprint('private payload')\nPY"

    sanitized = sanitize_tool_event_value({"command": heredoc, "timeout": 30})

    assert "private payload" not in sanitized["command"]
    assert sanitized["timeout"] == 30


def test_short_single_line_shell_command_is_not_persisted_in_event_arguments():
    canary = "printf private-file-body > report.txt"

    sanitized = sanitize_tool_event_value({"command": canary, "timeout": 30})

    assert "private-file-body" not in sanitized["command"]
    assert "omitted from event log" in sanitized["command"]


def test_binary_like_and_large_results_are_bounded():
    base64_body = "A" * 4096

    sanitized = sanitize_tool_event_value(base64_body, field_name="result")

    assert base64_body not in sanitized
    assert "omitted from event log" in sanitized


def test_short_tool_result_is_never_persisted_in_event_payload():
    canary = "PRIVATE_STDOUT_CANARY"

    sanitized = sanitize_tool_event_value(canary, field_name="result")

    assert canary not in sanitized
    assert "omitted from event log" in sanitized


def test_short_non_sensitive_values_remain_useful_for_the_timeline():
    sanitized = sanitize_tool_event_value(
        {"path": "report.xlsx", "exit_code": 0, "query": "quarterly totals"}
    )

    assert sanitized == {
        "path": "report.xlsx",
        "exit_code": 0,
        "query": "quarterly totals",
    }
