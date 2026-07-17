"""Secrets must not survive into log output.

Credentials reach log strings by accident, not by intent: a bot token sits in a
URL path, a DSN carries its password, an SDK error quotes the request it failed
on. Rendering exceptions (which the structured formatter now does) widens that
aperture, so redaction belongs in the logging pipeline rather than at each call
site — there is no realistic way to audit every one.
"""

import io
import json
import logging

from agentarea_common.logging import (
    LogSanitizerFilter,
    SecretRedactingFilter,
    WorkspaceContextFormatter,
)

TELEGRAM_TOKEN = "123456789:AAHfaKeToKeNvAlUe_ThatShouldNeverBeLogged"


def _emit(log) -> dict:
    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    handler.setFormatter(WorkspaceContextFormatter())
    handler.addFilter(SecretRedactingFilter())
    handler.addFilter(LogSanitizerFilter())

    logger = logging.getLogger("agentarea.test.redaction")
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    logger.handlers = [handler]
    try:
        log(logger)
    finally:
        logger.handlers = []

    lines = buf.getvalue().strip().splitlines()
    assert len(lines) == 1
    return json.loads(lines[0])


def test_telegram_bot_token_is_redacted_from_a_message():
    entry = _emit(
        lambda log: log.error(
            "Telegram send failed: Client error for url "
            f"'https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage'"
        )
    )

    assert TELEGRAM_TOKEN not in entry["message"]
    assert "api.telegram.org/bot" in entry["message"]


def test_token_is_redacted_inside_a_traceback():
    # The path the traceback fix opened: the secret rides in the exception text.
    def log(logger):
        try:
            raise RuntimeError(
                f"Client error '401' for url 'https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage'"
            )
        except RuntimeError:
            logger.exception("Telegram send failed")

    entry = _emit(log)
    assert TELEGRAM_TOKEN not in entry["exception"]
    assert "RuntimeError" in entry["exception"], "the error itself must survive"


def test_database_password_is_redacted():
    entry = _emit(
        lambda log: log.error("connect failed: postgresql://app_user:sup3rs3cret@db:5432/agentarea")
    )

    assert "sup3rs3cret" not in entry["message"]
    assert "db:5432/agentarea" in entry["message"], "the useful part must survive"


def test_bearer_token_is_redacted():
    entry = _emit(lambda log: log.warning("upstream said: Authorization: Bearer aat_deadbeefcafe"))
    assert "aat_deadbeefcafe" not in entry["message"]


def test_api_key_query_parameter_is_redacted():
    entry = _emit(lambda log: log.info("GET https://api.example.com/v1?api_key=sk-livesecret42"))
    assert "sk-livesecret42" not in entry["message"]


def test_ordinary_messages_are_untouched():
    entry = _emit(lambda log: log.info("task 123 completed in 4ms"))
    assert entry["message"] == "task 123 completed in 4ms"


def test_redaction_keeps_the_record_on_one_line():
    # Redaction must not defeat the log-forging defense.
    entry = _emit(lambda log: log.error("value=%s", "a\nFAKE [CRITICAL] forged"))
    assert "\n" not in entry["message"]
