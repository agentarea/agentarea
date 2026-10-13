"""What a tool call costs, as its connector declares it (wiki ADR-0038).

A connector is a definition, not code: an OpenAPI connection carries
``x-agentarea-payers`` at the root of its spec and ``x-agentarea-cost`` at the root
(the default) or on an operation; a catalog MCP server carries the same under
``agentarea:payers`` / ``agentarea:cost`` in its metadata. A declaration is::

    {"source": "free" | "rate" | "reported" | "settled" | "unknown",
     "unit": "request",
     "rate": {"amount": "0.488", "currency": "RUB",
              "quantity": 1 | {"arg": "num_phrases", "default": 50}
                          | {"count": "$.items"} | {"path": "$.usage.pages"}},
     "reported": {"path": "$.cost" | "meta": "<_meta key>", "currency": "USD"}}

``meter`` turns one call's arguments and response into what the vendor charged
the payer, or None when nothing is known at call time.
"""

import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any

DEFAULT_UNIT = "call"
_CURRENCY = re.compile(r"[A-Z]{3}")
_PATH_STEP = re.compile(r"\.([A-Za-z_][A-Za-z0-9_\-]*)|\[(\d+)\]")
_PATH = re.compile(r"\$(?:\.[A-Za-z_][A-Za-z0-9_\-]*|\[\d+\])*")


class ToolCostError(ValueError):
    """A cost declaration is malformed, or a call cannot be metered by it."""


class Payer(StrEnum):
    """Whose money a call spends."""

    WORKSPACE = "workspace"
    PLATFORM = "platform"
    PER_CALL = "per_call"


class CostSourceKind(StrEnum):
    FREE = "free"
    RATE = "rate"
    REPORTED = "reported"
    SETTLED = "settled"
    UNKNOWN = "unknown"


def json_path(doc: Any, path: str) -> Any:
    """The value at ``path`` (``$``, ``.key``, ``[n]`` steps) in ``doc``; KeyError if absent."""
    if not path.startswith("$"):
        raise KeyError(path)
    rest, node = path[1:], doc
    while rest:
        step = _PATH_STEP.match(rest)
        if step is None:
            raise KeyError(path)
        key, index = step.groups()
        if key is not None:
            if not isinstance(node, dict) or key not in node:
                raise KeyError(path)
            node = node[key]
        else:
            if not isinstance(node, list) or int(index) >= len(node):
                raise KeyError(path)
            node = node[int(index)]
        rest = rest[step.end() :]
    return node


def _valid_path(path: Any, where: str) -> str:
    if not isinstance(path, str) or not _PATH.fullmatch(path):
        raise ToolCostError(f"{where} must be a path like $.field, got {path!r}")
    return path


def _decimal(value: Any, where: str) -> Decimal:
    if isinstance(value, bool):
        raise ToolCostError(f"{where} must be a number")
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        raise ToolCostError(f"{where} must be a number, got {value!r}") from None
    if not number.is_finite() or number < 0:
        raise ToolCostError(f"{where} must be a non-negative number, got {value!r}")
    return number


def _required[T](value: T | None, where: str) -> T:
    if value is None:
        raise ToolCostError(f"{where} is not declared")
    return value


def _currency(value: Any, where: str) -> str:
    if not isinstance(value, str) or not _CURRENCY.fullmatch(value):
        raise ToolCostError(f"{where} must be an ISO 4217 code like RUB, got {value!r}")
    return value


@dataclass(frozen=True)
class Quantity:
    """How many units one call used: a constant, an argument, or read from the response."""

    constant: Decimal | None = Decimal(1)
    arg: str | None = None
    default: Decimal | None = None
    count: str | None = None
    path: str | None = None

    def evaluate(self, args: dict[str, Any], body: Any) -> Decimal:
        if self.arg is not None:
            if args.get(self.arg) is not None:
                return _decimal(args[self.arg], f"argument {self.arg}")
            if self.default is None:
                raise ToolCostError(f"argument {self.arg} is missing and declares no default")
            return self.default
        if self.count is not None:
            items = _read(body, self.count)
            if not isinstance(items, list):
                raise ToolCostError(f"{self.count} in the response is not a list")
            return Decimal(len(items))
        if self.path is not None:
            return _decimal(_read(body, self.path), self.path)
        return _required(self.constant, "rate.quantity")


def _quantity(raw: Any) -> Quantity:
    if raw is None:
        return Quantity()
    if not isinstance(raw, dict):
        return Quantity(constant=_decimal(raw, "rate.quantity"))
    if set(raw) - {"arg", "default", "count", "path"} or len(set(raw) - {"default"}) != 1:
        raise ToolCostError(f"rate.quantity must be one of arg, count, path; got {raw!r}")
    if "arg" in raw:
        if not isinstance(raw["arg"], str) or not raw["arg"]:
            raise ToolCostError("rate.quantity.arg must name an argument")
        default = raw.get("default")
        return Quantity(
            constant=None,
            arg=raw["arg"],
            default=None if default is None else _decimal(default, "rate.quantity.default"),
        )
    if "default" in raw:
        raise ToolCostError("rate.quantity.default applies only to arg")
    if "count" in raw:
        return Quantity(constant=None, count=_valid_path(raw["count"], "rate.quantity.count"))
    return Quantity(constant=None, path=_valid_path(raw["path"], "rate.quantity.path"))


@dataclass(frozen=True)
class ToolCostModel:
    source: CostSourceKind
    unit: str = DEFAULT_UNIT
    rate_amount: Decimal | None = None
    currency: str | None = None
    quantity: Quantity = field(default_factory=Quantity)
    reported_path: str | None = None
    reported_meta: str | None = None


UNKNOWN_COST = ToolCostModel(CostSourceKind.UNKNOWN)


def parse_cost_model(raw: Any) -> ToolCostModel:
    """A declaration as a model; None is an unknown cost. Malformed raises ToolCostError."""
    if raw is None:
        return UNKNOWN_COST
    if not isinstance(raw, dict):
        raise ToolCostError(f"a cost declaration must be an object, got {raw!r}")
    try:
        source = CostSourceKind(raw.get("source"))
    except ValueError:
        raise ToolCostError(f"unknown cost source {raw.get('source')!r}") from None
    unit = raw.get("unit") or DEFAULT_UNIT
    if not isinstance(unit, str):
        raise ToolCostError("unit must be a string")
    if source is CostSourceKind.RATE:
        rate = raw.get("rate")
        if not isinstance(rate, dict):
            raise ToolCostError("a rate cost declares rate: {amount, currency}")
        return ToolCostModel(
            source,
            unit,
            rate_amount=_decimal(rate.get("amount"), "rate.amount"),
            currency=_currency(rate.get("currency"), "rate.currency"),
            quantity=_quantity(rate.get("quantity")),
        )
    if source is CostSourceKind.REPORTED:
        reported = raw.get("reported")
        if not isinstance(reported, dict) or ("path" in reported) == ("meta" in reported):
            raise ToolCostError("a reported cost declares reported: {path | meta, currency}")
        meta = reported.get("meta")
        if "meta" in reported and (not isinstance(meta, str) or not meta):
            raise ToolCostError("reported.meta must name a _meta key")
        return ToolCostModel(
            source,
            unit,
            currency=_currency(reported.get("currency"), "reported.currency"),
            reported_path=(
                _valid_path(reported["path"], "reported.path") if "path" in reported else None
            ),
            reported_meta=meta,
        )
    return ToolCostModel(source, unit)


def resolve_cost_model(default: Any, own: Any) -> ToolCostModel:
    """An operation's own declaration, else its connector's default."""
    return parse_cost_model(own if own is not None else default)


def connector_payers(raw: Any) -> tuple[Payer, ...]:
    """The payers a connector allows; a connector that names none is paid by the workspace."""
    if raw is None:
        return (Payer.WORKSPACE,)
    if not isinstance(raw, list) or not raw:
        raise ToolCostError(f"payers must be a non-empty list, got {raw!r}")
    try:
        return tuple(Payer(value) for value in raw)
    except ValueError as error:
        raise ToolCostError(f"unknown payer in {raw!r}") from error


@dataclass(frozen=True)
class ToolConnection:
    """The connection a call runs on, and what its connector declares the tool costs.

    ``connector`` is the catalog id the connection was made from, or
    ``connection:<id>`` for one made by hand; an installed pricing prices by it.
    """

    connection_id: str
    connector: str
    tool: str
    payer: Payer
    cost_model: ToolCostModel

    @property
    def resource_ref(self) -> str:
        return f"{self.connector}#{self.tool}"


def tool_connection(
    *,
    connection_id: str,
    connector: str,
    tool: str,
    platform_managed: bool,
    payers: Any,
    cost: Any,
) -> ToolConnection:
    """A call's connection as its connector declares it; a payer it does not allow raises.

    A platform-managed connection runs on the platform's key, any other on the
    workspace's. Wallet payments are metered from the call, not declared here.
    """
    payer = Payer.PLATFORM if platform_managed else Payer.WORKSPACE
    if payer not in connector_payers(payers):
        raise ToolCostError(f"{connector} does not allow calls paid by the {payer.value}")
    return ToolConnection(connection_id, connector, tool, payer, parse_cost_model(cost))


def manual_connector(connection_id: Any) -> str:
    """The connector id of a connection made by hand rather than from the catalog."""
    return f"connection:{connection_id}"


@dataclass(frozen=True)
class MeteredCost:
    """What one call cost the payer, as the vendor charged it."""

    quantity: Decimal
    unit: str
    vendor_cost: Decimal
    currency: str
    source: CostSourceKind


def _read(body: Any, path: str) -> Any:
    try:
        return json_path(body, path)
    except KeyError:
        raise ToolCostError(f"the response carries no {path}") from None


def meter(
    model: ToolCostModel,
    *,
    args: dict[str, Any],
    body: Any,
    meta: dict[str, Any] | None = None,
) -> MeteredCost | None:
    """What one call cost, or None when nothing is known until later (or ever).

    A declared cost the call cannot be measured by raises: the line is missing,
    and that is an error to see, not a zero to sum.
    """
    if model.source is CostSourceKind.RATE:
        amount = _required(model.rate_amount, "rate.amount")
        quantity = model.quantity.evaluate(args, body)
        return MeteredCost(
            quantity,
            model.unit,
            amount * quantity,
            _required(model.currency, "rate.currency"),
            model.source,
        )
    if model.source is CostSourceKind.REPORTED:
        currency = _required(model.currency, "reported.currency")
        if model.reported_meta is not None:
            if model.reported_meta not in (meta or {}):
                raise ToolCostError(f"the result's _meta carries no {model.reported_meta}")
            value = (meta or {})[model.reported_meta]
            where = model.reported_meta
        else:
            where = _required(model.reported_path, "reported.path")
            value = _read(body, where)
        return MeteredCost(Decimal(1), model.unit, _decimal(value, where), currency, model.source)
    return None
