# Agent invocation access and messaging channels — design

**Date:** 2026-10-09
**Branch:** docs/agent-invocation-access
**Status:** draft for review (brainstorming output; not yet a plan)

## Problem

A Telegram bot attached to an agent answers anyone who finds it. Nothing on the
inbound path looks at the sender: the Go poller and the webhook parser carry
`from.id` into the event, no code reads it, and every run executes as
`trigger.created_by`.

That is one symptom of a wider gap. Five different things decide "may this
principal run this agent" today:

| Entry point | Who decides | Where |
|---|---|---|
| A2A JSON-RPC | `authorize_agent_action` (workspace scope; never reads the graph) | `apps/api/.../v1/a2a_auth.py:127` |
| REST task creation, `runs.start` toolset | nobody — `unrestricted` | `v1/agents_tasks.py:755,956,1045`, `tools/runs_toolset.py:113` |
| Stream-triggered runs | `ConfigurerAuthority.may_run` → FGA `resource#can_read` | `libs/triggers/.../stream_subscriber.py:84-101` |
| Cron, poller-inbound, IMAP triggers | nobody | `trigger_service.py:1435`, `channels/inbound_subscriber.py:207` |
| Agent-to-agent delegation | nobody | `agent_delegation_tool.py:101` |

Two related gaps:

- **Execute and read are the same bit.** In the graph, "execute" is the same
  bit as "read", and every workspace member inherits it through the root
  project.
- **A run has no identity of its own.** It executes "as" a user, who is at once
  the requester, the identity tools act as, and the governance subject.

Channels have gaps of their own:

- **Channels can only send strings.** Outbound delivery has no buttons.
- **Approvals are switched off for channels.** `resolve_interaction_capabilities`
  sets `allow_approvals=False` for every non-web origin.
- **Bot tokens are not exclusive.** One token can be attached to several
  triggers, and the last `setWebhook` silently disconnects the others.

## Goal

- Agent invocation governed like a cloud resource: IAM-style bindings on the
  agent, one PDP, every entry point asking it.
- Messaging channels as doors that only identify the caller.
- A run that acts as the agent, scoped by who asked.
- Both of these work: a team or customer bot per agent, and **one personal bot
  through which a person reaches every agent they may run, across
  workspaces**.

There are no deployments to preserve. This design replaces the current
mechanisms outright, with no compatibility path.

## Principles (zero trust)

- **Deny by default.** An agent nobody was granted is runnable by nobody.
- **Every right is an explicit, audited grant.** No role implies invocation:
  not `can_manage`, not workspace admin, not membership.
- **Every request is decided.** Each message, call and firing goes through the
  PDP, and nothing caches a past allow.
- **Fail closed.** A graph outage, an unknown sender or an unparseable subject
  is a deny.
- **The door does not grant.** A channel, A2A or the web UI identifies the
  caller. The agent's bindings decide.
- **Identity is proven by its owner.** Only the person can link an external
  account to their user, by proving control of it.

## Three separate decisions

| Decision | Question | Mechanism |
|---|---|---|
| Authentication | Who is this? | Session, API key, or a linked external identity (§4) |
| Admission | May they run this agent? | The PDP: `can_invoke` on the agent (§2) |
| Run scope | What may this run do? | The agent's run session, scoped at start (§3) |

A linked Telegram account answers only the first question. Admission does not
decide what a run may do; scoping does.

## Principals

| Type | What it is |
|---|---|
| `User` | A person (Kratos identity id). Telegram, Slack, and similar are ways we recognise them, not separate principals |
| `Agent` | An agent's workload identity, the service-account analogue. Runs act as it |

A run is **not** a principal. It is a session of the agent (§3), the way an AWS
assumed-role session belongs to a role, or a downscoped token belongs to a GCP
service account. Nothing is ever granted to a run.

## Design

### 1. Bindings

Agents are already graph objects, `resource:<agent_id>`. Invocation becomes
its own relation, independent of `reader`:

```fga
type resource
  relations
    ...
    define invoker: [User, Agent, Workspace#members]
    define can_invoke: invoker
```

- **Creating an agent** writes exactly `invoker@User:<creator>`, next to the
  ownership tuples (`WorkspaceScopedRepository._record_graph_ownership`), so it
  shares their rollback-on-failure.
- **Levels now:**
  - specific people (`User:<id>`);
  - specific agents (`Agent:<id>`);
  - workspace members (`Workspace:<ws>#members`).
- **Who may change bindings:** whoever has `can_manage` on the agent. They may
  grant invocation, including to themselves, and each grant is audited.
  Managing an agent does not by itself let them run it.
- **Seeing versus running:** these are separate bits, as with GCP's `viewer`
  and `run.invoker`.
- **`OpenFGAPermissionService`** maps `execute` to `can_invoke`
  (`auth/openfga_permission.py:17-31`).
- **These files change together:**
  - `model.fga`
  - `model.fga.yaml`
  - both copies of `authorization-model.json` (`config/auth/openfga/`,
    `charts/agentarea/files/openfga/`)

**For now, grants go only to workspace members.** The workspace-files toolset
is `unrestricted` ("member-level", `tools/workspace_files_toolset.py:78`), so
anyone who can run an agent can read the workspace's files. Granting a
non-member would leak them. Outside grants arrive once run scope covers
resources (§3).

**Later levels** follow GCP's special members and are gated by a workspace
constraint, the analogue of `iam.allowedPolicyMemberDomains`:

- `public` (`allUsers`);
- `authenticated` (`allAuthenticatedUsers`, meaning any account on this
  installation).

### 2. One PDP

```python
async def authorize_agent_invocation(user: UserPrincipal | UserContext, agent: AgentRef) -> Decision
```

It replaces `authorize_agent_action`. The order:

1. An agent-bound key → allowed on its own agent only.
2. FGA `check(resource:<agent>, can_invoke, User:<id>)`.
3. Deny. A graph error is a deny.

The decision names the matched grant, for audit and for the deny message.

Every entry point calls it, each with a single call:

- A2A;
- the three REST task-creation routes;
- `runs.start`;
- agent delegation, with the delegating agent as the subject;
- triggers, through `may_run`, which reaches it via `execute` → `can_invoke`.
  Cron goes through `may_run` too;
- every channel (§5).

### 3. Run session

A run acts as its agent, inside a session created once, at task creation:

```
run session (per task; not a principal)
  agent    the principal that acts
  caller   who asked: User + via (web | a2a | telegram | ...)
  scope    agent's capabilities ∩ caller's entitlements ∩ policy (tighten-only)
```

- **Scope is computed once** by `compute_run_scope(agent, caller)`. Today that
  is the governance snapshot, which is already resolved once per task across
  `workspace → agent → user → task` with the user layer as the caller layer.
  Later the agent's resources (MCP connections, secrets, collections) join it.
- **The runtime authorizes against the scope.** It does not use the caller's
  live context or session tokens, and it does not use the agent's whole
  configuration. No new code path may run "as the user".
- **The task records `caller` separately from ownership.** Audit reads "agent
  X, task T, at the request of Vasya".
- **Revocation.** On each step boundary, the run checks that the caller may
  still invoke the agent. A revoked grant or link stops the task.

**What exists and what is missing.** The governance snapshot already exists.
Activities still build a user context from the task owner
(`execution/.../activities/dependencies.py:189-217`), and the toolset's
`requires(...)` checks the owner's live graph rights. Moving these onto the
session is a later phase. Until then, the snapshot is the scope.

**Different people, different rights, same agent.** Each conversation is its
own task with its own caller, so each person gets:

- their own governance user layer: caps, denied tools, required approvals;
- their own `requires(...)` checks;
- their own audit trail.

What is still shared is the agent's MCP connections and secrets. Vasya and
Petya act with the same GitHub token; governance can deny Petya the
`github_*` tools. Per-person credentials need an on-behalf-of mode with
personal connections (the analogue of Graph delegated permissions), which is a
later phase.

### 4. Linked external identities

A link records **how we recognise a person in a channel**. It is application
data, kept in our database, not in the IdP:

- Kratos stores how a person logs in.
- Kratos cannot reverse-look-up arbitrary traits.
- With enterprise SSO, the IdP is the customer's, and we cannot write to it.

```
user_external_identities
  id, user_id          Kratos identity id
  provider             'telegram'
  external_id          from.id — never the username, which can change hands
  method               'pairing' (later: 'idp_sync', 'admin')
  linked_at, revoked_at
  unique (provider, external_id) where revoked_at is null
```

- **The table is user-scoped, not workspace-scoped.** This is a deliberate
  exception to the `WorkspaceScopedMixin` rule, following the
  `WorkspaceMembership` precedent: a link belongs to a person. Say so in the
  model's docstring.
- **Links and unlinks are audited.**
- **Resolution checks that the identity is still active in Kratos**, through
  `IdentityDirectory` with a short cache.

**Linking is proven, never typed.** A typed id proves nothing. If Vasya types
Petya's id, Petya's messages to any bot on the platform resolve to Vasya:

- Petya acts with Vasya's rights;
- Vasya reads what Petya sends.

The harm lands on third parties, not on Vasya.

The flow starts at a bot, so it needs no platform bot:

1. An unknown sender writes to a bot, and the bot replies with a link to
   `/link/telegram?via=<channel>`.
2. The person signs in and presses "Link". They get
   `t.me/<that bot>?start=link_<nonce>`. The nonce is single-use, kept in
   Redis with a 10-minute TTL, and stored hashed.
3. The bot shows a button: "Link this Telegram to a\*\*\*@mail.com?".
4. Pressing it writes the link.

The confirmation button prevents a login-CSRF variant, where someone sends you
a link carrying their nonce.

Any bot works, because a Telegram `from.id` is the same across bots.

Account settings list a person's links, with an unlink button for each.

### 5. Channels (doors)

A channel is one connected bot. It is a resource with an owner and two
settings:

```
channels
  id
  owner_kind, owner_id   'workspace' | 'user'
  provider               'telegram'
  bot token              encrypted, as secrets are
  routing                fixed agent_id | selectable
  admits                 'resolved_users' | 'owner_only'
  unique bot token per installation
```

| Kind | Owner | Routing | Admits | Use |
|---|---|---|---|---|
| Agent bot | workspace | fixed agent | resolved users (PDP decides) | a team or customer bot for one agent |
| Workspace bot | workspace | selectable among the workspace's agents | resolved users | one company bot for all its agents |
| **Personal bot** | user | selectable among **every agent the owner may invoke, in any workspace** | owner only | one bot to drive all your agents, projects and workspaces |

**One responsible party per door.** A channel's owner answers for the door. An
agent's workspace answers for the agent: it pays, keeps the audit, and decides
grants. A personal bot opens nothing new. It reaches exactly what its owner
can already run, and each message is still decided per agent.

**Per message**, for every kind:

1. Drop non-private chats (groups come later) and bot senders (`from.is_bot`).
2. Resolve the sender through §4. If `admits = owner_only`, the sender must be
   the owner; everyone else is ignored.
3. Pick the target agent:
   - a fixed agent;
   - otherwise the chat's current agent, chosen with `/agents`. That command
     lists, as buttons, the agents the sender may invoke, from FGA
     `list_objects(can_invoke)` filtered to the channel's reach. `/use`
     switches between them.
4. Run the PDP with `(sender, agent)`.
5. Create or continue the task in **the agent's workspace**, with
   `caller = sender, via = channel`, and compute the run scope.

Steps 1–5 are one function, `admit_channel_message`. Every intake calls it
before building any service:

- the webhook (`stream_subscriber`);
- the poller (`inbound_subscriber`);
- the personal-channel webhook.

**Threads** are keyed by `(channel, chat, caller, agent)`. Today the key is
`(workspace, agent, chat)`. With the channel in the key, DMs with two bots no
longer merge. In a personal bot, each agent has its own thread, and replies
are labelled "agent · workspace".

**Delivery guard.** `origin_guard` checks today that a trigger and its task
share a workspace. It becomes a check on whether the channel may receive this
task:

- a workspace channel: same workspace;
- a personal channel: the task's caller is the channel's owner.

Without the second rule, a task in someone else's workspace could post into
your bot.

**Denied senders.**

- In a DM, at most one reply per 24 hours:
  - an unlinked sender gets the link URL from §4;
  - a linked sender without access gets "You don't have access to this agent".
- A `skipped` execution is recorded with reason `caller_not_authorized`. The
  message text is not stored.
- Owner-only channels stay silent.

**Today's Telegram trigger becomes an agent bot.** The channel takes over the
bot token, its uniqueness and the webhook registration from
`_trigger_creation.py`. Trigger conditions remain a content filter and are
never used for access control.

### 6. Actions and approvals in the channel

A channel is also where a person learns that a run needs them, and where they
answer.

- **Structured outbound messages.** Outbound delivery stops being a bare
  string:
  ```
  OutboundMessage { text, actions: [Action{token, label, style}], edit_of? }
  ```
  An adapter that cannot render buttons renders text and an "open in web"
  link.
- **The action table.** It maps a single-use opaque token to
  `(kind, task_id, escalation_id, expires_at)`.
  - `kind` is `approval` | `continuation` | `input`; `approval` is the first.
  - `callback_data` carries only the token, because Telegram caps it at 64
    bytes and the button is not trusted.
- **Button presses.** `callback_query` joins `allowed_updates`
  (`channels/telegram.py:32` sets only `message` today). A press is routed to
  the action handler, never to a trigger. Today a press becomes chat text.
  The handler:
  1. resolves the token;
  2. resolves the presser through §4;
  3. runs the same path as `POST .../resolve-escalation` (task authority plus
     `caller_can_approve`);
  4. calls `answerCallbackQuery`;
  5. edits the message to "Approved by Vasya".

  An unlinked presser can never approve.
- **When approvals are offered.** `allow_approvals` becomes true when the
  channel renders actions **and** the caller is an identified user who may
  approve. Otherwise today's immediate deny stands.
- **What the request shows.** The `approval.request` formatter shows the tool
  name and the sanitized arguments; today it renders only "Approval needed".
  For sensitive tools it shows the tool name and a web link instead, so
  arguments do not leave for Telegram.
- **Personal bot as inbox.** A personal bot is the natural place for approval
  requests from any workspace. Notifying approvers other than the caller is a
  later phase.

## Plan of record

**Step 0 — close the open bot, with no throwaway code.** Every piece below is
part of the target design. It is only the subset needed so that a bot stops
answering strangers.

- **Admission reuses the check that exists.** `ConfigurerAuthority.may_run`
  (`stream_subscriber.py:91-100`) already answers "may this user run this
  agent": workspace membership plus `execute` in the graph. The channel calls
  it with the **sender**, as it already does for the trigger's creator. When
  step 1 makes `execute` mean `can_invoke`, the channel inherits the stricter
  rule with no change of its own.
- **One function, `admit_channel_sender(trigger, event) → caller | denial`**,
  runs before follow-up routing and before `fire`. It is called from:
  - the webhook path, in `TriggerSubscriptionHandler.handle`, before the
    follow-up claim;
  - the poller path, in `InboundMessageStreamConsumer._execute_trigger`.

  It applies these rules in order:
  1. **Not a private chat** (`chat_id != from.id`) or a bot sender
     (`raw_data.message.from.is_bot`) → skipped silently.
  2. **`from.id` has no link** (§4) → skipped, and the bot replies once per 24
     hours with the link URL.
  3. **`may_run(sender)` is false** → skipped, and the bot replies "no access".
  4. **Otherwise** the caller is the linked user.
- **The task runs for the caller, not the trigger's creator.**
  - `fire` gains `caller: str | None`, used for `AgentTask.user_id`.
    `fired_by` keeps its meaning of "a person pressed run now", which also
    bypasses `is_active`, so it is not reused.
  - The trigger service is rebuilt with the caller's `UserContext`, so the
    governance snapshot (the run scope today) and audit are the caller's.
  - The creator stays the trigger's owner and is still checked by `may_run` as
    today.
- **Linking, minimal (§4).**
  - The `user_external_identities` table and its migration.
  - `POST /v1/me/external-identities/telegram/link` mints a nonce in Redis
    (10 minutes, hashed) and returns `t.me/<bot>?start=link_<nonce>`. The bot's
    username is public, so it arrives in the link the bot sent and needs no
    lookup.
  - The intake handles `/start link_<nonce>` **before** admission. The bot
    asks "Link this Telegram to a\*\*\*@mail.com? Send /confirm", and
    `/confirm` writes the link. A text confirmation avoids `callback_query`
    until step 4 adds buttons.
  - `GET` / `DELETE /v1/me/external-identities` list and unlink.
  - The webapp gets one page, `/link/telegram?bot=<username>`, and one section
    in account settings.
- **Follow-up routing** gains `trigger_id` in its key, so DMs to two bots of
  the same agent stay apart.

Not in step 0: the `invoker` relation, the Access tab, channels as their own
entity, the personal bot, and buttons. Members of the agent's workspace who
link Telegram can use the bot; nobody else can.

**MVP.** After these four steps a person can attach a bot to an agent and share
it with colleagues, or attach a personal bot and reach all their agents.

1. **PDP.** `invoker` / `can_invoke`; the creator binding; the PDP; every entry
   point in §2; `execute` → `can_invoke`; the Access tab on the agent (people,
   agents, workspace members); grants restricted to members.
2. **Links and channels.**
   - `user_external_identities` and the pairing flow, which brings
     `callback_query` and a small action handler;
   - the `channels` entity, replacing the Telegram trigger;
   - token uniqueness;
   - `admit_channel_message`;
   - the thread key, the delivery guard and the deny replies.
3. **Personal bot.** `owner_kind = user`, `/agents` and `/use`, routing across
   workspaces, labelled replies.
4. **Approvals in the channel.** `OutboundMessage`, the action table, approve
   and deny buttons, `allow_approvals` for identified callers.

The run session lands with step 1 as naming and data: `caller` on the task,
and `compute_run_scope` wrapping the governance snapshot.

**Next.**

- Activities authorize against the run session instead of the owner's context.
- Resources join the run scope.
- Non-member grants.
- Revocation on each step.
- `continuation` and `input` actions.
- Notifying other approvers.
- Approval expiry: approvals wait forever today.

**Later.**

- `public` / `authenticated` and the workspace constraint.
- External accounts as principals (`telegram:<id>` granted directly, for people
  without an account), and pairing-based grants in the style of Hermes.
- Group chats.
- Admin-assigned links scoped to a workspace.
- On-behalf-of mode with personal connections.
- A platform bot for notifications.
- Slack, Discord and email.
- Corporate channels linked automatically from the IdP.

## Open questions

1. **`/agents` scope in a workspace bot.** Every agent of the workspace the
   sender may invoke (proposed), or an explicit list on the channel?
2. **Approvals in a personal bot for tasks started elsewhere.** If Vasya
   starts a task in the web and it needs his approval, should the request also
   reach his personal bot? Proposed: yes, as the first notification, since the
   caller is the bot's owner.
3. **Encrypted token storage for user-owned channels.** Should there be a
   user-scoped secret store, or should the channel row keep the ciphertext
   (proposed for now)?

## Related

- `docs/reference/authorization-model.md`: the enforcement table. It is
  rewritten with step 1.
- `docs/concepts/governance/policy-engine.md`: the governance PDP, which
  decides what a run may do. Its user layer is this design's caller layer.
- `docs/concepts/governance/approvals.md`: the escalation machinery that §6
  puts a button on.
- `docs/superpowers/plans/2026-09-21-authorization-gate-baseline.md`: the
  authorization gate ratchet. The REST routes leaving `unrestricted` count
  against it.
