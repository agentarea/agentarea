# Agent invocation access — design

**Date:** 2026-10-09
**Branch:** claude/adoring-shannon-2na8q5
**Status:** draft for review (brainstorming output; not yet a plan)

## Problem

A Telegram bot attached to an agent answers anyone who finds it. Nothing on the
inbound path looks at the sender: the Go poller and the Telegram webhook parser
carry `from.id` into the event and no code reads it, and every run executes as
`trigger.created_by`. The only lever is a trigger condition, and on the poller
path a `rule` condition cannot even reach `events[0].user_id` because
`value_at` does not index lists.

That is one symptom of a wider gap: there is no single answer to "may this
principal run this agent". Today five different things decide it:

| Entry point | Who decides | Where |
|---|---|---|
| A2A JSON-RPC | `authorize_agent_action` (workspace scope, never reads the graph) | `apps/api/.../v1/a2a_auth.py:127` |
| REST task creation, `runs.start` toolset | Nobody — `unrestricted`; the workspace-scoped repository is the boundary | `v1/agents_tasks.py:755,956,1045`, `tools/runs_toolset.py:113` |
| Stream-triggered runs | `ConfigurerAuthority.may_run` → `PermissionService.check("execute")` → FGA `resource#can_read` | `libs/triggers/.../stream_subscriber.py:84-101` |
| Cron, poller-inbound and IMAP triggers | Nobody | `trigger_service.py:1435`, `channels/inbound_subscriber.py:207` |
| Agent-to-agent delegation | Nobody | `agent_delegation_tool.py:101` |

And "execute" is the same graph bit as "read", which every workspace member
inherits through the root project — so even the one graph-backed check cannot
tell "may see the agent" from "may run it".

**Goal:** resource-level invocation access for agents, modelled on cloud IAM
bindings, decided by one PDP and enforced at every entry point — web, A2A,
triggers and messaging channels alike. A channel only answers "who is this";
whether they may talk to the agent is the same question, with the same answer,
as in the web UI.

## The model in one paragraph

An agent carries **invocation bindings**: who may run it. A binding names one
of four principal classes, mirroring GCP's `allUsers` /
`allAuthenticatedUsers` / `domain:` / `user:`:

| Level | Who | GCP | AWS |
|---|---|---|---|
| `public` | anyone, anonymous included | `allUsers` | `"Principal": "*"` |
| `authenticated` | any platform account | `allAuthenticatedUsers` | `"*"` + authenticated condition |
| `workspace` | members of the agent's workspace | `domain:` | `"*"` + `aws:PrincipalOrgID` |
| `principals` | the listed users (groups later) | `user:` / `group:` | principal ARNs |

Every caller is first resolved to a **subject** (a user, or an anonymous
caller), then the PDP checks the subject against the bindings. A channel
message resolves its sender through **linked external identities**. A
workspace-level **constraint** — the analogue of GCP's
`iam.allowedPolicyMemberDomains` or S3 Block Public Access — decides which
levels may be bound at all.

`authenticated` has a known trap: in GCP it means any Google account in the
world, not "my company", and it has leaked data for that reason. Here it means
any account on this platform installation. It is off by default and should
read as such in the UI.

## Scope

**In:** the FGA relation for invocation; one PDP; converging the A2A, REST,
`runs.start`, stream, cron and channel entry points on it; linked external
identities with Telegram as the first provider; running a channel task as the
resolved sender; per-sender conversation routing; the workspace constraint; the
agent "Access" UI and the "Linked accounts" UI; migrating existing bots.

**Out (named so they are not forgotten):** user groups (the model reserves a
slot; governance's `group` subject is still unresolved, #198); an
"external contact" principal for people without a platform account; a
first-class agent run principal (service account); agent-to-agent delegation as
a PEP; access to global catalog agents (`get_with_catalog`), which stay
runnable by any authenticated user as today; Slack, Discord, Teams and email
senders beyond leaving the provider column open for them.

## Design

### 1. Bindings live in the graph (PAP data)

Agents are already graph objects (`resource:<agent_id>`, written by
`WorkspaceScopedRepository._record_graph_ownership`). Invocation becomes its own
relation on `resource`, independent of `reader`:

```fga
type Anonymous

type resource
  relations
    ...
    define invoker: [User, User:*, Anonymous:*, Workspace#members]
    define can_invoke: invoker or can_manage
```

- `User:<id>` — a specific person (`principals`).
- `Workspace:<ws>#members` — the `workspace` level.
- `User:*` — `authenticated`.
- `public` writes **both** `User:*` and `Anonymous:*`, so that an authenticated
  caller is never worse off than an anonymous one.
- `can_manage` implies `can_invoke`: whoever can change the agent can run it,
  and workspace admins keep their reach through `admin from workspace`.

Seeing an agent and running it are separate bits, as with GCP's `viewer` and
`run.invoker`. A member can list an agent restricted to three people without
being able to call it.

`OpenFGAPermissionService` remaps `execute` from `can_read` to `can_invoke`
(`auth/openfga_permission.py:17-31`). `ConfigurerAuthority` then picks up the
new meaning without a code change.

The `resource` type is shared by every resource kind, so `invoker` exists on
skills and collections too. It is meaningful only for agents, and later for
clients; nothing writes it elsewhere.

`model.fga`, `model.fga.yaml` (the `fga model test` fixtures) and both copies of
`authorization-model.json` (`config/auth/openfga/` and
`charts/agentarea/files/openfga/`) change together. The bootstrap already
writes a new model id when the JSON changes.

### 2. One PDP

`authorize_agent_action` becomes the PDP for `agent:execute`, backed by the
graph instead of `accessible_workspaces`:

```python
async def authorize_agent_invocation(subject: Subject, agent: AgentRef) -> EdgeDecision
```

`Subject` is `UserPrincipal | UserContext | AnonymousCaller`. `AnonymousCaller`
records where the call came from (`channel="telegram"`, `external_id`) for
provenance; the graph check itself uses a fixed `Anonymous:anyone`.

Order:

1. An agent-bound key → allow on its own agent only (unchanged).
2. Workspace constraint: drop the levels the agent's workspace forbids (see
   §4). This is checked here as well as at write time, so a binding written
   before the constraint changed cannot be used.
3. FGA `check(resource:<agent>, can_invoke, User:<id> | Anonymous:anyone)`.
4. Deny. A graph outage denies; it never falls back to workspace scope.

The decision carries the matched level (`public`, `authenticated`,
`workspace`, `principal`, `manager`, `agent-key`) so audit and the deny UX can
say why.

The verb constants in `A2APermissions` (`a2a_auth.py:48-71`) collapse into the
ones in `auth/access.py`.

### 3. Enforcement points

Each one calls the PDP. None decides on its own.

| PEP | Subject | Change |
|---|---|---|
| A2A | key or session principal | Already calls it; now graph-backed |
| REST task create (`agents_tasks.py`) | session principal | `unrestricted` → PDP; the route's authz marker becomes `enforced_in_handler` |
| `runs.start` toolset | the run's user | PDP before `TaskService.start_run` |
| Stream trigger (`ConfigurerAuthority`) | `trigger.created_by` | `may_run` keeps membership and calls the PDP instead of `PermissionService` |
| Cron and IMAP trigger | `trigger.created_by` | Same `may_run` check; on failure, `needs_owner` as on the stream path |
| Channel message | the **sender** (§5) | New, inside `TriggerService.fire` |

The channel check goes into `TriggerService.fire` rather than into each intake.
`fire` is the one place the poller (`inbound_subscriber`), the webhook
(`stream_subscriber`) and IMAP paths converge. `fire` gains an optional
`sender: ChannelSender | None`, which each intake fills from data it already
parses:

- poller: `events[0].user_id`;
- webhook: `event.data["user_id"]`;
- IMAP: `from`.

### 4. Workspace constraint

A workspace setting `allowed_invocation_levels`, defaulting to
`{"workspace", "principals"}`:

- The PAP refuses to write a binding at a forbidden level.
- The PDP ignores one (§2, step 2).
- Lifting the constraint does not create any bindings.
- Tightening it leaves existing bindings in the graph but makes them inert. The
  Access UI shows them struck through with the reason.

When organisations exist above workspaces, this moves up a level, exactly as
GCP organisation policy sits above project IAM.

### 5. Linked external identities (PIP)

Kratos is the identity provider and its identity id is the platform user id.
Kratos cannot look an identity up by an arbitrary trait, and Telegram is not an
OIDC provider, so the link lives in the platform:

```
external_identities
  id                uuid
  user_id           Kratos identity id
  provider          'telegram' | 'slack' | ...
  provider_scope    '' for Telegram (ids are global); team_id for Slack
  external_subject  Telegram from.id, as text
  display_snapshot  username at link time, for the UI only
  linked_via        'self_verified' | 'admin_asserted'
  workspace_id      NULL for self_verified; the asserting workspace otherwise
  created_by, created_at, revoked_at
  unique (provider, provider_scope, external_subject) where revoked_at is null
```

**Keys and scoping**

- **The key is the stable numeric id, never the username.** A username can be
  changed and then claimed by someone else.
- **A self-verified link is global to the user.** The table is not
  workspace-scoped, following the `WorkspaceMembership` precedent; access is
  still decided per agent by the PDP.
- **An admin-asserted link is valid only inside the workspace that asserted
  it.** Otherwise an admin of workspace A could decide who a person is in
  workspace B.

**Self-service linking** works by deep link and never by typing an id:

1. Account settings → Linked accounts → "Link Telegram". The API mints a nonce
   bound to the user. It is single-use, stored hashed and valid for 10 minutes.
2. The UI shows `https://t.me/<bot>?start=link_<nonce>`. Any of the
   workspace's bots works, because a Telegram `from.id` is the same across
   bots.
3. The bot receives `/start link_<nonce>`. The intake intercepts it **before**
   the PDP and trigger firing, binds `from.id` to the nonce's user, and replies
   "Linked to <email>".

**Admin assertion** is for "we wrote him in". It is audited, it is visible in the
person's own Linked accounts list, and the person can revoke it there.

The account page already has `ConnectedAccountsSection.tsx`, which links Google
and GitHub through the Kratos settings flow. Telegram sits next to them with
its own flow.

**Resolution** is `resolve_sender(provider, scope, external_subject,
workspace_id) -> UserPrincipal | AnonymousCaller`:

- Prefer a self-verified link.
- Otherwise use an admin-asserted link of that workspace.
- Otherwise the caller is anonymous.

Unlinking or revoking takes effect on the next message. There is no cache beyond
the request.

### 6. Whose identity the run uses

| PDP matched as | Task runs as | Notes |
|---|---|---|
| a user (any level) | **the sender** | Policy snapshot, audit actor, tool authorization and activity principal are the sender's |
| anonymous (`public`) | `trigger.created_by`, as sponsor | Provenance records `on_behalf_of=anonymous:telegram:<id>` |

**Running as the sender means building the service graph for the sender, not
only setting `AgentTask.user_id`.** The policy snapshot is resolved from
`repository_factory.user_context` (`task_service.py:141-164`), and the audit
actor comes from the same context. So the intake builds `UserContext(sender,
agent_workspace)` and a `RepositoryFactory` for it.

A sender admitted by a direct grant without workspace membership still runs
inside the agent's workspace, with its resources and budget, much like a
principal from another GCP organisation granted `run.invoker` on a service. In
that case the governance USER layer has no rules for them, so only the
workspace and agent layers apply.

**Anonymous runs need a sponsor** because a run must belong to someone. No
agent run principal exists today: agents never appear as runtime subjects, and
`OpenFGAPermissionService` always checks `User:`. Phase 1 makes the trigger's
creator the sponsor.

- The sponsor must still pass `may_run`. This is today's behaviour made
  explicit and checked.
- A first-class agent principal, the true service-account analogue, is a
  follow-up. It would let an admin write governance rules for "anonymous
  callers of agent X" without them leaking onto the sponsor's own runs.

### 7. Conversation routing

Follow-ups are routed today by `(workspace, agent_id, chat_id)`
(`tasks/.../repository.py:276-296`). This has two defects once senders matter:

- **Group chats.** Every member's messages land in one task owned by whoever
  wrote first.
- **Two bots on one agent.** A DM to bot B can be routed into bot A's task.

The key becomes `(workspace, agent_id, trigger_id, chat_id, principal_key)`:

- `principal_key` is the user id when the sender resolved to a user, and
  `anon:<provider>:<external_subject>` otherwise.
- In a DM this changes nothing.
- In a group, each person gets their own thread with the agent, under their own
  identity.

A shared group conversation, with one task and many speakers, is possible later
as an explicit trigger option. It needs a decision on whose identity such a task
runs under, and this design does not make it.

### 8. Denied senders

- **Execution record.** A `skipped` execution with reason
  `sender_not_authorized` and the matched subject. The message text is not
  stored.
- **DM reply.** At most once per (chat, 24h). If the sender is unlinked:
  "This bot is private. If you have an account, link Telegram: <url>". If they
  are linked but not granted: "You don't have access to this agent."
- **Group.** Silent.
- **Bot senders** (`from.is_bot`) are dropped before resolution, to prevent
  bot-to-bot loops. The Go parser currently discards `is_bot`; it starts
  carrying it.

### 9. UI

**Agent → Settings → Access** (new), for whoever has `can_manage` on the agent:

- **Level radio:** Public / Any signed-in user / Workspace members / Only
  specific people. Levels the workspace forbids are disabled, with the reason.
- **People list** (`principals`): add or remove workspace members, using the
  same member picker as the members page.
- **"Reachable via"** (read-only): A2A address, channel triggers. A reminder
  that one binding covers every door.

**Workspace settings → Security:** the allowed-levels constraint, admin only.

**Account → Linked accounts:** Telegram link and unlink, plus admin-asserted
links with a revoke button.

**Network → People:** the existing person × agent matrix starts showing real
answers, because it already calls the PDP.

Per `agentarea-webapp/AGENTS.md`, these screens reuse the existing settings,
member-picker and table components and get no component tests.

### 10. Migration

**Agents.** Backfill `resource:<agent>#invoker@Workspace:<ws>#members` for every
agent, and write it at agent creation. This reproduces today's
`accessible_workspaces` rule exactly, so steps 1–3 of the plan change no
behaviour. The ownership reconciler (`rebac/ownership_reconcile.py`, add-only)
gains the binding, so a missed backfill row is repaired on the next
post-migration Job.

**Existing Telegram bots** answer anyone today. Making their agents `public`
would preserve that, but it would also open those agents to anonymous A2A, which
nobody chose. Instead:

- Each existing channel trigger gets `legacy_open_senders = true`. The channel
  PEP honours it by treating unknown senders as anonymous and admitting them
  with the creator as sponsor, which is today's behaviour.
- The trigger page shows a banner: "This bot answers anyone. Choose who can use
  the agent." Choosing any level clears the flag.
- New triggers never get the flag.
- The flag is removed one minor release later.

**Alternative considered.** A conditional `Anonymous:*` binding scoped to a
channel, using an OpenFGA condition. It is cleaner in the graph, but it makes
"who can reach this agent" depend on the door, which is what this design moves
away from.

## Plan of record (phases)

1. **Graph and PDP, no behaviour change.**
   - `invoker` / `can_invoke`, the `Anonymous` type and the backfill.
   - `authorize_agent_invocation` backed by FGA.
   - `execute` → `can_invoke`.
   - A2A, REST, `runs.start` and stream `may_run` call the PDP.
   - Cron and IMAP get `may_run`.
2. **Access UI and PAP API.** Levels plus specific people, and the workspace
   constraint.
3. **Telegram senders.**
   - The `external_identities` table, deep-link linking and admin assertion.
   - `ChannelSender` into `fire` and the channel PEP.
   - Run-as-sender.
   - The routing key.
   - The deny UX and `is_bot`.
4. **Legacy bots and the other channels.** The legacy flag and banner; Slack
   (`team_id` + `user`), Discord and email senders on the same table.
5. **Later.** Groups, the external-contact principal, the agent run principal,
   and delegation as a PEP.

## Open questions

1. **Default for new agents:** `workspace` (proposed, today's behaviour) or
   `principals` with only the creator?
2. **`authenticated` on the hosted service:** offer it behind the constraint,
   or hide it there and offer it only on self-hosted installs?
3. **Public sponsor:** the trigger creator for phase 1 (proposed), or wait for
   the agent run principal before shipping `public`?
4. **Group chats:** per-sender threads (proposed), or a shared thread as the
   default?
5. **Admin-asserted links:** valid immediately (proposed, audited and revocable)
   or only after the person confirms in the bot?
6. **Existing bots:** the legacy flag for one release (proposed), or force a
   choice on upgrade?

## Related

- `docs/reference/authorization-model.md`: the enforcement table. It changes
  with phase 1.
- `docs/concepts/governance/policy-engine.md`: governance decides what a run
  may do. This design decides who may start one. The two PDPs stay separate.
- `docs/superpowers/plans/2026-09-21-authorization-gate-baseline.md`: the
  authorization gate ratchet. The REST routes leaving `unrestricted` count
  against it.
- `docs/guides/governance/grant-resource-access.md`: the per-resource grants
  this builds on.
