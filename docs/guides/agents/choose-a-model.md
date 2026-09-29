---
title: Choose a model for an agent
type: guide
description: "Configure a provider, create a model instance, and point an agent at it."
prerequisites: []
related:
  - /guides/agents/create-and-configure
  - /concepts/agents/context-strategies
  - /guides/governance/set-a-budget
  - /reference/limits
last_updated: 2026-09-07
---

Models are described by four objects, in two layers. Getting the layering right
is most of the work; after that, pointing an agent at a model is one field.

| Object | Layer | What it is |
|---|---|---|
| `provider-specs` | catalog | A provider that exists in the world — OpenAI, Anthropic |
| `model-specs` | catalog | A model that provider offers, with its context window and per-token costs |
| `provider-configs` | your workspace | Your credential and endpoint for a provider |
| `model-instances` | your workspace | A usable model: one provider config plus one model spec |

An agent's `model_id` is a **model instance** id. That indirection is the point:
you can repoint an instance at a different provider config — a different key, a
different endpoint, a proxy — without touching any agent.

## Prerequisites

<Info>
- An access token.
- An API key for the provider you intend to use.
</Info>

## Steps

<Steps titleSize="h3">
  <Step title="Find the provider spec">
    ```bash
    curl -s http://localhost:8000/v1/workspaces/{workspace}/provider-specs/with-models \
      -H "Authorization: Bearer $TOKEN"
    ```

    This returns providers together with the model specs each one offers, which is
    usually all you need to pick both ids in one call.
  </Step>

  <Step title="Create a provider config">
    This is where your credential lives. Store the key as a secret rather than
    inline where your deployment supports it — see
    [pass secrets](/guides/mcp/pass-secrets) for the same pattern applied to MCP.

    ```bash
    curl -X POST http://localhost:8000/v1/workspaces/{workspace}/provider-configs/ \
      -H "Authorization: Bearer $TOKEN" \
      -H "Content-Type: application/json" \
      -d '{
        "provider_spec_id": "<provider-spec-id>",
        "name": "OpenAI (team key)",
        "api_key": "<your-api-key>"
      }'
    ```

    `provider_spec_id` and `name` are the only required fields. `endpoint_url` points
    at a compatible proxy or self-hosted gateway. Prefer `api_key_secret_id`, a
    reference to a stored secret, over an inline `api_key`.
  </Step>

  <Step title="Create a model instance">
    ```bash
    curl -X POST http://localhost:8000/v1/workspaces/{workspace}/model-instances/ \
      -H "Authorization: Bearer $TOKEN" \
      -H "Content-Type: application/json" \
      -d '{
        "provider_config_id": "<provider-config-id>",
        "model_spec_id": "<model-spec-id>",
        "name": "gpt-4o (team)"
      }'
    ```
  </Step>

  <Step title="Point the agent at it">
    Set `model_id` on the agent to the instance id — at creation, or with a `PATCH`
    later. See [create and configure an agent](/guides/agents/create-and-configure).
  </Step>
</Steps>

## Verify

```bash
curl -X POST http://localhost:8000/v1/workspaces/{workspace}/model-instances/test \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "provider_config_id": "<provider-config-id>",
    "model_spec_id": "<model-spec-id>",
    "test_message": "ping"
  }'
```

The test takes the config and spec ids rather than an instance id, so you can
check a pairing before you create an instance for it.

A failure here is a credential or endpoint problem, and it is much easier to
read than the same failure surfacing mid-task.

## What the model spec controls at runtime

Two fields do more than describe:

- **`context_window`** seeds context management and compaction. It has no
  default — a task whose model declares no positive window fails at startup with
  `InvalidExecutionSnapshot` rather than running against a guess.
- **`default_context_strategy`** sets the per-model default of `static`,
  `hybrid` or `dynamic`, which an agent may override.

Per-token costs drive budget accounting. Every paid call is metered, including
context compaction, and a call that returns no token usage is an error rather
than a free call.

## Troubleshooting

**The agent runs but always uses the wrong model.** Check the agent's `model_id`
rather than the provider config — several instances can share one config.

**Changing a provider key did not take effect.** The workflow resolves the model
once at task start and caches it for the run. In-flight tasks keep the old
resolution; new tasks pick up the change. A running task can be moved with the
`change_model` command.

## Related

<Columns cols={2}>
  <Card title="Create and configure an agent" icon="robot" href="/guides/agents/create-and-configure">
    Create an agent, bind it to a model instance, and give it instructions and
    tools
  </Card>
  <Card title="Context strategies" icon="robot" href="/concepts/agents/context-strategies">
    Three settings — static, hybrid and dynamic — decide whether large tool
    outputs are offloaded to
  </Card>
  <Card title="Set a budget" icon="scale-balanced" href="/guides/governance/set-a-budget">
    Cap monthly spend, per-run spend, service spend or tokens for a workspace,
    agent, user or single
  </Card>
</Columns>
