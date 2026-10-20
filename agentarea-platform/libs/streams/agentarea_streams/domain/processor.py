"""A processor: Python an agent wrote, run in the sandbox over each event of its input stream.

The code defines ``process(event: dict) -> list[dict] | None``. Each dict it
returns is an event to write, ``{stream, kind, data, key?}``, where ``stream``
names one of the processor's declared output streams by id or name. The code
gets no secrets and its source is shown to every reader of the stream, so a
secret written into it is refused.

One run is one bash command: a harness with the code and the event inlined,
which keeps what the code prints off the result and reports an exception as
data. What the platform decides is only whether the run is usable: a failure
of the code is ``ProcessorFailedError``, an error reaction.
"""

import ast
import base64
import json
from typing import Any
from uuid import UUID

from agentarea_common.events.redaction import mask_inline_secrets
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .errors import ProcessorCodeError, ProcessorFailedError
from .models import StreamEvent

MAX_CODE_BYTES = 64 * 1024
TIMEOUT_SECONDS = 10
MAX_RESULT_BYTES = 256 * 1024
MAX_OUTPUTS = 100
#: The sandbox's command body limit (Go ``sandboxcontract.MaxCommandBodyBytes``).
MAX_COMMAND_BYTES = 256 * 1024
#: What the sandbox reports for a command it stopped at its timeout.
TIMED_OUT_EXIT = 124
_MAX_REASON_CHARS = 1000
_DELIMITER = "AGENTAREA_PROCESSOR_HARNESS"

_HARNESS = """import base64, json, sys, traceback
code = base64.b64decode("__CODE__").decode()
event = json.loads(base64.b64decode("__EVENT__"))
result = sys.stdout
sys.stdout = sys.stderr
def failure(error):
    frames = [f for f in traceback.extract_tb(error.__traceback__) if f.filename == "processor.py"]
    where = f" (processor.py line {frames[-1].lineno})" if frames else ""
    return {"ok": False, "error": f"{type(error).__name__}: {error}{where}"}
try:
    scope = {"__name__": "processor"}
    exec(compile(code, "processor.py", "exec"), scope)
    text = json.dumps({"ok": True, "outputs": scope["process"](event)})
except BaseException as error:
    text = json.dumps(failure(error))
result.write(text)
result.flush()
"""


class CodeRun(BaseModel):
    """What the sandbox reports of one run; stderr is read only when the run failed."""

    exit_code: int
    stdout: str
    stdout_truncated: bool
    stderr: str = ""


class ProcessorOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    stream: str = Field(min_length=1, max_length=255)
    kind: str = Field(min_length=1, max_length=255)
    data: dict[str, Any]
    key: str | None = Field(default=None, min_length=1, max_length=512)


def sandbox_session(processor_id: UUID) -> str:
    """The sandbox session every run of one processor shares, so it stays warm."""
    return f"processor-{processor_id}"


def _secret_assignment(name: str, value: ast.expr) -> bool:
    if not isinstance(value, ast.Constant) or not isinstance(value.value, str) or not value.value:
        return False
    written = f"{json.dumps(name)}: {json.dumps(value.value)}"
    return mask_inline_secrets(written) != written


def _secret_line(tree: ast.Module) -> int | None:
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if mask_inline_secrets(node.value) != node.value:
                return node.lineno
        pairs: list[tuple[str, ast.expr]] = []
        if isinstance(node, ast.Assign):
            pairs = [(t.id, node.value) for t in node.targets if isinstance(t, ast.Name)]
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value:
            pairs = [(node.target.id, node.value)]
        elif isinstance(node, ast.keyword) and node.arg:
            pairs = [(node.arg, node.value)]
        elif isinstance(node, ast.Dict):
            pairs = [
                (k.value, v)
                for k, v in zip(node.keys, node.values, strict=True)
                if isinstance(k, ast.Constant) and isinstance(k.value, str)
            ]
        elif isinstance(node, ast.FunctionDef):
            positional = [*node.args.posonlyargs, *node.args.args]
            defaults = node.args.defaults
            pairs = [
                (a.arg, d)
                for a, d in zip(
                    positional[len(positional) - len(defaults) :], defaults, strict=True
                )
            ]
            pairs += [
                (a.arg, d)
                for a, d in zip(node.args.kwonlyargs, node.args.kw_defaults, strict=True)
                if d is not None
            ]
        if any(_secret_assignment(name, value) for name, value in pairs):
            return getattr(node, "lineno", None)
    return None


def _defines_process(tree: ast.Module) -> bool:
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "process":
            args = node.args
            return bool(args.posonlyargs or args.args or args.vararg)
    return False


def check_code(code: str) -> None:
    """Refuse code that cannot run as a processor, or that holds a secret."""
    if not code.strip():
        raise ProcessorCodeError("The processor's code is empty")
    size = len(code.encode())
    if size > MAX_CODE_BYTES:
        raise ProcessorCodeError(f"The code is {size} bytes; a processor holds {MAX_CODE_BYTES}")
    try:
        tree = ast.parse(code, "processor.py")
    except SyntaxError as error:
        raise ProcessorCodeError(
            f"The code does not parse: {error.msg} (line {error.lineno})"
        ) from error
    if not _defines_process(tree):
        raise ProcessorCodeError(
            "The code must define a top-level def process(event) returning a list of events or None"
        )
    line = _secret_line(tree)
    if line is not None:
        raise ProcessorCodeError(
            f"Line {line} holds what looks like a secret. A processor gets no secrets, "
            "and its code is shown to everyone who reads the stream"
        )


def event_payload(event: StreamEvent) -> dict[str, Any]:
    """The event as ``process`` receives it: the envelope, with ``key`` and ``kind``."""
    return {
        "id": str(event.id),
        "kind": event.type,
        "source": event.source,
        "subject": event.subject,
        "time": event.time.isoformat(),
        "received_at": event.received_at.isoformat(),
        "stream_id": str(event.stream_id),
        "key": event.event_key,
        "source_type": event.source_type,
        "session_key": event.session_key,
        "sender": event.sender,
        "correlation_id": event.correlation_id,
        "causation_id": event.causation_id,
        "depth": event.depth,
        "data": event.data,
        "attachments": [a.model_dump(mode="json") for a in event.attachments],
    }


def _inline(value: bytes) -> str:
    return base64.b64encode(value).decode()


def harness_command(code: str, payload: dict[str, Any]) -> str:
    """The bash command that runs ``process`` over ``payload`` and prints its result."""
    event = json.dumps(payload, separators=(",", ":"), ensure_ascii=False, default=str).encode()
    script = _HARNESS.replace("__CODE__", _inline(code.encode())).replace(
        "__EVENT__", _inline(event)
    )
    command = f"python3 - <<'{_DELIMITER}'\n{script}{_DELIMITER}\n"
    if len(command.encode()) > MAX_COMMAND_BYTES:
        raise ProcessorFailedError(
            f"The event is too large for a processor: {len(event)} bytes of event and "
            f"{len(code.encode())} of code exceed {MAX_COMMAND_BYTES} bytes once encoded"
        )
    return command


def _clip(text: str) -> str:
    return text if len(text) <= _MAX_REASON_CHARS else f"{text[: _MAX_REASON_CHARS - 1]}…"


def _json_type(value: Any) -> str:
    names = {dict: "an object", str: "a string", bool: "a boolean", int: "a number"}
    return names.get(type(value), "a number" if isinstance(value, float) else "a value")


def _first_problem(error: ValidationError) -> str:
    problem = error.errors()[0]
    where = ".".join(str(p) for p in problem["loc"])
    return f"{where}: {problem['msg']}" if where else problem["msg"]


def outputs_of(run: CodeRun) -> list[ProcessorOutput]:
    """The events one run wrote; ``ProcessorFailedError`` when the run is no usable result."""
    if run.exit_code == TIMED_OUT_EXIT:
        raise ProcessorFailedError(f"process() did not finish within {TIMEOUT_SECONDS}s")
    if run.stdout_truncated:
        raise ProcessorFailedError(f"process() returned more than {MAX_RESULT_BYTES} bytes")
    if run.exit_code != 0:
        tail = " ".join(run.stderr.split())[-300:]
        raise ProcessorFailedError(
            _clip(f"The processor exited with code {run.exit_code}" + (f": {tail}" if tail else ""))
        )
    try:
        result = json.loads(run.stdout)
    except ValueError:
        result = None
    if not isinstance(result, dict) or not isinstance(result.get("ok"), bool):
        raise ProcessorFailedError("The processor printed no result")
    if not result["ok"]:
        raise ProcessorFailedError(_clip(str(result.get("error"))))
    outputs = result.get("outputs")
    if outputs is None:
        return []
    if not isinstance(outputs, list):
        raise ProcessorFailedError(
            f"process() must return a list of events or None, not {_json_type(outputs)}"
        )
    if len(outputs) > MAX_OUTPUTS:
        raise ProcessorFailedError(f"process() returned more than {MAX_OUTPUTS} events")
    parsed: list[ProcessorOutput] = []
    for index, item in enumerate(outputs):
        try:
            parsed.append(ProcessorOutput.model_validate(item))
        except ValidationError as error:
            raise ProcessorFailedError(
                _clip(f"event {index} is not {{stream, kind, data, key?}}: {_first_problem(error)}")
            ) from error
    return parsed


def resolve_streams(
    outputs: list[ProcessorOutput], declared: dict[UUID, str], input_stream_id: UUID
) -> list[tuple[UUID, ProcessorOutput]]:
    """Each output with the declared stream it names, by id or by name."""
    by_name = {name: stream_id for stream_id, name in declared.items()}
    by_id = {str(stream_id): stream_id for stream_id in declared}
    routed: list[tuple[UUID, ProcessorOutput]] = []
    for index, output in enumerate(outputs):
        stream_id = by_id.get(output.stream) or by_name.get(output.stream)
        if stream_id == input_stream_id or output.stream == str(input_stream_id):
            raise ProcessorFailedError(
                f"event {index} names the processor's own input stream; a processor never "
                "writes to its own input"
            )
        if stream_id is None:
            names = ", ".join(sorted(declared.values())) or "none"
            raise ProcessorFailedError(
                _clip(
                    f"event {index} names stream {output.stream!r}, which is not one of this "
                    f"processor's outputs ({names})"
                )
            )
        routed.append((stream_id, output))
    return routed
