"""A catalog API connection's key form: what to ask for, and where each value goes.

A catalog item that authenticates with keys rather than OAuth publishes
``api_key.fields`` in its spec, one entry per value the vendor needs:

    {"name": "Authorization", "location": "header", "scheme": "Token", "label": "API key"}
    {"name": "key", "location": "query", "label": "API key"}

A header value is sent as ``<scheme> <value>`` when the field names a scheme. Every
value is stored as a secret of the connection the person creates, never in the row.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal

from agentarea_openapi.schemas.dto import HeaderInput, QueryParamInput

KeyLocation = Literal["header", "query"]

_HEADER_NAME = re.compile(r"[A-Za-z0-9\-_]+")
_QUERY_NAME = re.compile(r"[A-Za-z0-9_.\-\[\]]+")
_SCHEME = re.compile(r"[A-Za-z0-9\-_]+")


class CatalogKeyTemplateError(ValueError):
    """The catalog item's key template is malformed: the catalog's fault, not the caller's."""


@dataclass(frozen=True)
class CatalogKeyField:
    name: str
    location: KeyLocation
    label: str
    scheme: str | None = None
    description: str | None = None


@dataclass(frozen=True)
class CatalogKeyTemplate:
    fields: tuple[CatalogKeyField, ...]


def _field(entry: Any) -> CatalogKeyField:
    if not isinstance(entry, dict):
        raise CatalogKeyTemplateError("api_key field is not an object")
    name, location, label = entry.get("name"), entry.get("location"), entry.get("label")
    scheme, description = entry.get("scheme"), entry.get("description")
    if location not in ("header", "query"):
        raise CatalogKeyTemplateError(f"api_key field location {location!r} is not header or query")
    pattern = _HEADER_NAME if location == "header" else _QUERY_NAME
    if not isinstance(name, str) or not pattern.fullmatch(name):
        raise CatalogKeyTemplateError(f"api_key field name {name!r} is not a valid {location} name")
    if not isinstance(label, str) or not label.strip():
        raise CatalogKeyTemplateError(f"api_key field {name} has no label")
    if scheme is not None and (
        location != "header" or not isinstance(scheme, str) or not _SCHEME.fullmatch(scheme)
    ):
        raise CatalogKeyTemplateError(f"api_key field {name} has an invalid scheme")
    if description is not None and not isinstance(description, str):
        raise CatalogKeyTemplateError(f"api_key field {name} has an invalid description")
    return CatalogKeyField(
        name=name,
        location=location,
        label=label.strip(),
        scheme=scheme,
        description=description or None,
    )


def catalog_key_template(spec: dict[str, Any]) -> CatalogKeyTemplate | None:
    """The key form a catalog item declares, or None when it authenticates another way."""
    block = spec.get("api_key")
    if block is None:
        return None
    if not isinstance(block, dict):
        raise CatalogKeyTemplateError("api_key is not an object")
    entries = block.get("fields")
    if not isinstance(entries, list) or not entries:
        raise CatalogKeyTemplateError("api_key declares no fields")
    fields = tuple(_field(entry) for entry in entries)
    seen = [(f.location, f.name.lower() if f.location == "header" else f.name) for f in fields]
    if len(set(seen)) != len(seen):
        raise CatalogKeyTemplateError("api_key declares the same field twice")
    return CatalogKeyTemplate(fields=fields)


def catalog_key_credentials(
    template: CatalogKeyTemplate, values: dict[str, str]
) -> tuple[list[HeaderInput], list[QueryParamInput]]:
    """The headers and query parameters a new connection stores, one per field."""
    known = {f.name for f in template.fields}
    unknown = sorted(set(values) - known)
    if unknown:
        raise ValueError(f"Not a field of this connection: {', '.join(unknown)}")

    headers: list[HeaderInput] = []
    params: list[QueryParamInput] = []
    for field in template.fields:
        value = (values.get(field.name) or "").strip()
        if not value:
            raise ValueError(f"{field.label} is required")
        if field.location == "header":
            headers.append(
                HeaderInput(
                    name=field.name, value=f"{field.scheme} {value}" if field.scheme else value
                )
            )
        else:
            params.append(QueryParamInput(name=field.name, value=value, secret=True))
    return headers, params
