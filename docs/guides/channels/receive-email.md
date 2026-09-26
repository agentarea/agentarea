---
title: Let an agent receive email
type: guide
summary: Give an agent an address of its own, or connect a mailbox you already have, so incoming mail starts a task and the agent's answer lands in the same thread.
prerequisites:
  - /concepts/execution/tasks
related:
  - /concepts/open-core
  - /guides/tasks/start-a-task
last_updated: 2026-09-16
---

# Let an agent receive email

Do this when an agent should act on mail somebody sends: a bug report, an
alert, a customer question. Two shapes, and they meet in the same place.

**An address of its own.** Mail addressed to the agent is delivered by an
inbound-parse provider, which POSTs the parsed message to a webhook.

**A mailbox you already have.** AgentArea polls it over IMAP, read-only, and
reacts to what arrives.

Either way the message becomes a task, and the agent's reply goes back into the
same mail thread — recipients see a conversation, not a stream of unrelated
notifications.

## What this platform does and does not run

AgentArea does not accept SMTP. There is no MX record, no mail server, and no
address namespace in this repository. What it has is everything after a message
exists: parsing, routing to an agent, threading, and the reply.

That line is deliberate. Handing out `something@your-domain` means running a
domain's deliverability, quotas, and abuse handling, which only makes sense for
whoever operates that domain. AgentArea's hosted offering allocates addresses
that way; a self-hosted install points an inbound-parse provider (or its own
mail server) at the webhook below and owns its own namespace. See
[Open core](/concepts/open-core) for how that seam is wired.

## Give an agent an address

### 1. Create the trigger

`webhook_type: "email"` tells the webhook to read the body as a message. The
`field_map` says which JSON keys your provider uses — every provider names them
differently, so this is configuration rather than a per-vendor integration.

```bash
curl -s -X POST "$AGENTAREA_URL/v1/workspaces/$WORKSPACE/triggers/" \
  -H "Authorization: Bearer $AGENTAREA_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Support inbox",
    "agent_id": "'"$AGENT_ID"'",
    "trigger_type": "webhook",
    "webhook_type": "email",
    "webhook_config": {
      "field_map": {
        "from": "FromFull.Email",
        "to": "ToFull[].Email",
        "subject": "Subject",
        "text": "TextBody",
        "html": "HtmlBody",
        "message_id": "MessageID",
        "in_reply_to": "Headers.In-Reply-To",
        "references": "Headers.References"
      }
    },
    "channel_credentials": {
      "smtp_host": "smtp.example.com",
      "smtp_port": 587,
      "username": "apikey",
      "password": "...",
      "from_address": "agent@your-domain.example",
      "use_tls": true
    }
  }'
```

The response carries `webhook_id`. The endpoint is
`POST /webhooks/{webhook_id}` — unlike the rest of the API it is not
workspace-scoped in the path; the trigger row it targets carries its own
workspace.

A path segment is not a secret. Set `validation_rules.signing_secret` to the
secret your provider signs with, and the request is rejected unless the HMAC
over the raw bytes matches. Providers disagree on the header and encoding, so
`signature_header`, `signature_algorithm` and `signature_prefix` are
configurable alongside it:

```json
"validation_rules": {
  "signing_secret": "...",
  "signature_header": "x-provider-signature",
  "signature_prefix": "sha256="
}
```

`channel_credentials` are the SMTP settings for the **reply**, stored encrypted
under `channel_cred:email:{trigger_id}`. Without them the agent can read mail
but not answer.

### 2. Point the address at the webhook

In your provider, route the agent's address to that URL. The URL is what
identifies the agent — one address, one trigger, no ambiguity about who the mail
was for.

Field paths support nesting (`FromFull.Email`) and lists
(`ToFull[].Email`, which keeps every recipient in `to_all` and uses the first as
`to`).

## Connect a mailbox you already have

Polling is a cron trigger with the `imap` extractor. The credential goes to the
secret store, never into the trigger's config column.

```bash
curl -s -X POST "$AGENTAREA_URL/v1/workspaces/$WORKSPACE/triggers/" \
  -H "Authorization: Bearer $AGENTAREA_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "My inbox",
    "agent_id": "'"$AGENT_ID"'",
    "trigger_type": "cron",
    "cron_expression": "*/2 * * * *",
    "data_extractor": "imap",
    "data_extractor_config": {
      "host": "imap.example.com",
      "port": 993,
      "use_ssl": true,
      "mailbox": "INBOX"
    },
    "channel_credentials": {
      "username": "me@example.com",
      "password": "...",
      "smtp_host": "smtp.example.com",
      "smtp_port": 587,
      "from_address": "me@example.com",
      "use_tls": true
    }
  }'
```

One credential blob covers both directions: IMAP to read, SMTP to reply. For
Gmail and similar, that is an app password, not the account password.

Two behaviours worth knowing before you point it at a real mailbox:

- **Your mail is not touched.** The mailbox is opened read-only and progress is
  tracked by UID, so nothing is marked as read behind your back.
- **History is not replayed.** The first poll records where the mailbox is and
  emits nothing. Only mail arriving afterwards reaches the agent.

## How the reply threads

Each inbound message carries a thread key — the root of its `References`
header, falling back to `In-Reply-To`, then to its own `Message-ID`. Every
message in one conversation therefore resolves to the same key.

That key is the conversation identity. When mail arrives for a thread whose task
is still running, it is routed into that task rather than starting a new one, so
the agent answers with the conversation in hand. The outgoing reply carries
`In-Reply-To` and the full `References` chain, which is what makes mail clients
show it as a reply.

## Try it locally

The dev stack bundles [mailpit](http://localhost:8025), which can POST every new
message to a webhook. No provider account, no public DNS:

```yaml
# docker-compose override
services:
  mailpit:
    environment:
      MP_WEBHOOK_URL: http://app:8000/webhooks/YOUR_WEBHOOK_ID
```

mailpit's payload maps with:

```json
{
  "from": "From.Address",
  "to": "To[].Address",
  "subject": "Subject",
  "text": "Snippet",
  "message_id": "MessageID"
}
```

Send anything to `mailpit:1025` from inside the compose network and watch the
task appear. Note that mailpit's webhook carries a **snippet**, not the full
body — it is a development mail catcher, and real inbound-parse providers post
the whole message.

## Limits

- **One message per poll.** A trigger execution becomes one task with one reply
  address, so an IMAP poll emits the oldest unread message and reports the rest
  as `pending` in its state; they drain on following ticks. Match the cron
  interval to the volume you expect.
- **`webhook_type: "gmail"` is a different thing.** Gmail's Pub/Sub push
  notifies you that *something* changed and carries no message, so an agent
  cannot read the mail from it. Use `imap` against Gmail instead.
- **Attachments are not extracted.** The message text reaches the agent;
  attachments stay in the raw payload.
