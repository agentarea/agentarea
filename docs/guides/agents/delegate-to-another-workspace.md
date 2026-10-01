---
title: Delegate to an agent in another workspace
type: guide
description: "Let an agent hand tasks to an agent in a different workspace, owned by anyone, or on another A2A server, through an A2A delegate and a key bound to that agent."
prerequisites:
  - /concepts/agents/a2a
  - /guides/agents/create-and-configure
related:
  - /concepts/agents/a2a
  - /guides/mcp/issue-access-tokens
  - /guides/agents/create-and-configure
last_updated: 2026-10-01
---

An agent delegates to an agent in another workspace over A2A: the target's
address, and a key bound to the target agent kept as a secret in the caller's
workspace. The two workspaces may belong to different people. The same steps
reach any A2A v1.0 agent, not only one on AgentArea.

The example below lets `personal-assistant` in the `personal` workspace hand
documentation work to `docs-writer` in the `aadocs` workspace.

## Prerequisites

<Info>
- Someone who is a member of `aadocs` issues the key. It acts as them, so a
  delegated task in `aadocs` is started by them.
- You administer the calling workspace. Pointing a secret at an address sends
  the secret there, so only an admin may add or change that binding.
</Info>

## Steps

<Steps titleSize="h3">
  <Step title="Issue a key for the target agent">
    In `aadocs`, open `docs-writer` → **Settings** → **A2A access**. Copy the
    agent's **Address**, then select **Issue key**, name it after the caller,
    for example `personal`, and copy the key; it is shown once. Or:

    ```bash
    curl -X POST https://$API_HOST/v1/workspaces/aadocs/api-keys/ \
      -H "Authorization: Bearer $TOKEN" \
      -H "Content-Type: application/json" \
      -d '{"name": "personal", "agent_id": "<docs-writer-id>"}'
    ```

    The key reaches `docs-writer` over A2A and nothing else: no other agent, no
    data in `aadocs`, no REST route. Revoke it in the same section to cut the
    caller off.
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
    | Agent address | The address copied in the first step. Reading the card fills in the name and description. |
    | Name | `docs-writer` — the model sees the tool `delegate_to_docs_writer` |
    | Token | `aadocs-key` |
    | When to delegate | What this agent should hand over, and when |

    Select **Add external agent**, then **Save changes**. Through the API, the
    same delegate is one entry in the agent's `tools`; the update replaces the
    whole list, so send every tool the agent should keep:

    ```jsonc
    {
      "type": "agent",
      "name": "docs-writer",
      "settings": {
        "a2a_url": "https://78c3874a-e9b9-42dd-ad07-574086ca7034.a2a.example.com",
        "auth_secret_name": "aadocs-key", // pragma: allowlist secret
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
`docs-writer` appears in the `aadocs` workspace, started by whoever issued the
key.

## Troubleshooting

<AccordionGroup>
  <Accordion title="Reading the card fails, or the call fails naming the agent card">
    Nothing at the address serves `/.well-known/agent-card.json`. Use the
    address from **A2A access**, not the JSON-RPC URL. For another A2A server,
    use the origin or base URL its card is published under.
  </Accordion>
  <Accordion title="The call fails with HTTP 401">
    No valid key reached the target. Check that **Token** names a secret, and
    that the secret holds a key that has not been revoked and whose issuer is
    still a member of the target workspace.
  </Accordion>
  <Accordion title="The call fails with HTTP 403">
    The key is bound to a different agent, or it is a key for another
    workspace. Issue one from the target agent's **A2A access**.
  </Accordion>
  <Accordion title="The call fails: the card names no endpoint on the address">
    The remote card points its endpoint at another host. The token is sent only
    to the address you configured, so the delegate refuses. Configure the host
    the card names as the address instead.
  </Accordion>
  <Accordion title="Saving fails: only a workspace admin may send a workspace secret">
    Adding a delegate with a **Token**, or changing its address or token, needs
    a workspace admin in the calling workspace. Ask one to add the delegate.
  </Accordion>
  <Accordion title="Saving fails with invalid_delegate">
    The detail names the delegate and the problem: a secret that does not exist
    or is managed by a connection, an address that is not http(s), or two
    delegates whose names become the same tool name.
  </Accordion>
  <Accordion title="The call fails naming a secret that was not found">
    The secret was renamed or deleted after the delegate was added. Recreate it
    under the same name, or pick another one on the delegate.
  </Accordion>
  <Accordion title="The error says the host resolves to a non-public address">
    The outbound guard refused the address. Use the public one. A self-hosted
    deployment that must reach an internal host names it in
    `OUTBOUND_PRIVATE_ALLOWLIST` on the worker and the API.
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
