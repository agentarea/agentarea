# External access: public and guest access to apps and files — design

**Date:** 2026-11-10
**Status:** draft for review (brainstorming output; not yet a plan)
**Decision record:** ADR-0054
**Builds on:** `2026-10-09-agent-invocation-access-design.md` (its "later
levels": `public` / `allUsers`), ADR-0053 (personal connections,
`connection_user`), ADR-0050 (the API is bearer-only)

## Problem

Nobody without an AgentArea account can reach anything a workspace owns. The
MCP proxy (`/v1/mcp/{instance_id}/mcp`) requires a workspace principal, the
mcp-manager gateway is internal, every webapp route outside `/w` needs a
session, and the caller context an app receives is `user | agent` only.

That blocks a whole class of MCP apps whose point is the outside world: a
booking page (the first consumer: a cal.com-like calendar app), a form, a
status page, a file handed to a client.

## Goal

A workspace member can open one of their MCP apps or files to people who have
no account, in two modes:

1. **Everyone.** Anyone on the internet, at a stable address
   (`/p/<slug>`). GCP `allUsers`, SharePoint "Anyone", Drive "anyone with the
   link".
2. **A specific person.** A named guest with a personal link (`/g/<token>`),
   revocable on its own, every action attributed to that guest. Entra/Cognito
   guest identity; SharePoint "Specific people".

The app decides what an outsider may do inside it (see slots and book, but not
delete events).

Out of scope for v1: agents (see Constraints), guests who sign in with an
account (B2B), email one-time passcodes, password-protected links,
`allAuthenticatedUsers`.

## Principles

The zero-trust principles of the invocation-access design hold unchanged:
deny by default; every right is an explicit, audited grant; every request is
decided; fail closed; **the door does not grant** — `/p` and `/g` only
identify the caller, the resource's tuples decide.

Two more, from how every surveyed system does it:

- **A link is a credential, never a principal.** Rights attach to a principal
  or a stored grant; revoking deletes that record, not "the secret".
- **"Everyone" is not "every signed-in user".** Anonymous is its own subject
  type; `User:*` keeps meaning accounts on this installation.

## Principals and credentials

| Type | What it is | Analogue |
|---|---|---|
| `User` | A person with an account (unchanged) | user |
| `Agent` | An agent's workload identity (unchanged) | service account |
| `Anonymous` | Anyone without a session. Used only as the wildcard `Anonymous:*`; carries no identity, so two visitors cannot be told apart | GCP `allUsers`, SpiceDB `anonymoususer:*` |
| `Guest` | An external person without an account, created by a member, with a label ("Ivan, Sber"). Rights and audit attach to it | Entra External ID guest, Cognito unauthenticated identity, Calendly invitee |

**Share link** is the credential: a stored record plus a secret. A guest can
have several links (one per device, one rotated after a leak); revoking one
leaves the others and the guest's history (their bookings) intact. A later
stronger credential (email OTP) attaches to the same `Guest` without a model
change.

## Design

### 1. Graph

`resource` gains the two subject types on exactly the relations outsiders may
hold (`libs/common/agentarea_common/rebac/openfga/model.fga`):

```fga
type Anonymous
type Guest

type resource
  relations
    ...
    define reader: [User, Agent, Anonymous:*, Guest]
    define connection_user: [User, Agent, Anonymous:*, Guest]
    # invoker is unchanged: [User, Agent, Workspace#members]
```

- **Apps** use `connection_user`, the relation ADR-0053 made "who may call
  through a connection". The MCP proxy already checks it (`use_connection` →
  `can_use_connection`), so the call path gains no new check. It works on a
  personal connection too: `connection_user` is a direct grant, outside the
  `can_read but not personal` branch, so an owner can publish their personal
  calendar without sharing it with the workspace.
- **Files** use `reader` on a **file handle** (§4).
- **`invoker` does not change.** Agents cannot be opened to outsiders (see
  Constraints); the model enforces it, not only the API.

| Mode | Tuple |
|---|---|
| App, everyone | `resource:<instance>#connection_user@Anonymous:*` |
| App, a guest | `resource:<instance>#connection_user@Guest:<id>` |
| File, everyone | `resource:<handle>#reader@Anonymous:*` |
| File, a guest | `resource:<handle>#reader@Guest:<id>` |

No OpenFGA conditions: expiry and revocation are decided on the share-link row
on every request (§3), and the last link of a guest going away deletes that
guest's tuple. All four model files change together (`model.fga`,
`model.fga.yaml`, both `authorization-model.json`).

### 2. Records

```
guests
  id, workspace_id, label, email (nullable), created_by, created_at,
  deleted_at

share_links
  id, workspace_id, resource_id, resource_kind (mcp_app | file),
  audience (public | guest), guest_id (null for public),
  slug (public only; unique per deployment), token_hash (guest only),
  tools (nullable list: narrows the app's external tools),
  expires_at (nullable), revoked_at, created_by, created_at, last_used_at

file_handles
  id (= the graph resource id), workspace_id, path, created_by, created_at
```

- Tokens: 256-bit random, base64url, stored as SHA-256. Shown once at
  creation; the UI can rotate (new link, old one revoked).
- A public link has a slug and no secret: the address is meant to be known.
  Without a chosen slug it gets a random one.
- The API writes and deletes the tuples; it never exposes wildcards.
  `audience=public` is the parameter.

### 3. The guest's request path

**Doors** (webapp, outside `/w`, no session required):

- `/p/<slug>` — public. The visitor is `Anonymous` **even if they have an
  AgentArea session**, so a public page behaves the same for everyone and no
  `User:*` tuples are needed.
- `/g/<token>` — guest. The webapp server exchanges the token at
  `POST /public/v1/guest-sessions` for a short-lived guest session (12 h,
  bound to guest + link), keeps it in an httpOnly, `SameSite=Lax` cookie **on
  the webapp origin**, and redirects to `/g/s/<link_id>` without the token
  (RFC 6750: no bearer tokens in page URLs). The webapp server calls the API
  with that session as a bearer; the API stays bearer-only (ADR-0050).

**Resolution**, on every request:

1. Find the link (by slug or session). Unknown → 404. Revoked, expired, or its
   resource gone → 410.
2. Principal = `Anonymous` or `Guest:<id>`.
3. OpenFGA: `can_use_connection` (app) or `can_read` (file) on the resource. A
   graph error is a deny (503).
4. App calls only: the **external-tools filter** (§5), then the link's `tools`
   narrowing.
5. The workspace's governance policy (`authorize_mcp_tool_call`) as for any
   caller; there is no agent layer.
6. Upstream with a signed caller context naming the outsider (§5).
7. Audit: principal, `link_id`, `guest_id`, the issuing member, IP, tool.

**Apps** render in the existing `McpAppFrame` on the sandbox origin. Tool
calls go webapp server → `POST /public/v1/apps/<link_id>/mcp` → the same
proxy core as `/v1/mcp/{instance_id}/mcp`, entered with an outsider principal.

**Files**: `GET /public/v1/files/<link_id>` → 302 to a presigned GET valid
for a few minutes, with `Content-Disposition`. A handle points at a path: an
overwritten file serves its new content (Dropbox behaviour); a deleted one
answers 410.

**Every public route:** rate limit per IP and per link (429 + `Retry-After`),
`Referrer-Policy: no-referrer`, `X-Robots-Tag: noindex`, no third-party
resources on the door pages, and no state change on GET (mail scanners follow
links).

### 4. File handles

Workspace files are addressed by path and are not graph objects today: their
routes are `unrestricted` with the workspace-scoped repository as the
boundary. Sharing a file creates a `file_handles` row whose id is a new
`resource:<id>`, with ownership tuples like any graph resource
(`grant_resource_owner`). The graph stays the only authority; when workspace
files become graph resources wholesale, the handle is that object.

### 5. The contract for apps

**Marking external tools.** A tool is reachable by outsiders only if it says
so in `_meta`, next to the MCP Apps `ui` keys:

```json
"_meta": { "ai.agentarea/external": ["anonymous", "guest"] }
```

An unmarked tool answers 403 to an outsider no matter what the link says. The
link's `tools` can only narrow the marked set. An app that marks nothing
cannot be opened externally; the Share dialog says so.

**Caller context.** `X-AgentArea-Context` (HS256, per-instance key, unchanged
signing) gains two kinds; `mcp-apps-kit/context/caller.ts` parses them:

```ts
type Caller =
  | { kind: "user" | "agent"; ... }                       // unchanged
  | { kind: "guest"; guestId: string; linkId: string; label: string;
      workspaceId: string; tool?: string }
  | { kind: "anonymous"; linkId: string; workspaceId: string; tool?: string };
```

Row-level rules are the app's: a calendar shows a guest only their own
bookings, keyed by `guestId`.

**Apps mint guests for themselves.** A booking made on a public page needs a
personal cancel/reschedule link for the booker (what cal.com and Calendly send
by uid). An instance with the context capability calls
`POST /v1/mcp/instances/<self>/guests` with its instance credential and gets
`{ guest_id, url }`. It can mint only on its own resource, only with
`audience=guest`, and the issuer recorded is the instance; the owner sees and
revokes these guests like any other.

### 6. Owner surfaces

- **API** (`/v1`, workspace members):
  - `guests`: create, list, delete. Deleting revokes all of the guest's links.
  - `share-links`: create, list (by resource, by guest), revoke, rotate.
  - Who may share: the resource's direct `manager`, as ADR-0053 does for
    connection sharing. A workspace admin lists and revokes, but cannot
    publish someone else's personal connection.
- **Platform toolset:** the same operations as tools, under the usual
  governance, so an agent or Claude can "give Ivan a link to my calendar".
- **UI:** the connection Settings → Access section (ADR-0053) becomes one
  scale: Personal → Workspace → Guests → Everyone. "Guests": add a person,
  copy their link, revoke, rotate. "Everyone": on/off and slug. The same
  dialog on a file. A workspace page "External access" lists every live link.

### 7. Enterprise boundary

Core ships the mechanism. Control is enterprise, behind one interface with a
permissive core default:

```python
class ExternalAccessPolicy(Protocol):
    async def may_publish(self, workspace_id, resource, audience) -> Decision: ...
    def max_ttl(self, workspace_id, audience) -> timedelta | None: ...
    async def record(self, event: ExternalAccessEvent) -> None: ...  # audit sink
```

Enterprise implements: public access prevention per organisation/workspace
(the GCS feature of that name; the invocation design's
`allowedPolicyMemberDomains` analogue), mandatory expiry and max TTL, an admin
registry of every link with bulk revoke, SIEM export of outsider actions.

## Constraints

- **No external grants on agents.** The workspace-files toolset is
  `unrestricted`, so running an agent reads the workspace's files; opening an
  agent to an outsider would leak them. `invoker` keeps its subject types, and
  the share API rejects `resource_kind` other than `mcp_app` and `file`. This
  lifts only once run scope covers resources.
- **Only platform-run or context-enabled apps get outsider callers they can
  tell apart.** A plain `url` connection without caller context receives the
  call but cannot distinguish a guest from its owner; the Share dialog warns.

## Errors

| Situation | Answer |
|---|---|
| Unknown link or slug | 404 |
| Link revoked or expired; resource or file deleted | 410, a readable page |
| Graph unavailable | 503, deny |
| Tool not marked external, or outside the link's `tools` | 403, audited as `not_external` |
| Workspace policy denies | 403 with the reason |
| App rejects the caller kind | the tool error, shown in the app's UI |
| Rate limited | 429 + `Retry-After` |
| `may_publish` denies (enterprise) | 403 at link creation |

## Testing

- **Unit:** token generation, hashing, lookup and rotation; the external-tools
  filter and `tools` narrowing; kit `verifyContextToken` for `guest` and
  `anonymous`; the share API rejecting agents.
- **Model** (`model.fga.yaml`): `Anonymous:*` → `can_use_connection` on an
  app; `Guest` without a tuple → deny; `User:*` does not include `Anonymous`;
  a personal connection with a guest tuple → the guest may use it, a workspace
  member still may not; `invoker` rejects both new types.
- **API integration:** token → session → tool call → audit row; revoke
  mid-session → the next call is 410; public file → 302 → revoke → 410; an
  instance mints a guest only on itself; `/p` with a member's session still
  resolves to `Anonymous`.
- **Webapp e2e:** `/p/<slug>` with no session renders the app, an external
  tool succeeds, an unmarked tool is refused; `/g/<token>` leaves no token in
  the address bar or history.

## Rollout

- Additive: without the new tuples nothing changes for existing resources.
- One migration: `guests`, `share_links`, `file_handles`; the model files.
- Public routes behind `AGENTAREA_EXTERNAL_ACCESS_ENABLED` (deployment flag,
  default on).
- First consumer: `mcp-servers/mcp-apps-calendar`, its own spec, built on this.

## Open questions

- Guest session length and whether a guest may "stay signed in" on a device
  (longer session, still revocable through the link).
- CAPTCHA or proof-of-work on public write tools beyond rate limiting.
- Upgrading a guest to a full user later (Firebase-style linking) — modelled
  for, not built.
