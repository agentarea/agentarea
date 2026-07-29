"""A logged exception must carry its traceback.

logger.exception() and exc_info=True are the only record an operator gets of an
unexpected failure. Rendering just the message turns every such call into
"something broke" with no cause, which is worse than useless: it reads like the
error was reported when the reason was thrown away.
"""

import io
import json
import logging

from agentarea_common.logging import (
    LogSanitizerFilter,
    WorkspaceContextFormatter,
)


def _emit(log: object) -> dict:
    """Run a logging call through the structured formatter; return the JSON."""
    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    handler.setFormatter(WorkspaceContextFormatter())
    handler.addFilter(LogSanitizerFilter())

    logger = logging.getLogger("agentarea.test.exceptions")
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    logger.handlers = [handler]
    try:
        log(logger)  # type: ignore[operator]
    finally:
        logger.handlers = []

    lines = buf.getvalue().strip().splitlines()
    assert len(lines) == 1, f"expected one JSON line, got {len(lines)}"
    return json.loads(lines[0])


def test_logger_exception_records_the_traceback():
    def log(logger):
        try:
            raise ValueError("the actual cause")
        except ValueError:
            logger.exception("OutboxRelay batch failed")

    entry = _emit(log)

    assert entry["message"] == "OutboxRelay batch failed"
    assert "ValueError: the actual cause" in entry["exception"]
    assert "Traceback (most recent call last)" in entry["exception"]


def test_exc_info_true_records_the_traceback():
    def log(logger):
        try:
            raise KeyError("missing")
        except KeyError:
            logger.error("failed to publish", exc_info=True)

    assert "KeyError: 'missing'" in _emit(log)["exception"]


def test_the_raising_line_is_identified():
    def log(logger):
        try:
            raise RuntimeError("boom")
        except RuntimeError:
            logger.exception("failed")

    entry = _emit(log)
    assert "test_logging_exceptions.py" in entry["exception"]


def test_chained_causes_survive():
    def log(logger):
        try:
            try:
                raise ValueError("root cause")
            except ValueError as exc:
                raise RuntimeError("wrapper") from exc
        except RuntimeError:
            logger.exception("failed")

    exception = _emit(log)["exception"]
    assert "root cause" in exception
    assert "wrapper" in exception


def test_records_without_an_exception_have_no_exception_field():
    entry = _emit(lambda logger: logger.info("nothing wrong here"))
    assert "exception" not in entry


def test_stack_info_is_recorded_separately():
    entry = _emit(lambda logger: logger.warning("with stack", stack_info=True))

    assert "stack" in entry
    assert "Stack (most recent call last)" in entry["stack"]
    assert "exception" not in entry


def test_traceback_cannot_forge_a_second_log_line():
    # A traceback is inherently multi-line; JSON encoding must keep the record
    # on one physical line so it cannot be read as two log entries.
    def log(logger):
        try:
            raise ValueError("multi\nline\nvalue")
        except ValueError:
            logger.exception("failed")

    entry = _emit(log)  # asserts a single physical line
    assert "\n" in entry["exception"], "traceback should retain its own newlines inside the field"
