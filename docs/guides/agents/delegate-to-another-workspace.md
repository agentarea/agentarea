---
title: Delegate to an agent in another workspace
type: guide
description: "Let an agent hand tasks to an agent in a different workspace, or on another A2A server, through an A2A delegate."
prerequisites:
  - /concepts/agents/a2a
  - /guides/agents/create-and-configure
related:
  - /concepts/agents/a2a
  - /guides/mcp/issue-access-tokens
  - /guides/agents/create-and-configure
last_updated: 2026-09-30
---

An agent delegates to an agent in another workspace over A2A: the target's A2A
endpoint, and an API key from the target's workspace kept as a secret in the
caller's workspace. The same steps reach any A2A v1.0 server, not only
AgentArea.

The example below lets `personal-assistant` in the `personal` workspace hand
documentation work to `docs-writer` in the `aadocs` workspace.

## Prerequisites

<Info>
- Both agents exist, and you are a member of both workspaces.
- You administer the calling workspace. Pointing a secret at a URL sends the
  secret there, so only an admin may add or change that binding.
- The id of the target agent (`docs-writer`). It is the last segment of the
  agent's URL in the web app.
- The public API host of your deployment, the one that serves `/v1/...`.
</Info>

## Steps

<Steps titleSize="h3">
  <Step title="Create an API key in the target workspace">
    In `aadocs`, open **Settings → API keys** and create a key, or:

    ```bash
    curl -X POST https://$API_HOST/v1/workspaces/aadocs/api-keys/ \
      -H "Authorization: Bearer $TOKEN" \
      -H "Content-Type: application/json" \
      -d '{"name": "personal-delegation"}'
    ```

    Copy `token` from the response into `AADOCS_KEY`; it is shown once. The key
    acts as you, so a delegated task in `aadocs` is started by you and is allowed
    because you are a member of `aadocs`.
  </Step>

  <Step title="Store the key as a secret in the calling workspace">
    In `personal`, open **Secrets** and create a secret named `aadocs-key` with
    the key as its value, or:

    ```bash
    curl -X POST https://$API_HOST/v1/workspaces/personal/secrets \
      -H "Authorization: Bearer $TOKEN" \
      -H "Content-Type: application/json" \
      -d "{\"name\": \"aadocs-key\", \"value\": \"$AADOCS_KEY\", \"description\": \"Delegation to aadocs\"}"
    ```

    The agent keeps only the secret's name. The value is read when the agent
    delegates, so rotating the key means updating this secret, not the agent.
  </Step>

  <Step title="Add the delegate to the calling agent">
    Open `personal-assistant` → **Settings** → **Delegation** → **Agent**, and
    fill in **External agent (A2A)**:

    | Field | Value |
    |---|---|
    | Name | `docs-writer` — the model sees the tool `delegate_to_docs_writer` |
    | A2A endpoint URL | `https://$API_HOST/v1/agents/<docs-writer-id>/a2a/rpc` |
    | Token | `aadocs-key` |
    | When to delegate | What this agent should hand over, and when |

    Select **Add external agent**, then **Save changes**. Through the API, the
    same delegate is one entry in the agent's `tools`; the update replaces the
    whole list, so send every tool the agent should keep:

    ```json
    {
      "type": "agent",
      "name": "docs-writer",
      "settings": {
        "a2a_url": "https://api.example.com/v1/agents/78c3874a-e9b9-42dd-ad07-574086ca7034/a2a/rpc",
        "auth_secret_name": "aadocs-key",
        "description_override": "Hand over any request to write documentation."
      }
    }
    ```
  </Step>
</Steps>

## Verify

Start a task on `personal-assistant` that needs the delegate, for example "Write
a one-sentence doc for add(a, b) and delegate it to docs-writer". The task's
activity shows a `delegate_to_docs_writer` call, and a new task for
`docs-writer` appears in the `aadocs` workspace, started by you.

## Troubleshooting

<AccordionGroup>
  <Accordion title="The call fails with HTTP 401">
    No token reached the target. Check that **Token** names a secret, and that
    the secret holds a key from the target workspace that has not been revoked.
  </Accordion>
  <Accordion title="The call fails with HTTP 403">
    The key's owner is not a member of the target agent's workspace. The key
    must come from a user who can run tasks there.
  </Accordion>
  <Accordion title="Saving fails: only a workspace admin may send a workspace secret">
    Adding a delegate with a **Token**, or changing its URL or token, needs a
    workspace admin in the calling workspace. Ask one to add the delegate.
  </Accordion>
  <Accordion title="Saving fails with invalid_delegate">
    The detail names the delegate and the problem: a secret that does not exist
    or is managed by a connection, a URL that is not http(s), or two delegates
    whose names become the same tool name.
  </Accordion>
  <Accordion title="The call fails naming a secret that was not found">
    The secret was renamed or deleted after the delegate was added. Recreate it
    under the same name, or pick another one on the delegate.
  </Accordion>
  <Accordion title="The error says the host resolves to a non-public address">
    The outbound guard refused the URL. Use the public API host. A self-hosted
    deployment that must reach an internal host names it in
    `OUTBOUND_PRIVATE_ALLOWLIST` on the worker.
  </Accordion>
  <Accordion title="The delegate reports it is still working">
    The target did not finish within the 110-second A2A delegation budget. The
    task keeps running in the target workspace; its result does not come back
    to the caller.
  </Accordion>
</AccordionGroup>

## Related

<Columns cols={2}>
  <Card title="Agent-to-agent communication" icon="lightbulb" href="/concepts/agents/a2a">
    Delegation, the A2A binding, and its limits
  </Card>
  <Card title="Issue access tokens" icon="plug" href="/guides/mcp/issue-access-tokens">
    Create, scope, rotate, and revoke API keys
  </Card>
  <Card title="Create and configure an agent" icon="robot" href="/guides/agents/create-and-configure">
    Create an agent and give it a model, instructions and tools
  </Card>
</Columns>
