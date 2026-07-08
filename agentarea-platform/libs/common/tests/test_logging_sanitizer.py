"""Tests for log-injection hardening in agentarea_common.logging."""

import io
import json
import logging

from agentarea_common.logging import (
    LogSanitizerFilter,
    WorkspaceContextFormatter,
)


def _make_record(msg: str, *args: object) -> logging.LogRecord:
    return logging.LogRecord(
        name="agentarea.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg=msg,
        args=args,
        exc_info=None,
    )


class TestLogSanitizerFilter:
    def test_strips_crlf_from_message(self):
        f = LogSanitizerFilter()
        record = _make_record("user said: %s", "hi\r\nFAKE [CRITICAL] injected")
        assert f.filter(record) is True
        rendered = record.getMessage()
        assert "\n" not in rendered
        assert "\r" not in rendered
        assert rendered == "user said: hi  FAKE [CRITICAL] injected"

    def test_strips_other_control_chars_but_keeps_tab(self):
        f = LogSanitizerFilter()
        record = _make_record("x=%s", "a\x00b\x1fc\td")
        f.filter(record)
        rendered = record.getMessage()
        assert rendered == "x=a b c\td"

    def test_clean_message_is_untouched(self):
        f = LogSanitizerFilter()
        record = _make_record("plain %s message", "clean")
        f.filter(record)
        # args are preserved (not collapsed) when nothing needed sanitizing
        assert record.args == ("clean",)
        assert record.getMessage() == "plain clean message"


class TestStructuredLoggingNeutralizesForging:
    """Verify the structured JSON path keeps a forged newline on one line.

    Built with a local logger + handler (no global setup_logging) so the test
    never mutates process-wide logging state that other tests rely on.
    """

    def test_injected_newline_stays_on_one_json_line(self):
        buf = io.StringIO()
        handler = logging.StreamHandler(buf)
        handler.setFormatter(WorkspaceContextFormatter())
        handler.addFilter(LogSanitizerFilter())

        logger = logging.getLogger("agentarea.test.forging_isolated")
        logger.setLevel(logging.INFO)
        logger.propagate = False
        logger.addHandler(handler)
        try:
            logger.warning("provider=%s", "evil\nFAKE [CRITICAL] forged")
        finally:
            logger.removeHandler(handler)

        physical_lines = buf.getvalue().strip().splitlines()
        assert len(physical_lines) == 1
        record = json.loads(physical_lines[0])
        assert "\n" not in record["message"]
        assert record["message"] == "provider=evil FAKE [CRITICAL] forged"
