---
title: Subscribe to a stream over MCP Events
type: guide
description: "Read a stream from outside AgentArea with the MCP Events extension: poll it with a cursor, or have signed events POSTed to your HTTPS endpoint."
prerequisites:
  - /concepts/integration/event-streams
related:
  - /concepts/integration/event-streams
  - /guides/triggers/collect-events-into-a-stream
  - /guides/mcp/issue-access-tokens
  - /concepts/integration/mcp
last_updated: 2026-10-19
---

The AgentArea MCP server is also an MCP Events server. Every stream you can
read is an event type on it, so an MCP client outside the platform (your own
service, a gateway, an assistant that speaks MCP Events) can follow what
arrives in a stream without an agent run. Use it when something outside
AgentArea must react to stream events. When an agent should react, attach a
[trigger](/guides/triggers/trigger-from-a-webhook) instead.

The server implements the MCP Events extension, `io.modelcontextprotocol/events`
(SEP-3415, the draft of 2026-10-16 for protocol 2026-07-28), with two delivery
modes: **poll** (`events/poll`) and **webhook** (`events/subscribe`). There is no
push mode (`events/stream`): the MCP endpoints are stateless.

<Info>
**Prerequisites**

- A stream with events in it: see [Collect events into a stream](/guides/triggers/collect-events-into-a-stream).
- A bearer token for a member of the stream's workspace. A token of a
  non-member is refused.
- For webhook delivery, an endpoint reachable at an `https://` URL that can
  verify [Standard Webhooks](https://www.standardwebhooks.com/) signatures.
</Info>

## Which endpoint

All three MCP endpoints serve the same methods. An event type is named
`<workspace slug>/<stream id>` on every one of them.

| Endpoint | Lists the streams of |
|---|---|
| `/mcp/w/{workspace}` | that workspace |
| `/mcp` | every workspace you belong to |
| `/mcp/clients/{client_id}` | the client's workspace |

`initialize` (and `server/discover` on 2026-07-28) reports the extension as
`capabilities.extensions["io.modelcontextprotocol/events"]`, and also as the
top-level `capabilities.events` that clients written against the pre-SEP sketch
read.

## Steps

<Steps titleSize="h3">
<Step title="List the event types">

```bash
curl -s https://api.agentarea.ai/mcp/w/acme \
  -H "Authorization: Bearer $TOKEN" \
  -H "Accept: application/json, text/event-stream" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"events/list"}'
```

Each entry is one stream you may read:

```json
{
  "name": "acme/2dfaff89-bdd7-4b76-9688-1e869e95bc39",
  "title": "Demo orders",
  "description": "Order events from a shop, via a generic webhook",
  "delivery": ["poll", "webhook"],
  "inputSchema": {"type": "object", "properties": {"kind": {}, "source_type": {}, "session_key": {}}},
  "payloadSchema": {"title": "EventEnvelope", "type": "object"}
}
```

`inputSchema` lists the arguments that narrow a subscription; all are optional.

| Argument | Keeps |
|---|---|
| `kind` | events of this kind or a kind under it: `order` keeps `order.paid` |
| `source_type` | events a source of this catalog entry brought, such as `github` |
| `session_key` | events of one session: one chat, one thread |

`payloadSchema` is the event envelope every subscriber receives as `data`:
`id`, `kind`, `key`, `source_type`, `session_key`, `sender`, `received_at`,
`occurred_at`, `correlation_id`, `causation_id`, `data` (the headers without
credentials, and the body as sent) and `attachments`.

</Step>
<Step title="Poll">

Start with `cursor: null`. It returns no events and a cursor for "now".

```bash
curl -s https://api.agentarea.ai/mcp/w/acme \
  -H "Authorization: Bearer $TOKEN" \
  -H "Accept: application/json, text/event-stream" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":2,"method":"events/poll","params":{
        "name":"acme/2dfaff89-bdd7-4b76-9688-1e869e95bc39",
        "arguments":{"kind":"order"},"cursor":null}}'
```

```json
{"events": [], "cursor": "djE6MTc5MjQxMTkwMTQ5NzozMTY5", "truncated": false, "hasMore": false, "nextPollMs": 10000}
```

Pass the cursor back on the next poll; every response carries the next one,
also when nothing arrived. Each event is `{eventId, name, timestamp, data}`.
When `hasMore` is true, poll again at once; otherwise wait `nextPollMs`.
`maxEvents` caps a page (default 50, at most 500). `maxAgeMs` skips events older
than that many milliseconds.

</Step>
<Step title="Or subscribe a webhook">

Generate the secret yourself: `whsec_` followed by the base64 of 24 to 64
random bytes. The server never makes one for you.

```bash
WHSEC="whsec_$(openssl rand -base64 32)"
curl -s https://api.agentarea.ai/mcp/w/acme \
  -H "Authorization: Bearer $TOKEN" \
  -H "Accept: application/json, text/event-stream" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":3,"method":"events/subscribe","params":{
        "name":"acme/2dfaff89-bdd7-4b76-9688-1e869e95bc39",
        "arguments":{"kind":"order"},
        "delivery":{"mode":"webhook","url":"https://hooks.example.com/agentarea","secret":"'"$WHSEC"'"},
        "cursor":null,"ttlMs":3600000}}'
```

Before it answers, the server POSTs a signed
`{"type":"verification","challenge":"<nonce>"}` to your URL. Your endpoint
checks the signature and answers `200` with `{"challenge":"<nonce>"}`. Then:

```json
{"id": "sub_7b16c9a8cec7989cb0cd16f3faaab04d", "refreshBefore": "2026-10-19T13:21:58Z", "cursor": null, "truncated": false}
```

Each matching event is then POSTed with the headers `webhook-id` (the event
id), `webhook-timestamp`, `webhook-signature` (`v1,` and the base64
HMAC-SHA256 of `webhook-id.webhook-timestamp.body` under your secret) and
`X-MCP-Subscription-Id`. Verify the signature over the raw body, reject a
timestamp older than five minutes, and deduplicate on `eventId`.

Call `events/subscribe` again with the same name, arguments and URL before
`refreshBefore`. The same call rotates the secret and reactivates a subscription
whose deliveries failed. To stop, call `events/unsubscribe` with
`{name, arguments, delivery: {url}}`.

</Step>
</Steps>

## Verify

- `events/poll` with the cursor from the previous answer returns the event you
  just sent to the stream, and the cursor changes.
- Your endpoint logs one POST per event whose signature verifies, with the
  `X-MCP-Subscription-Id` that `events/subscribe` returned.
- The refresh answer's `deliveryStatus` shows `lastDeliveryAt` and no
  `lastError`.

## Limits

- A subscription lasts at most 24 hours without a refresh (at least one
  minute; one hour when you send no `ttlMs`). `ttlMs: null`, no expiry, is
  answered with the 24-hour grant.
- A webhook subscription starts at the end of the stream. A `cursor` you pass to
  `events/subscribe` is not replayed (`truncated: true`); read the backlog with
  `events/poll`. Webhook deliveries carry `cursor: null`.
- A failed delivery is retried after 30 s, 2 min, 10 min, 30 min, 1 h and 2 h,
  each attempt with a fresh timestamp and signature. After the last one the
  subscription is marked failed and receives nothing until you refresh it. A
  `410` or `413` answer is final for that event.
- Delivery is at least once and may arrive out of order; use `eventId` and
  `timestamp`.
- Polling reads the last 7 days of the stream (`AGENTAREA_EVENT_RETENTION`). A
  cursor older than that comes back with `truncated: true`.
- A workspace holds at most 100 webhook subscriptions.
- Deliveries leave through the outbound policy for member-set addresses: no
  redirects, every address resolved and vetted before connecting. A callback
  that resolves to a private address is refused unless the deployment allows
  it in `AGENTAREA_HTTP_PRIVATE_ALLOWLIST`; only such an allowed private host may
  use `http://`, for a receiver in development.

## Troubleshooting

<AccordionGroup>
<Accordion title="events/subscribe fails with -32027 CallbackEndpointError">
`data.reason` names the failure: `challenge_failed` when the endpoint answered
without echoing the challenge, `connection_refused`, `timeout` or `tls_error`
when it could not be reached, `http_4xx` or `http_5xx` for its status. The
endpoint must verify the signature with the secret you just sent and answer
before the 10 s timeout.
</Accordion>
<Accordion title="events/subscribe fails with -32602 for the URL">
The URL is not `https://`. Only a private host listed in
`AGENTAREA_HTTP_PRIVATE_ALLOWLIST` (or any private host with
`AGENTAREA_HTTP_ALLOW_PRIVATE=true`) may use `http://`.
</Accordion>
<Accordion title="-32024 Forbidden or a 403 response">
The token's user is not a member of the workspace, or may not read the stream.
On `/mcp/w/{workspace}` a non-member is refused with HTTP 403 before any method
runs.
</Accordion>
</AccordionGroup>

## Related

<Columns cols={2}>
  <Card title="Event streams" icon="water" href="/concepts/integration/event-streams">Sources, streams and who reads them</Card>
  <Card title="Collect events into a stream" icon="inbox" href="/guides/triggers/collect-events-into-a-stream">Point a webhook at a stream</Card>
  <Card title="Issue access tokens" icon="key" href="/guides/mcp/issue-access-tokens">Tokens for the MCP endpoints</Card>
  <Card title="MCP on AgentArea" icon="plug" href="/concepts/integration/mcp">How the platform serves and consumes MCP</Card>
</Columns>
