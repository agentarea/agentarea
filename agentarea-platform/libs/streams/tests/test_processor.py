"""A processor's code: what is refused at create, and how one run over an event is read.

The harness is run here with the local ``bash`` and ``python3``, the way the
sandbox runs it, so what an agent's code does is what these tests see.
"""

import subprocess
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from agentarea_streams.domain.errors import ProcessorCodeError, ProcessorFailedError
from agentarea_streams.domain.keys import processor_output_id
from agentarea_streams.domain.models import StreamEvent
from agentarea_streams.domain.processor import (
    MAX_CODE_BYTES,
    MAX_OUTPUTS,
    MAX_RESULT_BYTES,
    TIMED_OUT_EXIT,
    CodeRun,
    check_code,
    event_payload,
    harness_command,
    outputs_of,
    resolve_streams,
)

ORDERS = """
def process(event):
    if event["kind"].startswith("order.") and event["data"]["amount"] > 100:
        return [{"stream": "big-orders", "kind": event["kind"], "data": event["data"]}]
    return None
"""


def _event(kind="order.paid", data=None) -> StreamEvent:
    return StreamEvent(
        id=uuid4(),
        type=kind,
        source="webhook",
        data=data if data is not None else {"amount": 250},
        stream_id=uuid4(),
        workspace_id="ws",
        created_by="u",
        event_key="k1",
        received_at=datetime.now(UTC),
        correlation_id="corr-1",
    )


def _run(code: str, event: StreamEvent, max_bytes: int = MAX_RESULT_BYTES) -> CodeRun:
    done = subprocess.run(
        ["bash", "-c", harness_command(code, event_payload(event))],
        capture_output=True,
        timeout=30,
        check=False,
    )
    stdout = done.stdout[:max_bytes].decode()
    return CodeRun(
        exit_code=done.returncode,
        stdout=stdout,
        stdout_truncated=len(done.stdout) > max_bytes,
        stderr=done.stderr.decode(),
    )


def test_code_that_defines_process_is_accepted():
    check_code(ORDERS)


@pytest.mark.parametrize(
    ("code", "message"),
    [
        ("", "empty"),
        ("def process(event):\n  return [", "does not parse"),
        ("def handle(event):\n    return None\n", "top-level def process"),
        ("async def process(event):\n    return None\n", "top-level def process"),
        ("def process():\n    return None\n", "top-level def process"),
        ("x = 1\n" * (MAX_CODE_BYTES // 6 + 1) + ORDERS, "bytes"),
    ],
)
def test_code_a_processor_cannot_run_is_refused(code, message):
    with pytest.raises(ProcessorCodeError, match=message):
        check_code(code)


@pytest.mark.parametrize(
    "line",
    [
        'API_KEY = "sk-abcdefghijklmnop0123"',  # pragma: allowlist secret
        'password = "hunter22-hunter22"',  # pragma: allowlist secret
        'HEADERS = {"Authorization": "Bearer abcdefgh12345678"}',
        'def call(token="ghp_abcdefghijklmnopqrstuvwx"): pass',  # pragma: allowlist secret
    ],
)
def test_code_holding_a_secret_is_refused(line):
    with pytest.raises(ProcessorCodeError, match="secret"):
        check_code(f"{line}\n{ORDERS}")


def test_code_that_reads_a_secret_shaped_field_of_the_event_is_accepted():
    check_code(
        "def process(event):\n"
        '    token = event["data"].get("token")\n'
        '    return [{"stream": "out", "kind": "t", "data": {"token": token}, "key": "order-1"}]\n'
    )


def test_a_run_returns_the_events_process_wrote():
    event = _event()
    outputs = outputs_of(_run(ORDERS, event))
    assert [(o.stream, o.kind, o.data, o.key) for o in outputs] == [
        ("big-orders", "order.paid", {"amount": 250}, None)
    ]


def test_process_sees_the_event_envelope():
    event = _event()
    code = (
        "def process(event):\n"
        "    keys = sorted(event)\n"
        '    return [{"stream": "out", "kind": "seen", "data": {"keys": keys, '
        '"id": event["id"], "correlation_id": event["correlation_id"]}}]\n'
    )
    (output,) = outputs_of(_run(code, event))
    assert output.data["id"] == str(event.id)
    assert output.data["correlation_id"] == "corr-1"
    assert {"id", "kind", "data", "stream_id", "key", "source_type", "depth"} <= set(
        output.data["keys"]
    )


def test_none_and_an_empty_list_write_nothing():
    assert outputs_of(_run(ORDERS, _event(data={"amount": 5}))) == []
    assert outputs_of(_run("def process(event):\n    return []\n", _event())) == []


def test_what_process_prints_does_not_spoil_the_result():
    code = 'def process(event):\n    print("hello")\n    return [{"stream": "o", "kind": "k", "data": {}}]\n'
    assert [o.kind for o in outputs_of(_run(code, _event()))] == ["k"]


def test_an_exception_is_a_failure_naming_the_error_and_the_line():
    code = "def process(event):\n    x = 1\n    raise ValueError('bad order')\n"
    with pytest.raises(
        ProcessorFailedError, match=r"ValueError: bad order \(processor.py line 3\)"
    ):
        outputs_of(_run(code, _event()))


def test_sys_exit_is_a_failure():
    code = "import sys\ndef process(event):\n    sys.exit(3)\n"
    with pytest.raises(ProcessorFailedError, match="SystemExit"):
        outputs_of(_run(code, _event()))


@pytest.mark.parametrize(
    ("returned", "message"),
    [
        ('{"stream": "o", "kind": "k", "data": {}}', "list of events or None"),
        ('[{"stream": "o", "data": {}}]', "event 0"),
        ('[{"stream": "o", "kind": "k", "data": []}]', "event 0"),
        ('[{"stream": "o", "kind": "k", "data": {}, "colour": 1}]', "event 0"),
        ('[{"stream": "o", "kind": "k", "data": {1, 2}}]', "TypeError"),
    ],
)
def test_a_result_that_is_not_a_list_of_events_is_a_failure(returned, message):
    code = f"def process(event):\n    return {returned}\n"
    with pytest.raises(ProcessorFailedError, match=message):
        outputs_of(_run(code, _event()))


def test_too_many_events_is_a_failure():
    code = (
        "def process(event):\n"
        f'    return [{{"stream": "o", "kind": "k", "data": {{}}}}] * {MAX_OUTPUTS + 1}\n'
    )
    with pytest.raises(ProcessorFailedError, match=f"more than {MAX_OUTPUTS}"):
        outputs_of(_run(code, _event()))


def test_a_result_past_the_size_cap_is_a_failure():
    code = 'def process(event):\n    return [{"stream": "o", "kind": "k", "data": {"x": "y" * 4000}}]\n'
    with pytest.raises(ProcessorFailedError, match="more than"):
        outputs_of(_run(code, _event(), max_bytes=1000))


def test_a_timed_out_run_is_a_failure():
    with pytest.raises(ProcessorFailedError, match="did not finish"):
        outputs_of(CodeRun(exit_code=TIMED_OUT_EXIT, stdout="", stdout_truncated=False))


def test_a_run_that_died_names_its_exit_code_and_the_end_of_stderr():
    with pytest.raises(ProcessorFailedError, match="code 137.*Killed"):
        outputs_of(CodeRun(exit_code=137, stdout="", stdout_truncated=False, stderr="x\nKilled"))
    with pytest.raises(ProcessorFailedError, match="no result"):
        outputs_of(CodeRun(exit_code=0, stdout="hello", stdout_truncated=False))


def test_outputs_name_a_declared_stream_by_id_or_name():
    big, audit, source = uuid4(), uuid4(), uuid4()
    code = (
        "def process(event):\n"
        f'    return [{{"stream": "big-orders", "kind": "a", "data": {{}}}}, '
        f'{{"stream": "{audit}", "kind": "b", "data": {{}}}}]\n'
    )
    routed = resolve_streams(
        outputs_of(_run(code, _event())), {big: "big-orders", audit: "audit"}, source
    )
    assert [(stream, o.kind) for stream, o in routed] == [(big, "a"), (audit, "b")]


def test_an_output_to_an_undeclared_stream_or_the_input_is_a_failure():
    big, source = uuid4(), uuid4()
    other = outputs_of(
        _run(
            'def process(event):\n    return [{"stream": "elsewhere", "kind": "a", "data": {}}]\n',
            _event(),
        )
    )
    with pytest.raises(ProcessorFailedError, match="not one of this processor's outputs"):
        resolve_streams(other, {big: "big-orders"}, source)
    own = outputs_of(
        _run(
            f'def process(event):\n    return [{{"stream": "{source}", "kind": "a", "data": {{}}}}]\n',
            _event(),
        )
    )
    with pytest.raises(ProcessorFailedError, match="own input"):
        resolve_streams(own, {big: "big-orders", source: "in"}, source)


def test_an_event_too_large_for_one_sandbox_call_is_a_failure():
    with pytest.raises(ProcessorFailedError, match="too large"):
        harness_command(ORDERS, event_payload(_event(data={"blob": "x" * 300_000})))


def test_each_output_is_named_by_its_processor_source_event_and_position():
    processor, source = uuid4(), uuid4()
    assert processor_output_id(processor, source, 0) == processor_output_id(processor, source, 0)
    assert processor_output_id(processor, source, 0) != processor_output_id(processor, source, 1)
    assert processor_output_id(processor, source, 0) != processor_output_id(uuid4(), source, 0)
