"""Tests for log-injection hardening in agentarea_common.logging."""

import io
import json
import logging

from agentarea_common.logging import (
    LogSanitizerFilter,
    SecretRedactingFilter,
    WorkspaceContextFormatter,
    install_log_filters,
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


class TestInstallLogFiltersCoversForeignHandlers:
    """uvicorn and gunicorn give their loggers their own handlers with propagate=False,
    so those records never reach our console handler and never hit the filters declared
    on it. install_log_filters() has to retrofit both protections onto them.
    """

    def _foreign_logger(self, name: str) -> tuple[logging.Logger, logging.Handler, io.StringIO]:
        buf = io.StringIO()
        handler = logging.StreamHandler(buf)
        handler.setFormatter(WorkspaceContextFormatter())
        logger = logging.getLogger(name)
        logger.setLevel(logging.INFO)
        logger.propagate = False
        logger.addHandler(handler)
        return logger, handler, buf

    def test_retrofits_both_filters_onto_a_foreign_handler(self):
        logger, handler, buf = self._foreign_logger("uvicorn.access.test_retrofit")
        try:
            install_log_filters()

            assert any(isinstance(f, LogSanitizerFilter) for f in handler.filters)
            assert any(isinstance(f, SecretRedactingFilter) for f in handler.filters)

            logger.warning("path=%s", "/x\nFAKE [CRITICAL] forged")
            physical_lines = buf.getvalue().strip().splitlines()
            assert len(physical_lines) == 1
            assert json.loads(physical_lines[0])["message"] == "path=/x FAKE [CRITICAL] forged"
        finally:
            logger.removeHandler(handler)

    def test_is_idempotent(self):
        logger, handler, _ = self._foreign_logger("uvicorn.access.test_idempotent")
        try:
            install_log_filters()
            install_log_filters()

            assert sum(isinstance(f, LogSanitizerFilter) for f in handler.filters) == 1
            assert sum(isinstance(f, SecretRedactingFilter) for f in handler.filters) == 1
        finally:
            logger.removeHandler(handler)

    def test_redaction_runs_before_sanitization_even_if_sanitizer_was_already_there(self):
        """Order is documented as redact-then-sanitize; it has to hold, not just be stated."""
        logger, handler, _ = self._foreign_logger("uvicorn.access.test_order")
        handler.addFilter(LogSanitizerFilter())
        try:
            install_log_filters()

            ours = [
                type(f)
                for f in handler.filters
                if isinstance(f, SecretRedactingFilter | LogSanitizerFilter)
            ]
            assert ours == [SecretRedactingFilter, LogSanitizerFilter]
        finally:
            logger.removeHandler(handler)

    def test_unrelated_filters_are_preserved(self):
        logger, handler, _ = self._foreign_logger("uvicorn.access.test_preserve")
        marker = logging.Filter(name="unrelated")
        handler.addFilter(marker)
        try:
            install_log_filters()

            assert marker in handler.filters
        finally:
            logger.removeHandler(handler)
