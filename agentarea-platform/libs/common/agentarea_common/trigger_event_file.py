"""The run input that holds a trigger's event when it is too large to quote.

The trigger service names the file and stores the event's scrubbed data beside
it in ``task_parameters``; the run's config activity writes that data there, in
the task's own ``inputs/attachments`` scope, before the agent starts -- the
scope uploaded attachments use, never the workspace's shared files.
"""

import json
import re
from typing import Any

TRIGGER_EVENT_FILE_PARAMETER = "trigger_event_file"
TRIGGER_EVENT_PARAMETER = "trigger_event"
TRIGGER_EVENT_FILE_CONTENT_TYPE = "application/json"

_FILE_NAME = re.compile(r"^trigger-event(?:-\d+)?\.json$")


def trigger_event_file_name(sequence: int | None) -> str:
    return "trigger-event.json" if sequence is None else f"trigger-event-{sequence}.json"


def is_trigger_event_file_name(name: Any) -> bool:
    return isinstance(name, str) and _FILE_NAME.fullmatch(name) is not None


def trigger_event_file_path(name: str) -> str:
    if not is_trigger_event_file_name(name):
        raise ValueError(f"not a trigger event file name: {name!r}")
    return f"inputs/attachments/{name}"


def event_data_json(data: dict[str, Any]) -> str:
    """The one serialization of event data, quoted inline and written to the file alike."""
    return json.dumps(data, indent=2, ensure_ascii=False, default=str)
