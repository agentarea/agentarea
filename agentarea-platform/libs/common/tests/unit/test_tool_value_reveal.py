"""What a task's authority sees of a tool call: everything, with the secret-shaped parts masked."""

import pytest
from agentarea_common.events.redaction import mask_inline_secrets, reveal_tool_value

BEARER = "sk-live-4f9a2c77QpZ"


@pytest.mark.parametrize(
    ("text", "secret", "kept"),
    [
        (
            f"curl -H 'Authorization: Bearer {BEARER}' https://api.example.com/v1/items",
            BEARER,
            "curl -H 'Authorization: Bearer [redacted]' https://api.example.com/v1/items",
        ),
        (
            "curl -H 'Authorization: Basic dXNlcjpodW50ZXIy' https://x.example",
            "dXNlcjpodW50ZXIy",
            "Authorization: Basic [redacted]",
        ),
        ("deploy --password=hunter2 --region eu", "hunter2", "--region eu"),
        ("deploy --api-key hunter2 --region eu", "hunter2", "--region eu"),
        ("mysql -u root -phunter2 db", "hunter2", "mysql -u root -p[redacted] db"),
        ("sshpass -p hunter2 ssh host", "hunter2", "ssh host"),
        ("PGPASSWORD=hunter2 psql -h db", "hunter2", "psql -h db"),
        ('{"password": "hunter2", "user": "ann"}', "hunter2", '"user": "ann"'),  # pragma: allowlist secret
        ("git clone https://ann:hunter2@git.example/repo", "hunter2", "git.example/repo"),  # pragma: allowlist secret
        ("curl -u ann:hunter2 https://x.example", "hunter2", "-u ann:"),
    ],
)
def test_a_secret_inside_a_text_is_masked_in_place(text, secret, kept):
    masked = mask_inline_secrets(text)
    assert secret not in masked
    assert kept in masked


def test_a_text_without_secrets_is_unchanged():
    text = "ls -la /srv && mkdir -p build && find . -print"
    assert mask_inline_secrets(text) == text


def test_the_whole_command_and_result_are_kept_with_secrets_masked():
    revealed = reveal_tool_value(
        {
            "command": f"curl -H 'Authorization: Bearer {BEARER}' https://api.example.com",
            "password": "hunter2",  # pragma: allowlist secret
            "timeout": 30,
            "nested": [{"api_key": "k-1", "path": "/srv"}],  # pragma: allowlist secret
        }
    )
    assert revealed == {
        "command": "curl -H 'Authorization: Bearer [redacted]' https://api.example.com",
        "password": "[redacted]",
        "timeout": 30,
        "nested": [{"api_key": "[redacted]", "path": "/srv"}],
    }
    long_output = "line\n" * 5000
    assert reveal_tool_value(long_output, field_name="result") == long_output
