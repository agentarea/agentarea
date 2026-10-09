# Agent invocation access — design

**Date:** 2026-10-09
**Branch:** claude/adoring-shannon-2na8q5
**Status:** draft for review (brainstorming output; not yet a plan)

## Problem

A Telegram bot attached to an agent answers anyone who finds it. Nothing on the
inbound path looks at the sender. The Go poller and the Telegram webhook parser
both carry `from.id` into the event, but no code reads it, and every run
executes as `trigger.created_by`.

That is one symptom of a wider gap: there is no single answer to "may this
principal run this agent". Today five different things decide it:

| Entry point | Who decides | Where |
|---|---|---|
| A2A JSON-RPC | `authorize_agent_action` (workspace scope; never reads the graph) | `apps/api/.../v1/a2a_auth.py:127` |
| REST task creation, `runs.start` toolset | nobody — `unrestricted` | `v1/agents_tasks.py:755,956,1045`, `tools/runs_toolset.py:113` |
| Stream-triggered runs | `ConfigurerAuthority.may_run` → FGA `resource#can_read` | `libs/triggers/.../stream_subscriber.py:84-101` |
| Cron, poller-inbound, IMAP triggers | nobody | `trigger_service.py:1435`, `channels/inbound_subscriber.py:207` |
| Agent-to-agent delegation | nobody | `agent_delegation_tool.py:101` |

In the graph, "execute" is the same bit as "read", and every workspace member
inherits it through the root project. So "may see the agent" and "may run it"
cannot be told apart.

The run identity has the same blur. A run executes as a user — whoever fired it,
otherwise the trigger's creator. That user is at once the one who asked, the
identity the run's tools act as, and the subject governance resolves policy
for. A Telegram stranger therefore runs with the trigger creator's identity and
policy.

## Goal

Agent invocation governed like a cloud resource. An agent carries IAM-style
bindings. One PDP decides every invocation, whether it comes from the web, A2A,
a trigger, a messaging channel or another agent. A run separates *who asked*
from *who acts*.

There are no deployments to preserve. This design replaces the current
mechanisms outright and has no compatibility path.

## Principles (zero trust)

- **Deny by default.** An agent nobody was granted is runnable by nobody.
- **Every right is an explicit, audited tuple.** No role implies invocation:
  not `can_manage`, not workspace admin, not workspace membership. Each right
  is a grant that somebody wrote, and the PAP records who wrote it.
- **Every request is decided.** Each message, call and firing goes through the
  PDP, and nothing caches a past allow. A revoked grant or link stops the very
  next message.
- **Fail closed.** A graph outage, an unknown sender or an unparseable subject
  is a deny.
- **The door does not grant.** A channel, A2A or the web UI only identifies the
  caller. What the caller may do depends on the agent's bindings, never on the
  door they came through.
- **Identity is proven by its owner.** Nobody can assert that an external
  account belongs to a platform user except that user, by proving control of
  the account.

## Principals

| Type | What it is | Authenticated by |
|---|---|---|
| `User` | A platform account (Kratos identity id) | Kratos session, API key, Hydra token, or a linked external identity (§4) |
| `Agent` | An agent's own workload identity — the service-account analogue | The platform, for runs it executes |
| `Contact` | An external account known only by its provider id (a Telegram user with no platform account), registered in one workspace | The provider: a Telegram update with that `from.id` |
| `Anonymous` | An unidentified caller | Nothing |

Groups are a later addition. The model reserves the slot, and governance's
`group` subject is still unresolved (#198).

`Contact` is what makes "we wrote them in" possible without breaking the last
principle. An admin does not claim that Telegram 12345 *is* some platform user.
The admin registers Telegram 12345 as a principal in its own right. The
Telegram update itself proves the `from.id`: it arrives from Telegram over the
bot's own webhook, protected by the secret token. So a contact needs no further
verification.

## Design

### 1. Bindings (PAP data, in the graph)

Agents are already graph objects: `resource:<agent_id>`, written by
`WorkspaceScopedRepository._record_graph_ownership`. Invocation becomes its own
relation, independent of `reader`:

```fga
type User
type Anonymous
type Agent
type Contact
  relations
    define workspace: [Workspace]

type Workspace
  relations
    define members: [User, Agent]
    define admin: [User]

type resource
  relations
    ...
    define invoker: [User, User:*, Anonymous:*, Agent, Contact, Workspace#members]
    define can_invoke: invoker
```

A binding has one of four levels, mirroring GCP's `allUsers` /
`allAuthenticatedUsers` / `domain:` / `user:`:

| Level | Tuples | GCP | AWS |
|---|---|---|---|
| `public` | `User:*` and `Anonymous:*` | `allUsers` | `"Principal": "*"` |
| `authenticated` | `User:*` | `allAuthenticatedUsers` | `"*"` + authenticated condition |
| `workspace` | `Workspace:<ws>#members` (people and the workspace's agents) | `domain:` | `"*"` + `aws:PrincipalOrgID` |
| `principals` | `User:<id>`, `Contact:<id>`, `Agent:<id>` | `user:` / `serviceAccount:` | principal ARNs |

How the levels behave:

- `public` writes both tuples, so an authenticated caller is never worse off
  than an anonymous one.
- `authenticated` means any account on this installation. In GCP its namesake
  means any Google account in the world, and has leaked data for that reason.
  It is off by default (§6).
- `can_invoke` is `invoker` and nothing else.

**What creating an agent writes:** exactly `invoker@User:<creator>`, next to the
ownership tuples, so it shares their rollback-on-failure.

**Who may change bindings:** whoever has `can_manage` on the agent. Managing an
agent lets you grant invocation, including to yourself. You do not get
invocation by managing. Every grant is audited as `agent_access.grant` /
`.revoke`, with the writer and the level.

**Seeing versus running:** these are separate bits, as with GCP's `viewer` and
`run.invoker`. A member can list an agent that only three people may call.

`OpenFGAPermissionService` maps `execute` to `can_invoke`
(`auth/openfga_permission.py:17-31`). It checks the subject's own type, not
always `User:`.

These files change together:

- `model.fga`
- `model.fga.yaml` (the `fga model test` fixtures)
- both copies of `authorization-model.json` (`config/auth/openfga/` and
  `charts/agentarea/files/openfga/`)

### 2. One PDP

```python
async def authorize_agent_invocation(caller: Caller, agent: AgentRef) -> InvocationDecision
```

`Caller` is a tagged union:

- `UserCaller(user_id, via)`
- `AgentCaller(agent_id, run_id)`
- `ContactCaller(contact_id)`
- `AnonymousCaller(provider, external_id)`

`via` records the door: `web`, `a2a`, `api_key`, `telegram`, …. It is used for
audit and never for the decision.

The decision runs in this order:

1. **Agent-bound key.** Allowed only on its own agent.
2. **Workspace constraint (§6).** Levels the agent's workspace forbids are
   removed from consideration. Write time enforces this too. Checking here as
   well means a binding written before the constraint was tightened stays
   inert.
3. **Graph check.** FGA `check(resource:<agent>, can_invoke, <caller subject>)`.
   An anonymous caller is checked as `Anonymous:anyone`.
4. **Otherwise deny.** A graph error is a deny.

The decision carries the level that matched: `public`, `authenticated`,
`workspace`, `principal` or `agent-key`. Audit, the run's provenance and the
deny UX all read it.

`authorize_agent_action` and the duplicated verb constants in `A2APermissions`
(`a2a_auth.py:48-71`) are replaced by this function.

### 3. Run identity: who asks versus who acts

A run carries two principals, as a Cloud Run request does: the invoker checked
at the edge, and the service account the service runs as.

| Field | Meaning | Used for |
|---|---|---|
| `actor` | `Agent:<id>`, always | The identity the run's tools, MCP calls and resource reads act as |
| `caller` | The `Caller` the PDP admitted | Governance's caller layer, audit, reply routing, thread key |
| `chain` | Callers above this one when an agent delegates | Audit; each hop's caller layer |

**Governance.** Governance resolution is already tighten-only across
`workspace → agent → user → task`. The `user` layer becomes the **caller
layer**: rules can name a user, a contact, `anonymous`, or an agent.

- An anonymous Telegram caller gets the workspace's and agent's policy,
  tightened by whatever the workspace writes for `anonymous` (a lower budget,
  no write tools, mandatory approval).
- A trusted colleague gets their own user rules.
- No caller can loosen what the agent's layer sets.
- A delegated run adds each hop's caller layer, so a chain can only narrow.

**Resources.** Secrets, MCP connections and tools a run uses are reached as the
`actor`, so the agent's configuration is the boundary. A caller cannot reach
anything the agent was not given.

The escalation path is a manager wiring a resource they could not otherwise use
into an agent they can invoke. That is closed at configuration time: wiring a
secret or connection into an agent requires use-rights on it. This is today's
`get_for_use` creator-or-admin rule (`secrets/.../catalog_service.py:158`), the
analogue of GCP's `iam.serviceAccounts.actAs`.

Checking agent resource grants in the graph at use time (`reader@Agent:<id>`)
is a follow-up.

**What changes in the code:**

- Activities build their context from `actor` and `caller` instead of a single
  `user_id`. These sites today take the task owner:
  - `create_user_context` (`execution/.../activities/dependencies.py:189-217`)
  - tool discovery (`activities/agent/config.py:526,577`)
  - the triggers-tool default user (`tools.py:350,377`)
  - delegation (`tools.py:594`)
- `AgentTask` stores `caller_type`, `caller_id` and `via` in place of a bare
  `user_id`.
- `@audited` records both principals.
- `create_task_with_policy` resolves the snapshot for the caller, not for the
  service's `UserContext`.

**Task authority** decides who may follow up on, cancel or read a task. It
belongs to the caller. A workspace admin also gets it, and only if they hold
`can_manage` on the agent.

### 4. Who the caller is, per door

| Door | Caller | Notes |
|---|---|---|
| Web / REST | `UserCaller` from the session | |
| API key | `UserCaller` of the key's owner, or the bound agent's rule | |
| A2A | The key's or token's principal | Anonymous A2A only reaches `public` agents |
| Agent delegation | `AgentCaller` of the delegating agent | The target must bind that agent, or `workspace` |
| Messaging channel | The sender, resolved (below) | |
| Cron, generic webhook, stream trigger | `UserCaller` of the trigger's owner | Re-checked on every firing; the owner losing `can_invoke` sets `needs_owner` |

A trigger that does not carry a person — a schedule, a signed webhook, a
stream — fires on its owner's behalf, the way a scheduled job belongs to
whoever set it up.

Ownership is a transferable field. It is not "whoever created it". Transferring
requires the new owner's `can_invoke`.

**Resolving a channel sender** is `resolve_sender(provider, scope, external_id,
workspace) -> Caller`:

1. A **linked user identity** (below) → `UserCaller`.
2. Otherwise a **contact** registered in the agent's workspace →
   `ContactCaller`.
3. Otherwise `AnonymousCaller`.

The order means that someone who later creates an account and links Telegram is
treated as themselves from then on. Their contact entry then shows "linked to
<user>" and can be removed.

### 5. External identities and contacts

**Linked user identities.** These are global to the user and not
workspace-scoped, following the `WorkspaceMembership` precedent.

```
user_external_identities
  id, user_id                 Kratos identity id
  provider                    'telegram' | 'slack' | ...
  provider_scope              '' for Telegram (ids are global); team_id for Slack
  external_id                 Telegram from.id, as text — never the username
  display_snapshot            username at link time, for the UI only
  created_at, revoked_at
  unique (provider, provider_scope, external_id) where revoked_at is null
```

Linking is self-service and proven by deep link:

1. The user goes to Account → Linked accounts → "Link Telegram". The API mints
   a nonce bound to the user: single-use, stored hashed, valid for 10 minutes.
2. The UI shows `https://t.me/<bot>?start=link_<nonce>`. Any bot on the
   platform works, because a Telegram `from.id` is the same across bots.
3. The bot receives `/start link_<nonce>`. The intake handles it **before** the
   PDP and before any trigger fires: it binds `from.id` to the nonce's user and
   replies "Linked to <email>".

Kratos cannot look an identity up by an arbitrary trait, and Telegram is not an
OIDC provider. That is why the link lives in the platform. The account page's
`ConnectedAccountsSection.tsx` (Google and GitHub through Kratos) gets a
Telegram row with this flow.

**Contacts.** These are workspace-scoped and use the `WorkspaceScopedMixin`.

```
contacts
  id, workspace_id
  provider, provider_scope, external_id
  display_name                set by the admin
  created_by, created_at
  unique (workspace_id, provider, provider_scope, external_id)
```

Whoever has `can_manage` on an agent may create a contact while granting it,
and workspace admins may create contacts at any time. There are two ways to
register one:

- **By invite link** (the usual way; people do not know their numeric id). The
  admin gets `t.me/<bot>?start=inv_<code>`, single-use and expiring. The first
  `from.id` to open it becomes the contact, and the admin sees the username to
  confirm.
- **By id.** The admin pastes the numeric id.

A contact is a graph principal (`Contact:<id>#workspace@Workspace:<ws>`). It is
granted like a person and named in governance like a person.

### 6. Workspace constraint

The workspace setting `allowed_invocation_levels` defaults to
`{"workspace", "principals"}`:

- The PAP refuses to write a binding at a level the setting forbids, and the
  PDP ignores one (§2, step 2).
- Allowing `public` or `authenticated` is a workspace-admin action and is
  audited.

This is the analogue of GCP's `iam.allowedPolicyMemberDomains` or S3 Block
Public Access. When organisations exist above workspaces, it moves up a level.

### 7. Channel specifics

**Where the check runs.** In `TriggerService.fire`, which is where the poller
(`inbound_subscriber`), webhook (`stream_subscriber`) and IMAP paths converge.

- `fire` takes a `ChannelSender` that each intake builds from data it already
  parses:
  - poller: `events[0].user_id`
  - webhook: `event.data["user_id"]`
  - IMAP: `from`
- `fire` resolves the caller, asks the PDP, and only then evaluates conditions
  and creates the task.
- Trigger conditions remain a content filter, never an access control.

**Bot messages.** Messages whose sender is a bot (`from.is_bot`) are dropped
before resolution, to prevent loops. The Go parser starts carrying `is_bot`.

**Conversation threads.** These are keyed by `(workspace, agent, trigger, chat,
caller)`. Today the key is `(workspace, agent, chat)`.

- In a DM nothing changes.
- In a group, each person has their own thread with the agent, under their own
  identity.
- A bot shared by two triggers no longer leaks one conversation into the other.

**Group chats.** A group is a room, not a principal. Every message is decided
for its sender, so one group can mix granted colleagues and refused strangers.

**Denied senders.**

- **Execution record.** A `skipped` execution with reason
  `caller_not_authorized`, the resolved caller and the door. The message text is
  not stored.
- **In a DM**, at most one reply per (chat, 24h):
  - unknown sender: "This bot is private. If you have an account, link
    Telegram: <url>";
  - known sender without access: "You don't have access to this agent."
- **In a group:** silence.

**One bot, one door.** A Telegram bot has a single webhook. Registering the
same token on a second trigger silently disconnects the first, and deleting
either one unregisters both (`_trigger_creation.py:256-325`). So a bot token is
unique per installation, and attaching one that is already in use is refused
with a pointer to the trigger that holds it. Creating a channel trigger requires
`can_manage` on the agent, because it opens a new door to it.

### 8. UI

**Agent → Settings → Access** (new), for `can_manage`:

- A level radio: Only specific people / Workspace members / Any signed-in user
  / Public. Levels the workspace forbids are disabled, with the reason.
- A principal list for `principals`:
  - add a member through the members page's picker;
  - add an agent;
  - add a contact, either "Invite via Telegram" or "Add by id".
- A read-only **Reachable via** list: web, the A2A address, each channel
  trigger. It is a reminder that one binding covers every door.

**Workspace → Settings → Security:** allowed invocation levels and the contact
list. Admin only.

**Account → Linked accounts:** Telegram link and unlink, next to Google and
GitHub.

**Network → People:** the existing person × agent matrix (`network_people.py`)
calls the new PDP and gains contacts as rows.

**Governance → Policies:** subject choices gain `contact`, `anonymous` and
`agent` for the caller layer.

Per `agentarea-webapp/AGENTS.md`, these screens reuse the existing settings,
member-picker and table components and get no component tests.

## Plan of record (phases)

1. **Graph and PDP.**
   - The `invoker` / `can_invoke` relation and the new principal types.
   - Creator-only binding at agent creation.
   - `authorize_agent_invocation`.
   - `execute` → `can_invoke`.
   - Every PEP in §4 calls the PDP, delegation included.
   - Trigger ownership becomes transferable.
2. **Access UI, PAP API, workspace constraint.**
3. **Run identity.**
   - `actor` / `caller` / `chain` on the task and in activities.
   - The caller layer in governance.
   - Task authority by caller.
4. **Telegram senders.**
   - Linked identities and contacts.
   - Sender resolution and the PDP in `fire`.
   - The thread key.
   - The deny UX and `is_bot`.
   - Bot-token uniqueness.
5. **Other channels.** Slack (`team_id` + `user`), Discord and email senders on
   the same tables.
6. **Later.**
   - Groups.
   - Graph-checked agent resource grants at use time.
   - Personal OAuth connections used on the caller's behalf.

## Open questions

1. **`authenticated` on the hosted service.** Allow it behind the workspace
   constraint, or not offer it at all there? On a shared installation it means
   "anyone who signed up".
2. **Shared group threads.** Should a trigger be able to opt into one
   conversation per group chat? It would need a rule for whose caller layer
   governs a task with many speakers. The strictest-of-speakers rule is one
   candidate.
3. **Delegation inside a workspace.** Should `workspace` bindings admit the
   workspace's agents automatically (`Workspace#members` includes them today),
   or must agents always be bound by name?

## Related

- `docs/reference/authorization-model.md`: the enforcement table. It is
  rewritten with phase 1.
- `docs/concepts/governance/policy-engine.md`: the governance PDP. It decides
  what a run may do; this design decides who may start one and as whom. The
  caller layer is the seam between the two.
- `docs/superpowers/plans/2026-09-21-authorization-gate-baseline.md`: the
  authorization gate ratchet. The REST routes leaving `unrestricted` count
  against it.
- `docs/guides/governance/grant-resource-access.md`: the per-resource grants
  this builds on.
