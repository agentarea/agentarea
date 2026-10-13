"""Reshape a vendor's response before the agent sees it, as the connector declares.

``x-agentarea-response-transform`` on an OpenAPI operation is a list of steps, each
replacing the value at ``at`` in the decoded JSON body::

    [{"decode": "base64", "at": "$.rawData"}, {"parse": "xml", "at": "$.rawData"}]

Parsed XML becomes JSON the way ``xmltodict`` writes it: an element is an object
keyed by child tag, attributes as ``@name``, text as ``#text`` (or the bare string
when the element has nothing else), and repeated children as a list.
"""

import base64
import binascii
import xml.etree.ElementTree as ET
from typing import Any

from .tool_cost import json_path

_MAX_XML_BYTES = 8 << 20


class ResponseTransformError(ValueError):
    """A transform is malformed, or the response does not fit it."""


def _element(node: ET.Element) -> Any:
    out: dict[str, Any] = {f"@{name}": value for name, value in node.attrib.items()}
    for child in node:
        value = _element(child)
        if child.tag in out:
            existing = out[child.tag]
            out[child.tag] = [*existing, value] if isinstance(existing, list) else [existing, value]
        else:
            out[child.tag] = value
    text = (node.text or "").strip()
    if not out:
        return text
    if text:
        out["#text"] = text
    return out


def _parse_xml(value: Any) -> Any:
    raw = value.encode() if isinstance(value, str) else value
    if not isinstance(raw, bytes):
        raise ResponseTransformError("xml input must be text")
    if len(raw) > _MAX_XML_BYTES:
        raise ResponseTransformError("xml document is too large")
    if b"<!DOCTYPE" in raw or b"<!ENTITY" in raw:
        raise ResponseTransformError("xml documents with a DOCTYPE or ENTITY are refused")
    try:
        root = ET.fromstring(raw)  # noqa: S314 - no DOCTYPE, no entities, bounded size
    except ET.ParseError as error:
        raise ResponseTransformError(f"invalid xml: {error}") from error
    return {root.tag: _element(root)}


def _decode_base64(value: Any) -> str:
    if not isinstance(value, str):
        raise ResponseTransformError("base64 input must be text")
    try:
        return base64.b64decode(value, validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError) as error:
        raise ResponseTransformError(f"invalid base64: {error}") from error


_STEPS = {("decode", "base64"): _decode_base64, ("parse", "xml"): _parse_xml}


def _set(doc: Any, path: str, value: Any) -> None:
    parent_path, _, key = path.rpartition(".")
    if not parent_path or "[" in key:
        raise ResponseTransformError(f"cannot replace {path}: it must end in .field")
    parent = json_path(doc, parent_path)
    parent[key] = value


def apply_response_transform(steps: list[dict[str, Any]], body: Any) -> Any:
    """The body with every step applied in order; any failure raises."""
    for step in steps:
        if not isinstance(step, dict) or not isinstance(step.get("at"), str):
            raise ResponseTransformError(f"a transform step needs at: <path>, got {step!r}")
        kinds = [(kind, step[kind]) for kind in ("decode", "parse") if kind in step]
        if len(kinds) != 1 or kinds[0] not in _STEPS:
            raise ResponseTransformError(f"unknown transform step {step!r}")
        path = step["at"]
        try:
            current = json_path(body, path)
        except KeyError:
            raise ResponseTransformError(f"the response carries no {path}") from None
        _set(body, path, _STEPS[kinds[0]](current))
    return body
