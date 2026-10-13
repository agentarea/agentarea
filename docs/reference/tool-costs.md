---
title: Tool costs
type: reference
description: "The x-agentarea-* and agentarea:* fields a connector declares so each tool call is metered, counted against spend caps and, on the platform's key, billed."
prerequisites:
  - /concepts/integration/mcp
related:
  - /guides/governance/set-a-budget
  - /reference/policy-syntax
  - /reference/limits
  - /concepts/integration/registry-and-catalog
last_updated: 2026-10-13
---

A connector declares what its tool calls cost: who may pay, how the cost is known,
and how the vendor's response is reshaped. Every tool call, from a run or from a
Registered Client over `/mcp`, passes one layer that reads the declaration, checks
the spend caps before the call, and writes one line per known cost to the spend
ledger after it. The declaration is data in the connector; no code runs per vendor.

The parser is `agentarea_common/tool_cost.py`; the response transform is
`agentarea_common/response_transform.py`; the layer is
`agentarea_governance/tool_calls.py`.

## Where the declaration lives

| Connector | Payers | Cost |
|---|---|---|
| OpenAPI connection | `x-agentarea-payers` at the spec root | `x-agentarea-cost` at the spec root (the default) or on an operation (wins) |
| MCP server from the catalog | `agentarea:payers` in the server's `metadata` | `agentarea:cost` in `metadata`: `{"default": <cost>, "tools": {"<tool>": <cost>}}` |

An OpenAPI spec with a malformed declaration is refused when the connection is
created. An MCP connection with no catalog entry behind it declares nothing: its
calls have an `unknown` cost.

## Payers

| Value | Who is charged | Set by |
|---|---|---|
| `workspace` | The vendor bills the customer on their own key. The platform only meters. | Any connection a workspace creates |
| `platform` | The vendor bills the platform; the platform bills the workspace. | A connection with `managed_by = platform` |
| `per_call` | The agent's wallet pays the vendor at call time (x402, MPP). | A call that settles a wallet payment |

A connector that names no payers allows `workspace` only. A platform-managed
connection whose connector does not list `platform` is refused at call time.

## Cost declaration

```json
{
  "source": "rate",
  "unit": "request",
  "rate": {"amount": "0.488", "currency": "RUB", "quantity": 1}
}
```

| Field | Type | Applies to | Meaning |
|---|---|---|---|
| `source` | `free` \| `rate` \| `reported` \| `settled` \| `unknown` | all | How the cost is known. Required. |
| `unit` | string | all | Label for `quantity` on the ledger line. Default `call`. |
| `rate.amount` | decimal string or number, ≥ 0 | `rate` | Price of one unit, in `rate.currency`. |
| `rate.currency` | ISO 4217 code | `rate` | Currency the vendor charges in. |
| `rate.quantity` | see below | `rate` | Units one call uses. Default `1`. |
| `reported.path` | path | `reported` | Where the response body carries the cost. |
| `reported.meta` | string | `reported` | The MCP result `_meta` key that carries the cost. Exactly one of `path`, `meta`. |
| `reported.currency` | ISO 4217 code | `reported` | Currency of the reported cost. |

| `source` | Line written after a successful call |
|---|---|
| `free` | None. |
| `rate` | `amount × quantity`. |
| `reported` | The value read from the response. |
| `settled` | None at call time; a later reconciliation writes a line. |
| `unknown` | None. The call is in the audit trail only. |

A call that fails writes no declared-cost line. A declared cost the response does not
carry is logged as an error and writes no line; it is never recorded as zero.

### Quantity

| Form | Units |
|---|---|
| `2` | A constant. |
| `{"arg": "num_phrases", "default": 50}` | The call's argument, else `default`. Without a default a missing argument is an error. |
| `{"count": "$.items"}` | The length of the list at that path in the response. |
| `{"path": "$.usage.pages"}` | The number at that path in the response. |

Paths use `$`, `.field` and `[index]` steps only.

## Response transform (OpenAPI)

`x-agentarea-response-transform` on an operation is a list of steps applied, in
order, to the decoded JSON body before the agent sees it and before the cost is read.

| Step | Effect |
|---|---|
| `{"decode": "base64", "at": "$.rawData"}` | Replaces the base64 text at the path with the decoded UTF-8 text. |
| `{"parse": "xml", "at": "$.rawData"}` | Replaces the XML text at the path with JSON: element → object by child tag, attribute → `@name`, text → `#text` (or the bare string), repeated children → list. |

A document with a `DOCTYPE` or `ENTITY` is refused, as is one over 8 MiB. A response
the transform does not fit is a failed call.

## The ledger line

One `cost_entries` row per known cost, keyed on the tool call so a retried call is
the same line. `subject_id` is the connection, `subject_name` the tool, `payer`,
`quantity` and `unit`, `vendor_cost` in `vendor_currency`, and `amount` in
`currency`: the billing currency when a billing extension prices the line, otherwise
the vendor's currency. `amount` is what spend caps count and what the UI shows. A wallet payment is a line of its own with `payer = per_call`.

## Spend caps on tool cost

Monthly `cap` rules on `spend` count these lines like every other paid line. A rule
can be narrowed to one Registered Client, one connection, or one tool of a connection
with `client_id`, `connection_id` and `tool` in its params; see
[policy syntax](/reference/policy-syntax). A cap already reached refuses the call
before the vendor is called.

Nothing is converted. Without a billing extension a tool line keeps its vendor's
currency (a RUB-priced Yandex call is a RUB line), as an LLM line keeps the provider's
USD cost. A cap counts only lines in its own currency: the billing currency (USD
without a billing extension), or the `currency` in its params (`{"amount_usd": "300",
"currency": "RUB"}`; the amount is in that currency). Spend in a currency no cap
counts is never blocked; when the workspace has a monthly cap, the dashboard's spend
card lists the month's spend in every other currency under `not_covered`. With
a billing extension, every line is priced in the billing currency, so caps compare
one currency.

## On the platform's key

A `platform` connection lives in the platform workspace and every workspace may call
it; none can edit it. Its calls are governed by policy and caps, and a tool whose cost
is `unknown` or `settled` is refused, since nobody could be charged for it. When a
billing extension is installed it also checks the workspace balance before each call
and bills the vendor cost times the connector's markup. Without one, a self-hoster can
share one key with every workspace, limited by policy and caps alone.
