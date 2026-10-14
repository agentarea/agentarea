"""What a tool call costs, as its connector declares it (wiki ADR-0038).

A connector is a definition, not code: an OpenAPI connection carries
``x-agentarea-payers`` at the root of its spec and ``x-agentarea-cost`` at the root
(the default) or on an operation; a catalog MCP server carries the same under
``agentarea:payers`` / ``agentarea:cost`` in its metadata. A declaration is::

    {"source": "free" | "rate" | "reported" | "settled" | "unknown",
     "unit": "request",
     "exact": true | false,
     "rate": {"amount": "0.488", "currency": "RUB",
              "quantity": 1 | {"arg": "num_phrases", "default": 50}
                          | {"count": "$.items"} | {"path": "$.usage.pages"}},
     "reported": {"path": "$.cost" | "meta": "<_meta key>" [+ "path"], "currency": "USD"},
     "estimate": {"amount": "0.05", "currency": "USD"},
     "settled": {"fetch": {"url": "https://api.apify.com/v2/actor-runs/{run_id}",
                           "params": {"run_id": "$.data.id" | {"meta": "<_meta key>"}},
                           "cost": "$.data.usageTotalUsd", "currency": "USD",
                           "done": {"path": "$.data.status", "in": ["SUCCEEDED"]}}}}

``exact`` says the figure is what the vendor bills: true by default for a reported or
settled cost, false for a rate. ``estimate`` is the figure before the call for a cost
known only afterwards. A settled cost is read later with the connection's own
credential, from ``fetch.url`` with ``params`` taken from the call's response.

``pre_call_cost`` is what a call will cost before it runs, ``meter`` what one call
cost from its arguments and response, and ``settled_cost`` what a settlement fetch
says it finally cost.
"""

import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any
from urllib.parse import quote

DEFAULT_UNIT = "call"
_CURRENCY = re.compile(r"[A-Z]{3}")
_PATH_STEP = re.compile(r"\.([A-Za-z_][A-Za-z0-9_\-]*)|\[(\d+)\]")
_PATH = re.compile(r"\$(?:\.[A-Za-z_][A-Za-z0-9_\-]*|\[\d+\])*")
_URL_PARAM = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")
# Currencies that are another's under a different name: a USD stablecoin is USD.
_SAME_CURRENCY = {"USDC": "USD"}


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
    value = _SAME_CURRENCY.get(value, value) if isinstance(value, str) else value
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
class ValueRef:
    """Where a value is read from in a call's result: a path in its body, or a _meta key."""

    path: str | None = None
    meta: str | None = None

    def read(self, body: Any, meta: dict[str, Any] | None) -> Any:
        if self.meta is not None:
            if self.meta not in (meta or {}):
                raise ToolCostError(f"the result's _meta carries no {self.meta}")
            return (meta or {})[self.meta]
        return _read(body, _required(self.path, "path"))


@dataclass(frozen=True)
class SettleFetch:
    """How the cost of a call is read later: one GET with the connection's credential."""

    url: str
    params: tuple[tuple[str, ValueRef], ...]
    cost_path: str
    currency: str
    done_path: str | None = None
    done_in: tuple[str, ...] = ()


@dataclass(frozen=True)
class ToolCostModel:
    source: CostSourceKind
    unit: str = DEFAULT_UNIT
    rate_amount: Decimal | None = None
    currency: str | None = None
    quantity: Quantity = field(default_factory=Quantity)
    reported_path: str | None = None
    reported_meta: str | None = None
    exact: bool = False
    estimate_amount: Decimal | None = None
    estimate_currency: str | None = None
    settle: SettleFetch | None = None


UNKNOWN_COST = ToolCostModel(CostSourceKind.UNKNOWN)


def _value_ref(raw: Any, where: str) -> ValueRef:
    if isinstance(raw, dict) and set(raw) == {"meta"}:
        if not isinstance(raw["meta"], str) or not raw["meta"]:
            raise ToolCostError(f"{where}.meta must name a _meta key")
        return ValueRef(meta=raw["meta"])
    return ValueRef(path=_valid_path(raw, where))


def _settle_fetch(raw: Any) -> SettleFetch:
    fetch = raw.get("fetch") if isinstance(raw, dict) else None
    if not isinstance(fetch, dict):
        raise ToolCostError(
            "a settled cost declares settled: {fetch: {url, params, cost, currency}}"
        )
    url = fetch.get("url")
    if not isinstance(url, str) or not url.startswith("https://"):
        raise ToolCostError(f"settled.fetch.url must be an https URL, got {url!r}")
    params = fetch.get("params") or {}
    if not isinstance(params, dict):
        raise ToolCostError("settled.fetch.params must map URL parameters to result paths")
    missing = set(_URL_PARAM.findall(url)) - set(params)
    if missing:
        raise ToolCostError(f"settled.fetch.url names {sorted(missing)} that params do not read")
    done = fetch.get("done")
    done_path: str | None = None
    done_in: tuple[str, ...] = ()
    if done is not None:
        values = done.get("in") if isinstance(done, dict) else None
        if (
            not isinstance(values, list)
            or not values
            or not all(isinstance(v, str) for v in values)
        ):
            raise ToolCostError("settled.fetch.done declares {path, in: [values]}")
        done_path, done_in = _valid_path(done.get("path"), "settled.fetch.done.path"), tuple(values)
    return SettleFetch(
        url=url,
        params=tuple(
            (name, _value_ref(ref, f"settled.fetch.params.{name}")) for name, ref in params.items()
        ),
        cost_path=_valid_path(fetch.get("cost"), "settled.fetch.cost"),
        currency=_currency(fetch.get("currency"), "settled.fetch.currency"),
        done_path=done_path,
        done_in=done_in,
    )


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
    exact = raw.get("exact", source in (CostSourceKind.REPORTED, CostSourceKind.SETTLED))
    if not isinstance(exact, bool):
        raise ToolCostError("exact must be true or false")
    estimate = raw.get("estimate")
    estimate_amount = estimate_currency = None
    if estimate is not None:
        if not isinstance(estimate, dict):
            raise ToolCostError("estimate declares {amount, currency}")
        estimate_amount = _decimal(estimate.get("amount"), "estimate.amount")
        estimate_currency = _currency(estimate.get("currency"), "estimate.currency")
    common: dict[str, Any] = {
        "exact": exact,
        "estimate_amount": estimate_amount,
        "estimate_currency": estimate_currency,
    }
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
            **common,
        )
    if source is CostSourceKind.REPORTED:
        reported = raw.get("reported")
        if not isinstance(reported, dict) or ("path" not in reported and "meta" not in reported):
            raise ToolCostError(
                "a reported cost declares reported: {path | meta [+ path], currency}"
            )
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
            **common,
        )
    if source is CostSourceKind.SETTLED:
        settle = _settle_fetch(raw.get("settled"))
        if estimate_currency is not None and estimate_currency != settle.currency:
            raise ToolCostError(
                f"estimate is in {estimate_currency} but the settled cost in {settle.currency}"
            )
        return ToolCostModel(source, unit, currency=settle.currency, settle=settle, **common)
    return ToolCostModel(source, unit, **common)


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
    override: Any = None,
) -> ToolConnection:
    """A call's connection as its connector declares it; a payer it does not allow raises.

    A platform-managed connection runs on the platform's key, any other on the
    workspace's. ``override`` is the cost a member set on a connection the workspace
    pays for, which wins over the connector's. Wallet payments are metered from the
    call, not declared here.
    """
    payer = Payer.PLATFORM if platform_managed else Payer.WORKSPACE
    if payer not in connector_payers(payers):
        raise ToolCostError(f"{connector} does not allow calls paid by the {payer.value}")
    if override is None:
        return ToolConnection(connection_id, connector, tool, payer, parse_cost_model(cost))
    if payer is Payer.PLATFORM:
        raise ToolCostError("the cost of a connection the platform pays for is not set on it")
    return ToolConnection(connection_id, connector, tool, payer, parse_connection_cost(override))


def parse_connection_cost(raw: Any) -> ToolCostModel:
    """A cost a member sets on a connection: a rate, a reported field, or free.

    A settled cost is not one: it would send the connection's credential to the URL
    the declaration names, which only a catalog entry may name.
    """
    model = parse_cost_model(raw)
    if model.source not in (CostSourceKind.RATE, CostSourceKind.REPORTED, CostSourceKind.FREE):
        raise ToolCostError(
            f"a connection's own cost is a rate, a reported field or free, not {model.source.value}"
        )
    return model


def manual_connector(connection_id: Any) -> str:
    """The connector id of a connection made by hand rather than from the catalog."""
    return f"connection:{connection_id}"


@dataclass(frozen=True)
class MeteredCost:
    """What one call cost the payer, as the vendor charged it.

    ``exact`` is False for an estimate. ``settle_params`` are what a settled cost is
    fetched with later, read from the call's result.
    """

    quantity: Decimal
    unit: str
    vendor_cost: Decimal
    currency: str
    source: CostSourceKind
    exact: bool = True
    settle_params: dict[str, str] | None = None


def _estimate(model: ToolCostModel) -> MeteredCost | None:
    if model.estimate_amount is None or model.estimate_currency is None:
        return None
    return MeteredCost(
        Decimal(1),
        model.unit,
        model.estimate_amount,
        model.estimate_currency,
        model.source,
        exact=False,
    )


def pre_call_cost(model: ToolCostModel, *, args: dict[str, Any]) -> MeteredCost | None:
    """What a call will cost before it runs, or None when nothing says.

    A rate counted from a constant or an argument is known; any other cost is its
    declared estimate.
    """
    if model.source is CostSourceKind.RATE and (
        model.quantity.constant is not None or model.quantity.arg is not None
    ):
        return meter(model, args=args, body=None)
    if model.source in (CostSourceKind.FREE, CostSourceKind.UNKNOWN):
        return None
    return _estimate(model)


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
            exact=model.exact,
        )
    if model.source is CostSourceKind.REPORTED:
        currency = _required(model.currency, "reported.currency")
        if model.reported_meta is not None:
            if model.reported_meta not in (meta or {}):
                raise ToolCostError(f"the result's _meta carries no {model.reported_meta}")
            value = (meta or {})[model.reported_meta]
            where = model.reported_meta
            if model.reported_path is not None:
                # A path inside that _meta value, e.g. Apify's {"com.apify/ActorRun": {...}}.
                value = _read(value, model.reported_path)
                where = f"{model.reported_meta}{model.reported_path[1:]}"
        else:
            where = _required(model.reported_path, "reported.path")
            value = _read(body, where)
        return MeteredCost(
            Decimal(1),
            model.unit,
            _decimal(value, where),
            currency,
            model.source,
            exact=model.exact,
        )
    if model.source is CostSourceKind.SETTLED:
        settle = _required(model.settle, "settled.fetch")
        params = {}
        for name, ref in settle.params:
            value = ref.read(body, meta)
            if not isinstance(value, str | int) or isinstance(value, bool) or value == "":
                raise ToolCostError(f"settled.fetch.params.{name} read {value!r}, not an id")
            params[name] = str(value)
        return MeteredCost(
            Decimal(1),
            model.unit,
            model.estimate_amount or Decimal(0),
            settle.currency,
            model.source,
            exact=False,
            settle_params=params,
        )
    return None


def settle_url(model: ToolCostModel, params: dict[str, str]) -> str:
    """The URL a settled cost is fetched from, with the parameters the call returned."""
    settle = _required(model.settle, "settled.fetch")

    def fill(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in params:
            raise ToolCostError(f"the line keeps no {name} to settle with")
        return quote(params[name], safe="")

    return _URL_PARAM.sub(fill, settle.url)


def settled_cost(model: ToolCostModel, body: Any) -> MeteredCost | None:
    """What a settlement fetch says the call cost, or None while it is not done."""
    settle = _required(model.settle, "settled.fetch")
    if settle.done_path is not None and _read(body, settle.done_path) not in settle.done_in:
        return None
    return MeteredCost(
        Decimal(1),
        model.unit,
        _decimal(_read(body, settle.cost_path), settle.cost_path),
        settle.currency,
        model.source,
        exact=model.exact,
    )
