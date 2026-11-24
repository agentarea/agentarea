# identity: porting notes

Python paths are relative to `agentarea-platform/`.

## Ported

These four routes, plus the owned-workspaces lookup that the admin authority reads:
- POST `/v1/workspaces` (`apps/api/agentarea_api/api/v1/workspaces.py:212`)
- POST `/v1/workspaces/{workspace}/invitations`
- POST `/v1/invitations/accept` (`apps/api/agentarea_api/api/v1/workspace_invitations.py:436`)
- POST `/v1/workspaces/{workspace}/api-keys/` (`apps/api/agentarea_api/api/v1/api_keys.py`)

Second pass (`handlers/routes.go`, `handlers/explorer.go`), all 26 identity-tag
operations now have a handler:
- GET `/v1/workspaces` (`workspaces.py:246`); PUT/DELETE `{ws}/logo` (`workspaces.py:281`, `:301`)
- GET `{ws}/invitations` (`workspace_invitations.py:350`), DELETE `{ws}/invitations/{id}` (`:365`),
  POST `/v1/invitations/preview` (`:392`), GET `{ws}/members` (`:483`), DELETE `{ws}/members/{user_id}` (`:515`)
- GET `{ws}/api-keys/` (`api_keys.py:162`), GET/DELETE `{ws}/api-keys/{token_id}` (`:184`, `:217`)
- GET `{ws}/principals` (`principals.py:67`)
- `/v1/me/external-identities`: POST `telegram/link`, GET, DELETE `{identity_id}` (`external_identities.py:54`, `:76`, `:96`)
- `{ws}/access-control`: GET graph (`access_control.py:396`), GET/POST/DELETE relationships (`:516`, `:626`, `:658`),
  POST check (`:706`), resolve (`:744`), sync (`:851`)

Authority, as in Python: invitations list/revoke, logo, the whole explorer and
sync need workspace admin (an agent run is never admin). Removing a member: the
owner is never removable (409); only the owner removes others, anyone may leave
(403 otherwise); the last member stays (409). API keys: a member lists and reads
only keys they created, an admin all; revoke is the creator or an admin; runner
(client) keys are invisible (404). Key revoke, link and unlink refuse
non-user credentials (scope check). Toolsets get `Module.Members()` (`api.Members`).

There are no Python routes for users/me, workspace rename/delete/roles or key
rotation; OAuth AS and Hydra client registration and consent are the connections
module's (dossier), so none are here.

## Kept bugs

- Invitation `created_at`/`updated_at` are the local wall clock (`datetime.now`),
  but `expires_at`, `accepted_at` and `membership_granted_at` are naive UTC
  (`libs/common/agentarea_common/workspaces/service.py:94`). The response
  labels all of them `Z`, so `created_at` is off by the process's UTC offset.
- API key `created_at` is local time, while `expires_at` is UTC plus the days.
- `_next_free_slug` probes base, base-2, ... without a bound.
- GET `/v1/workspaces` writes: it provisions the personal workspace for a
  signed-in user (`workspaces.py:246`, `libs/common/agentarea_common/workspaces/service.py:460`),
  and that row's `created_at` is local time.
- Revoking an already revoked invitation records `member.revoke_invitation` again
  (`workspace_invitations.py:383`).
- Pending invitations past `expires_at` are still listed (`libs/common/agentarea_common/workspaces/repository.py:59`).
- `/access-control/sync` counts attempts, not writes, and only writes
  `Workspace#members` tuples; `collections` is always 0 (`access_control.py:858`).
- `/graph` and `/relationships` answer empty when the graph is down
  (`_resource_tuples`, `access_control.py:256`); `/resolve` answers
  `allowed: false` on a graph error (`:785`) while `/check` answers 503 (`:733`).
- `linked_at` is a naive datetime, serialised without `Z` (`external_identities.py:44`).

## Invitation mail

An addressed invitation is mailed after the row is stored (`service/invitation_email.go`,
`deliver_invitation_for_workspace`): `sent`, `failed` (logged without the link), or
`not_configured` when the deployment has no SMTP. The settings are the deployment's own
`SMTP_*` names (`config/email.py`, shared with Kratos' courier): `SMTP_CONNECTION_URI` wins
over the discrete `SMTP_HOST`/`PORT`/`USERNAME`/`PASSWORD`/`PROTOCOL`/`DISABLE_STARTTLS`/
`SKIP_SSL_VERIFY`; `SMTP_FROM_EMAIL` and `SMTP_FROM_NAME` are the sender. The SMTP session is
`internal/kernel/mail`, which the streams email reply channel also sends through.

Deviations:
- The HTML body escapes the workspace name and the link; Python interpolated them raw, so a
  workspace named `<b>x</b>` rendered markup in the invitee's mail. Test:
  `service/invitation_email_test.go` `TestAddressedInvitationIsMailedWithItsLink`.
- A server named without `SMTP_FROM_EMAIL` fails startup; Python's `build_mailer` returned no
  mailer and every invitation silently answered `not_configured`. Test:
  `store/mailer_test.go` `TestNoServerIsNoMailAndAServerNeedsASender`.
- Reading the workspace's name failing answers `failed`; Python let the exception out of
  `deliver_invitation_for_workspace` after the invitation was committed.

## Not ported (gaps)

- Governance's `provision_default_policies` on workspace creation
  (`workspaces.py:67-89`). `service.Deps.OnWorkspaceCreated` is the hook and it is nil.
- `invited_by_display_name` is always null, because no identity directory is
  wired (`workspace_invitations.py:207`).

## Blocked (app wiring)

`app/serve.go`'s identity line cannot reach these from `coreDeps` (no blob
store, Redis, config or audit writer there), so they are declared in
`identity.Deps` / `service.Deps` and nil until wired:
- `Directory` (Kratos admin, `LoadConfig` + `NewDirectory`, env
  `AGENTAREA_AUTH_KRATOS_ADMIN_URL`): nil means no names or emails beyond the
  caller's own, personal workspaces need the credential's email, and removing
  a member is refused (500, logged). Without the member's email the pending
  invitations addressed to them could not be revoked, so they could rejoin.
- `Logos` (blob store): nil leaves PUT/DELETE `logo` unmounted, and listing a
  workspace that has a `logo_key` fails loudly.
- `LinkCodes` (Redis `SetEX`, `NewLinkCodes`): nil answers telegram/link 503.
- `Audit` (governance `AuditWriter`): nil records nothing (`member.invite`,
  `api_key.create`, `member.remove`, `member.revoke_invitation`, `api_key.revoke`, `access.grant`/`revoke`).
- `Resources`: wired (app/identity_ports.go) over agents `Lookup` + `Inventory()`
  (agents, skills, collections, skill counts) and catalog `MCPInventory()` (the
  workspace's own `mcp_servers` rows); the whole explorer is mounted.
- `MembershipRemovalHandler()` must be registered on the outbox relay for
  `workspace.membership.ended`; until it is, a removal whose graph revoke
  failed (202 `revocation_pending`) is not retried.
- `OnWorkspaceCreated` (governance default policies) as before.

## Deviations

- The `workspaces` registry and invitation lookup by token run on
  `db.Global()`, not a workspace session. The token names its workspace, so no
  workspace is known before the lookup.
- As in projects, the edge authenticates before the body is validated.
  FastAPI does it the other way round.
- The membership-ended outbox event carries `aggregate_id`/`aggregate_type` in
  its data; the Go outbox has no columns for them.
- Audit rows are written in their own transaction after the action.
- A blank `AGENTAREA_AUTH_KRATOS_ADMIN_URL` falls back to the default
  `http://kratos:4434` (the loader treats empty as unset); Python disables the
  directory on an empty value.
- The behaviour suite (`test/suite/identity/`) compiles and lints but has not
  run: `go build ./...` fails in runs and sandbox (other modules' work in
  progress), so `agentarea serve` cannot be built for the stack.

## Runner keys (2026-11-15)

`Module.RunnerKeys()` (`api.RunnerKeys`, `service/runnerkeys.go`) is
`APIKeyService.create_token/list_tokens(client_id=...)/get_token/revoke_token` for
agents' client routes (adapted in app/agents_ports.go): keys bound to a client
(`api_keys.client_id`), no expiry, created by the caller; agents audits
`api_key.create`/`api_key.revoke` as `clients.py` does. Suite: `test/suite/runs/runner_test.go`.

## An agent changes no membership (2026-11-15)

Python bug, fixed in Go: `remove` compared only `user_id`, so a run started by
the owner could remove any member (`workspaces/service.py` remove).
`RemoveMember` now refuses an agent-subject caller with
`ErrAgentMembership` (403). Inviting and revoking already refused agents
(`requireAdmin`, `Admins.IsAdmin`). Test: `TestAnAgentChangesNoMembership`.
