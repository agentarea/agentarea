# Authorization Gate Baseline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the authorization gates that already exist in the codebase actually deny, and add a ratchet so no new endpoint ships ungated.

**Architecture:** Nothing in the permission model changes — no OpenFGA model edit, no new entity, no new grant semantics. The work is threefold: split the overloaded `can_write_workspace` port method so "is this caller an admin" becomes its own question answered by the `Workspace#admin` tuple that already exists in the graph; point `assert_workspace_admin` at it; and freeze the route/gate inventory in a test so the remaining ungated surface is a tracked number instead of an unknown one.

**Tech Stack:** Python 3.12, FastAPI, OpenFGA (`config/auth/openfga/model.fga`, schema 1.1), pytest, uv workspace.

## Global Constraints

- Run tests with `uv run python -m pytest` from `agentarea-platform/`; pytest is not in the runtime container venv.
- No silent fallbacks. Where behaviour depends on `ACCESS_CONTROL_BACKEND`, the selection is logged at startup by name, following the existing `PermissionService=%s` pattern in `apps/api/agentarea_api/main.py:120`.
- Do NOT change the semantics of `AuthorizationService.can_write_workspace`. It is a tenancy check (`AgentService`, `registries.py` depend on that meaning); making it admin-only breaks ordinary member work.
- Additive only: no OpenFGA model change in this plan. `Workspace#admin` already exists (`model.fga:11`).
- No emojis in source. Comments only where the code cannot say it itself.

---

## Findings this plan is based on

Measured by AST-parsing every router under `apps/api/agentarea_api/api/v1/` (270 endpoints) for calls to any known gate, then hand-verifying the high-stakes rows.

**Four gate mechanisms exist. Two of them never deny.**

| Mechanism | Sites | Actually denies? |
|---|---|---|
| Repository `workspace_id` filter | every request | Yes, but it is tenancy, not authorization |
| `assert_workspace_admin` → `can_write_workspace` | 19 | **No** — OSS impl returns `workspace_id == user_context.workspace_id` (`workspace_authorization.py:25-26`), which every member satisfies |
| `require_permission` → `PermissionService` | 8 | Only when `ACCESS_CONTROL_BACKEND` is `openfga`/`keto`. **The default is `disabled`** (`config/access_control.py:11`), and `WorkspaceScopedPermissionService.check()` returns `True` unconditionally (`workspace_permission.py:20`) |
| Service-level actor rule | 1 (`WorkspaceMembershipService.remove`) | Yes — owner-only removal, self-leave allowed, owner and last member protected |

Which of these is live depends on the deployment:

- **Kubernetes** — `charts/agentarea/values.yaml:1226` ships `openfga.enabled: true`, and the backend template sets `ACCESS_CONTROL_BACKEND=openfga` from it (`templates/agentarea-backend/deployment.yaml:125`). So the 8 `require_permission` sites really deny there. `assert_workspace_admin` still does not, because no `authorization` extension exists — checked `../agentarea-enterprise/pyproject.toml`, which registers only `entitlement_guard` and `api_router`. **In deployed environments the 19 money/policy/graph-write sites are open to any workspace member.**
- **`make up`** — `docker-compose.yaml` never sets `ACCESS_CONTROL_BACKEND` (0 occurrences; `docker-compose.dev.yaml` sets it 20 times), so the default falls to `disabled` and **all four mechanisms reduce to the tenancy filter.** `make up-dev` is the configuration that matches production.

**Counts:** 33 endpoints carry a gate; 122 mutating and 115 read endpoints carry none. Crown-jewel domains hold 30 ungated mutating and 26 ungated read endpoints.

**Ungated endpoints that move money, secrets, policy or identity:**

| Domain | Ungated |
|---|---|
| money | `GET /agents/{id}/wallet`, `/wallet/balance`, `/wallet/payments`; `GET /usage/events` |
| secrets | `POST /secrets`, `PATCH /secrets/{id}`, `PUT /secrets/{id}/value`, `DELETE /secrets/{id}`; all of `/provider-configs` writes (6); `/mcp-auth-configs` writes (3); `POST /connections/catalog/{id}/connect`, `PUT /connections/oauth/apps/{key}` |
| policy | `GET /policies`, `GET /policies/{id}`, `POST /governance/effective-policy/preview`, `GET /governance/task-policy-snapshots/{id}` |
| identity | `POST /workspaces/{id}/invitations`, `DELETE .../invitations/{id}`, `POST /api-keys/`, `DELETE /api-keys/{id}`, `GET /workspace/export`, all `/clients` writes (7) |

Wallet **writes** are already gated (4 of 7 endpoints) — they just gate on a check that does not deny.

**Verified false positives — do not "fix" these:**

- `POST /a2a/rpc` — own auth context, rejects unauthenticated (`agents_a2a.py:333`).
- `POST /webhooks/{id}` and the other webhook verbs — public ingress on `get_public_webhook_manager`, authenticated by webhook identity.
- `GET /connections/oauth/callback` — OAuth redirect, validated by `state`.
- `POST /invitations/accept`, `POST /workspaces`, `GET /workspaces` — must stay open to the acting user. `GET /workspaces` must never require a workspace header.
- `DELETE /workspaces/{id}/members/{user_id}` — gated inside `WorkspaceMembershipService.remove`.
- `GET /workspace/export` — full-workspace config dump, but secret values are replaced with placeholders. Real finding, lower severity.

**`create_invitation` carries a self-documented placeholder.** `_ensure_workspace_access` (`workspace_invitations.py:236-251`) says in its own docstring: *"Until permissions land in their own PR, the rule is: a user may operate on a workspace iff that workspace is in their accessible_workspaces list."* A member's own workspace is always in that list, so any member can invite anyone. This plan is that PR.

**The `admin` tuples already exist.** `scripts/20260722_backfill_resource_authz.py:64` writes `Workspace#admin` for every existing workspace owner, and `seed_workspace()` writes it for new ones. Task 6 verifies this per environment rather than assuming it.

---

## File Structure

| File | Responsibility |
|---|---|
| `libs/common/agentarea_common/auth/authorization.py` | Modify: add `is_workspace_admin` to the ABC; repoint `assert_workspace_admin` at it |
| `libs/common/agentarea_common/auth/workspace_authorization.py` | Modify: implement `is_workspace_admin` for the no-graph deployment |
| `libs/common/agentarea_common/auth/graph_workspace_authorization.py` | Create: the graph-backed implementation |
| `libs/common/tests/test_workspace_admin_authorization.py` | Create: unit tests for both implementations |
| `apps/api/agentarea_api/main.py` | Modify: select the implementation, log which one |
| `apps/worker/agentarea_worker/main.py` | Modify: same selection |
| `apps/api/agentarea_api/api/v1/workspace_invitations.py` | Modify: drop `_ensure_workspace_access`, gate on admin |
| `apps/api/agentarea_api/api/v1/wallet.py` | Modify: gate the three read endpoints |
| `apps/api/agentarea_api/api/v1/usage.py` | Modify: gate `GET /usage/events` |
| `apps/api/tests/test_admin_gated_endpoints.py` | Create: endpoint-level 403 tests |
| `apps/api/tests/route_authz_inventory.json` | Create: the frozen inventory fixture |
| `apps/api/tests/test_route_authz_inventory.py` | Create: the ratchet |

---

### Task 1: Split the port — `is_workspace_admin`

**Files:**
- Modify: `agentarea-platform/libs/common/agentarea_common/auth/authorization.py:20-69`
- Modify: `agentarea-platform/libs/common/agentarea_common/auth/workspace_authorization.py`
- Create: `agentarea-platform/libs/common/agentarea_common/auth/graph_workspace_authorization.py`
- Test: `agentarea-platform/libs/common/tests/test_workspace_admin_authorization.py`

**Interfaces:**
- Consumes: `AuthorizationService` ABC, `UserContext` (`.user_id`, `.workspace_id`), `OpenFGAClient.check(namespace=, object=, relation=, subject_id=) -> result with .allowed`.
- Produces: `AuthorizationService.is_workspace_admin(user_context: UserContext, workspace_id: str) -> bool`; `GraphWorkspaceAuthorizationService(graph_client)`; `assert_workspace_admin` now calls `is_workspace_admin`.

- [ ] **Step 1: Write the failing tests**

Create `agentarea-platform/libs/common/tests/test_workspace_admin_authorization.py`:

```python
"""Admin resolution must come from the graph, not from workspace equality."""

import pytest
from agentarea_common.auth.context import UserContext
from agentarea_common.auth.graph_workspace_authorization import (
    GraphWorkspaceAuthorizationService,
)
from agentarea_common.auth.workspace_authorization import (
    WorkspaceScopedAuthorizationService,
)


class FakeGraph:
    """Records checks and answers from a set of allowed (object, relation, subject)."""

    def __init__(self, allowed: set[tuple[str, str, str]]) -> None:
        self.allowed = allowed
        self.calls: list[dict] = []

    async def check(self, *, namespace: str, object: str, relation: str, subject_id: str):
        self.calls.append(
            {
                "namespace": namespace,
                "object": object,
                "relation": relation,
                "subject_id": subject_id,
            }
        )

        class Result:
            pass

        result = Result()
        result.allowed = (object, relation, subject_id) in self.allowed
        return result


def ctx(user_id: str, workspace_id: str) -> UserContext:
    return UserContext(user_id=user_id, workspace_id=workspace_id)


@pytest.mark.asyncio
async def test_graph_admin_allowed_reads_the_admin_tuple():
    graph = FakeGraph({("ws-1", "admin", "User:owner")})
    service = GraphWorkspaceAuthorizationService(graph)

    assert await service.is_workspace_admin(ctx("owner", "ws-1"), "ws-1") is True
    assert graph.calls == [
        {
            "namespace": "Workspace",
            "object": "ws-1",
            "relation": "admin",
            "subject_id": "User:owner",
        }
    ]


@pytest.mark.asyncio
async def test_graph_admin_denies_a_plain_member():
    """The regression this task exists for: membership is not admin."""
    graph = FakeGraph({("ws-1", "members", "User:invitee")})
    service = GraphWorkspaceAuthorizationService(graph)

    assert await service.is_workspace_admin(ctx("invitee", "ws-1"), "ws-1") is False


@pytest.mark.asyncio
async def test_graph_write_check_stays_a_tenancy_check():
    """can_write_workspace must NOT become admin-only; AgentService relies on it."""
    graph = FakeGraph(set())
    service = GraphWorkspaceAuthorizationService(graph)

    assert await service.can_write_workspace(ctx("invitee", "ws-1"), "ws-1") is True
    assert await service.can_write_workspace(ctx("invitee", "ws-1"), "ws-2") is False
    assert graph.calls == []


@pytest.mark.asyncio
async def test_no_graph_deployment_admits_the_workspace_owner_shape():
    """With no graph configured there is no admin separation; this is explicit."""
    service = WorkspaceScopedAuthorizationService()

    assert await service.is_workspace_admin(ctx("someone", "ws-1"), "ws-1") is True
    assert await service.is_workspace_admin(ctx("someone", "ws-1"), "ws-2") is False
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd agentarea-platform && uv run python -m pytest libs/common/tests/test_workspace_admin_authorization.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agentarea_common.auth.graph_workspace_authorization'`

- [ ] **Step 3: Add the abstract method**

In `libs/common/agentarea_common/auth/authorization.py`, add to the `AuthorizationService` ABC after `can_write_workspace` (which keeps its docstring unchanged, plus one clarifying line):

```python
    @abstractmethod
    async def can_write_workspace(self, user_context: UserContext, workspace_id: str) -> bool:
        """Check if the user can mutate entities in the given workspace.

        This is a tenancy question — "is this workspace mine" — not a
        privilege question. Use ``is_workspace_admin`` for the latter.

        Args:
            user_context: Current user and workspace context.
            workspace_id: The workspace to check write access for.

        Returns:
            True if the user can write to the workspace.
        """
        ...

    @abstractmethod
    async def is_workspace_admin(self, user_context: UserContext, workspace_id: str) -> bool:
        """Check if the user administers the given workspace.

        Gates policy, money and authorization-graph writes. Plain membership
        must not satisfy this: a member could otherwise loosen their own spend
        cap, delete a deny rule, or grant themselves any relation.

        Args:
            user_context: Current user and workspace context.
            workspace_id: The workspace to check admin rights on.

        Returns:
            True if the user administers the workspace.
        """
        ...
```

- [ ] **Step 4: Repoint the assertion helper**

In the same file, change the body of `assert_workspace_admin`:

```python
    authz = resolve(AuthorizationService)
    if not await authz.is_workspace_admin(user_context, user_context.workspace_id):
        raise HTTPException(
            status_code=403,
            detail="Only a workspace admin may perform this action",
        )
```

- [ ] **Step 5: Implement the no-graph case**

Append to `libs/common/agentarea_common/auth/workspace_authorization.py`:

```python
    async def is_workspace_admin(self, user_context: UserContext, workspace_id: str) -> bool:
        """No graph is configured, so this deployment has no admin separation.

        Returning the tenancy answer is the only coherent verdict here, and it
        is why ``apps/api/main.py`` logs the selected implementation by name:
        a deployment that wants admin separation must set
        ``ACCESS_CONTROL_BACKEND``.
        """
        return workspace_id == user_context.workspace_id
```

- [ ] **Step 6: Implement the graph-backed case**

Create `libs/common/agentarea_common/auth/graph_workspace_authorization.py`:

```python
"""Graph-backed workspace authorization — admin resolved from the relation graph."""

import logging

from ..rebac.keto_client import KetoClient
from ..rebac.openfga_client import OpenFGAClient
from .authorization import AuthorizationService
from .context import UserContext

logger = logging.getLogger(__name__)


class GraphWorkspaceAuthorizationService(AuthorizationService):
    """Resolve workspace admin from ``Workspace:<ws>#admin@User:<uid>``.

    Reads only. The tuples are written by ``seed_workspace`` at workspace
    creation and by ``scripts/20260722_backfill_resource_authz.py`` for
    workspaces that predate it.
    """

    def __init__(self, graph_client: OpenFGAClient | KetoClient) -> None:
        self._graph = graph_client

    async def get_accessible_workspaces(self, user_context: UserContext) -> list[str]:
        return [user_context.workspace_id]

    async def can_write_workspace(self, user_context: UserContext, workspace_id: str) -> bool:
        return workspace_id == user_context.workspace_id

    async def is_workspace_admin(self, user_context: UserContext, workspace_id: str) -> bool:
        result = await self._graph.check(
            namespace="Workspace",
            object=workspace_id,
            relation="admin",
            subject_id=f"User:{user_context.user_id}",
        )
        return result.allowed
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `cd agentarea-platform && uv run python -m pytest libs/common/tests/test_workspace_admin_authorization.py -v`
Expected: 4 passed

- [ ] **Step 8: Run the whole common suite for regressions**

Run: `cd agentarea-platform && uv run python -m pytest libs/common -q -m "not integration"`
Expected: no new failures. A failure naming `is_workspace_admin` as missing means a test double implements the ABC — add the method to that double.

- [ ] **Step 9: Commit**

```bash
git add agentarea-platform/libs/common/agentarea_common/auth/authorization.py \
        agentarea-platform/libs/common/agentarea_common/auth/workspace_authorization.py \
        agentarea-platform/libs/common/agentarea_common/auth/graph_workspace_authorization.py \
        agentarea-platform/libs/common/tests/test_workspace_admin_authorization.py
git commit -m "feat(authz): resolve workspace admin from the graph instead of workspace equality"
```

---

### Task 2: Wire the implementation and say which one is running

**Files:**
- Modify: `agentarea-platform/apps/api/agentarea_api/main.py:122-126`
- Modify: `agentarea-platform/apps/worker/agentarea_worker/main.py` (the matching `AuthorizationService` registration)
- Test: `agentarea-platform/apps/api/tests/test_authz_wiring.py`

**Interfaces:**
- Consumes: `GraphWorkspaceAuthorizationService` from Task 1; `openfga_client` / `keto_client` locals already resolved above the registration block in both `main.py` files.
- Produces: an `AuthorizationService` singleton whose implementation name is logged as `AuthorizationService=%s`.

- [ ] **Step 1: Write the failing test**

Create `agentarea-platform/apps/api/tests/test_authz_wiring.py`:

```python
"""The selected authorization implementation must follow the configured backend."""

from agentarea_common.auth.graph_workspace_authorization import (
    GraphWorkspaceAuthorizationService,
)
from agentarea_common.auth.workspace_authorization import (
    WorkspaceScopedAuthorizationService,
)
from agentarea_api.main import select_authorization_service


def test_graph_backend_selects_the_graph_implementation():
    sentinel = object()
    service, name = select_authorization_service(
        openfga_client=sentinel, keto_client=None, authz_factory=None
    )
    assert isinstance(service, GraphWorkspaceAuthorizationService)
    assert name == "GraphWorkspaceAuthorizationService"


def test_no_backend_selects_the_workspace_scoped_implementation():
    service, name = select_authorization_service(
        openfga_client=None, keto_client=None, authz_factory=None
    )
    assert isinstance(service, WorkspaceScopedAuthorizationService)
    assert name == "WorkspaceScopedAuthorizationService"


def test_extension_factory_wins_when_no_backend_is_configured():
    def factory():
        return WorkspaceScopedAuthorizationService()

    service, name = select_authorization_service(
        openfga_client=None, keto_client=None, authz_factory=factory
    )
    assert name == "extension:authorization"
    assert service is factory
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd agentarea-platform && uv run python -m pytest apps/api/tests/test_authz_wiring.py -v`
Expected: FAIL — `ImportError: cannot import name 'select_authorization_service'`

- [ ] **Step 3: Extract the selection as a testable function**

Add to `apps/api/agentarea_api/main.py`, at module level above `initialize_services`:

```python
def select_authorization_service(*, openfga_client, keto_client, authz_factory):
    """Pick the AuthorizationService implementation. Returns (value, impl_name).

    An explicitly configured graph backend wins over a registered extension,
    mirroring how PermissionService is selected below.
    """
    from agentarea_common.auth.graph_workspace_authorization import (
        GraphWorkspaceAuthorizationService,
    )
    from agentarea_common.auth.workspace_authorization import (
        WorkspaceScopedAuthorizationService,
    )

    graph_client = openfga_client or keto_client
    if graph_client is not None:
        return GraphWorkspaceAuthorizationService(graph_client), (
            "GraphWorkspaceAuthorizationService"
        )
    if authz_factory:
        return authz_factory, "extension:authorization"
    return WorkspaceScopedAuthorizationService(), "WorkspaceScopedAuthorizationService"
```

- [ ] **Step 4: Use it at the registration site**

Replace `main.py:122-126` with:

```python
        authz_factory = ExtensionRegistry.get_factory("authorization")
        authz_impl, authz_name = select_authorization_service(
            openfga_client=openfga_client,
            keto_client=keto_client,
            authz_factory=authz_factory,
        )
        if authz_name == "extension:authorization":
            register_factory(AuthorizationService, authz_impl)
        else:
            register_singleton(AuthorizationService, authz_impl)
        if authz_name == "WorkspaceScopedAuthorizationService":
            logger.warning(
                "AuthorizationService=%s (ACCESS_CONTROL_BACKEND=%s): this deployment has "
                "no admin separation — every workspace member passes assert_workspace_admin",
                authz_name,
                backend,
            )
        else:
            logger.info(
                "AuthorizationService=%s (ACCESS_CONTROL_BACKEND=%s)", authz_name, backend
            )
```

- [ ] **Step 5: Mirror it in the worker**

Apply the same replacement in `apps/worker/agentarea_worker/main.py`, importing `select_authorization_service` from `agentarea_api.main` is NOT allowed (the worker must not import the API app). Copy the same three-branch selection inline there, with the same log lines.

- [ ] **Step 6: Run the tests**

Run: `cd agentarea-platform && uv run python -m pytest apps/api/tests/test_authz_wiring.py -v`
Expected: 3 passed

- [ ] **Step 7: Commit**

```bash
git add agentarea-platform/apps/api/agentarea_api/main.py \
        agentarea-platform/apps/worker/agentarea_worker/main.py \
        agentarea-platform/apps/api/tests/test_authz_wiring.py
git commit -m "feat(authz): select the graph authorization service and log which one runs"
```

---

### Task 3: Gate invitation creation and revocation on admin

**Files:**
- Modify: `agentarea-platform/apps/api/agentarea_api/api/v1/workspace_invitations.py:236-251` (delete `_ensure_workspace_access`), `:263-299` (`create_invitation`), `:316-335` (`revoke_invitation`), `:300-315` (`list_invitations`)
- Test: `agentarea-platform/apps/api/tests/test_admin_gated_endpoints.py`

**Interfaces:**
- Consumes: `assert_workspace_admin` from `agentarea_common.auth` (already exported there — `wallet.py:16` imports it that way).
- Produces: no new symbols. `_ensure_workspace_access` is removed; nothing else references it.

- [ ] **Step 1: Confirm nothing else uses the placeholder**

Run: `rg -n "_ensure_workspace_access" agentarea-platform/`
Expected: matches only inside `workspace_invitations.py`. If another module uses it, gate that module in this task too rather than leaving a second copy of the rule.

- [ ] **Step 2: Write the failing test**

Create `agentarea-platform/apps/api/tests/test_admin_gated_endpoints.py`:

```python
"""A plain member must not be able to invite, revoke, or read the money."""

from unittest.mock import MagicMock

import pytest
import pytest_asyncio
from agentarea_api.main import app
from agentarea_common.auth.authorization import AuthorizationService
from agentarea_common.auth.dependencies import get_user_context
from httpx import ASGITransport, AsyncClient

WORKSPACE = "ws-1"


class MemberAuthz(AuthorizationService):
    """A member of their workspace who is not its admin."""

    async def get_accessible_workspaces(self, user_context):
        return [user_context.workspace_id]

    async def can_write_workspace(self, user_context, workspace_id):
        return workspace_id == user_context.workspace_id

    async def is_workspace_admin(self, user_context, workspace_id):
        return False


@pytest.fixture
def member_context(monkeypatch):
    """Authenticate as a non-admin member and make the DI container agree."""
    from agentarea_common.di import container as container_module

    monkeypatch.setattr(container_module, "resolve", lambda _iface: MemberAuthz())

    context = MagicMock()
    context.user_id = "invitee"
    context.workspace_id = WORKSPACE
    context.accessible_workspaces = [WORKSPACE]

    async def _override():
        return context

    app.dependency_overrides[get_user_context] = _override
    yield context
    app.dependency_overrides.pop(get_user_context, None)


@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_member_cannot_create_an_invitation(client, member_context):
    response = await client.post(
        f"/v1/workspaces/{WORKSPACE}/invitations",
        json={"email": "outsider@example.com"},
    )
    assert response.status_code == 403, response.text


@pytest.mark.asyncio
async def test_member_cannot_list_invitations(client, member_context):
    response = await client.get(f"/v1/workspaces/{WORKSPACE}/invitations")
    assert response.status_code == 403, response.text
```

- [ ] **Step 3: Run it to verify it fails**

Run: `cd agentarea-platform && uv run python -m pytest apps/api/tests/test_admin_gated_endpoints.py -v`
Expected: FAIL — both tests get 201/200 instead of 403, because `_ensure_workspace_access` accepts any member of the workspace. That is the bug. If instead you get a 404, the mount prefix differs: take it from `apps/api/agentarea_api/api/v1/router.py` and fix the URLs.

- [ ] **Step 4: Delete the placeholder and gate the three endpoints**

In `workspace_invitations.py`, delete the whole `_ensure_workspace_access` function (lines 236-251). Then in `create_invitation`, replace the line `_ensure_workspace_access(user, workspace_id)` with:

```python
    if workspace_id != user.workspace_id:
        raise HTTPException(status_code=403, detail=f"Access denied to workspace {workspace_id}")
    await assert_workspace_admin(user)
```

Apply the identical two statements at the start of `revoke_invitation` and `list_invitations`, replacing their `_ensure_workspace_access(...)` calls. Add the import at the top of the file:

```python
from agentarea_common.auth import assert_workspace_admin
```

The path-vs-context comparison stays because `assert_workspace_admin` only ever inspects `user_context.workspace_id`; without it a member of `ws-1` could pass their own admin check while naming `ws-2` in the path.

- [ ] **Step 5: Run the file's existing tests plus the new one**

Run: `cd agentarea-platform && uv run python -m pytest apps/api/tests -q -k "invitation or admin_gated"`
Expected: all pass. A failing invitation test that asserts a member can invite is asserting the old rule — update it to expect 403 and keep an owner-invites case.

- [ ] **Step 6: Commit**

```bash
git add agentarea-platform/apps/api/agentarea_api/api/v1/workspace_invitations.py \
        agentarea-platform/apps/api/tests/test_admin_gated_endpoints.py
git commit -m "fix(authz): only a workspace admin may invite, list or revoke invitations"
```

---

### Task 4: Gate the money reads

**Files:**
- Modify: `agentarea-platform/apps/api/agentarea_api/api/v1/wallet.py:201` (`get_wallet`), `:276` (`get_wallet_balance`), `:300` (`get_payment_history`)
- Modify: `agentarea-platform/apps/api/agentarea_api/api/v1/usage.py` (`GET /usage/events`)
- Test: `agentarea-platform/apps/api/tests/test_admin_gated_endpoints.py` (extend)

**Interfaces:**
- Consumes: `assert_workspace_admin`, already imported in `wallet.py:16`. `usage.py` needs the import added.
- Produces: no new symbols.

- [ ] **Step 1: Extend the test**

Add `import inspect` to the imports at the top of `agentarea-platform/apps/api/tests/test_admin_gated_endpoints.py` (ruff's E402 fails a mid-file import), then append:

```python
def test_every_wallet_and_usage_endpoint_asserts_admin():
    """Balance and payment history are money reads; membership must not suffice."""
    from agentarea_api.api.v1 import usage, wallet

    expected = {
        (wallet, "get_wallet"),
        (wallet, "get_wallet_balance"),
        (wallet, "get_payment_history"),
        (usage, "list_usage_events"),
    }
    missing = []
    for module, fn_name in expected:
        fn = getattr(module, fn_name, None)
        assert fn is not None, f"{module.__name__}.{fn_name} not found — rename in the test"
        if "assert_workspace_admin" not in inspect.getsource(fn):
            missing.append(f"{module.__name__}.{fn_name}")
    assert not missing, f"ungated money endpoints: {missing}"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd agentarea-platform && uv run python -m pytest apps/api/tests/test_admin_gated_endpoints.py::test_every_wallet_and_usage_endpoint_asserts_admin -v`
Expected: FAIL listing all four endpoints. The four handler names are verified against the current routers; if one is reported as not found, the router was renamed — take the new name from `grep -n "^async def" wallet.py` rather than guessing.

- [ ] **Step 3: Add the gate**

As the first statement in each of `get_wallet`, `get_wallet_balance` and `list_wallet_payments` in `wallet.py`, and in the `/usage/events` handler in `usage.py`:

```python
    await assert_workspace_admin(user_context)
```

In `usage.py`, add the import:

```python
from agentarea_common.auth import assert_workspace_admin
```

If an endpoint's signature has no `user_context`, add `user_context: UserContextDep` as its first parameter and import `UserContextDep` from `agentarea_common.auth.dependencies`.

- [ ] **Step 4: Run the tests**

Run: `cd agentarea-platform && uv run python -m pytest apps/api/tests/test_admin_gated_endpoints.py -v`
Expected: all pass

- [ ] **Step 5: Check the frontend does not now 403 for ordinary members**

Run: `rg -n "wallet|usage/events" agentarea-webapp/src --glob '*.ts' --glob '*.tsx' -l`
Expected: a list of call sites. For each page that a non-admin can reach, the 403 must render as an absence of the widget, not as a generic error toast — see `lib/api-errors.ts`. Note any page needing that follow-up in the commit body; do not change frontend behaviour in this task.

- [ ] **Step 6: Commit**

```bash
git add agentarea-platform/apps/api/agentarea_api/api/v1/wallet.py \
        agentarea-platform/apps/api/agentarea_api/api/v1/usage.py \
        agentarea-platform/apps/api/tests/test_admin_gated_endpoints.py
git commit -m "fix(authz): require workspace admin to read wallet balance, payments and usage"
```

---

### Task 5: Freeze the inventory so the remaining surface is a ratchet

**Files:**
- Create: `agentarea-platform/apps/api/tests/route_authz_inventory.json`
- Create: `agentarea-platform/apps/api/tests/test_route_authz_inventory.py`

**Interfaces:**
- Consumes: nothing from earlier tasks at runtime; it re-derives the inventory by AST-parsing `api/v1/*.py`.
- Produces: `route_authz_inventory.json`, the committed baseline. Later plans shrink its `ungated` list; nothing may grow it.

- [ ] **Step 1: Write the ratchet test**

Create `agentarea-platform/apps/api/tests/test_route_authz_inventory.py`:

```python
"""Ratchet: no new ungated endpoint may be added, and gated ones may not regress.

The inventory is derived by parsing the routers, so it cannot drift from the code
the way a hand-maintained list would. Shrinking `ungated` is the goal; growing it
fails here with the exact paths that were added.
"""

import ast
import json
from pathlib import Path

V1 = Path(__file__).resolve().parents[1] / "agentarea_api" / "api" / "v1"
BASELINE = Path(__file__).with_name("route_authz_inventory.json")

GATES = {
    "assert_workspace_admin",
    "_assert_workspace_admin",
    "require_permission",
    "check_workspace_membership",
    "_verify_task_for_agent",
    "authorize_agent_action",
}
METHODS = {"get", "post", "put", "patch", "delete"}


def _calls(node: ast.AST) -> set[str]:
    names = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            func = child.func
            if isinstance(func, ast.Name):
                names.add(func.id)
            elif isinstance(func, ast.Attribute):
                names.add(func.attr)
    return names


def current_inventory() -> dict[str, list[str]]:
    gated, ungated = set(), set()
    for path in sorted(V1.glob("*.py")):
        if path.name == "router.py":
            continue
        tree = ast.parse(path.read_text())
        helpers = {
            n.name: _calls(n)
            for n in tree.body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        prefixes = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
                func = node.value.func
                name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
                if name != "APIRouter":
                    continue
                prefix = next(
                    (
                        kw.value.value
                        for kw in node.value.keywords
                        if kw.arg == "prefix" and isinstance(kw.value, ast.Constant)
                    ),
                    "",
                )
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        prefixes[target.id] = prefix

        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            direct = _calls(node)
            reachable = set(direct)
            for name in direct:
                reachable |= helpers.get(name, set())
            has_gate = bool(reachable & GATES)

            for dec in node.decorator_list:
                if not isinstance(dec, ast.Call):
                    continue
                func = dec.func
                if not isinstance(func, ast.Attribute) or func.attr not in METHODS:
                    continue
                owner = func.value.id if isinstance(func.value, ast.Name) else "router"
                sub = dec.args[0].value if dec.args and isinstance(dec.args[0], ast.Constant) else ""
                route = f"{func.attr.upper()} {prefixes.get(owner, '')}{sub}"
                (gated if has_gate else ungated).add(route)

    return {"gated": sorted(gated), "ungated": sorted(ungated)}


def test_no_new_ungated_endpoints():
    baseline = json.loads(BASELINE.read_text())
    current = current_inventory()

    added = sorted(set(current["ungated"]) - set(baseline["ungated"]))
    assert not added, (
        "New endpoints ship without an authorization gate:\n  "
        + "\n  ".join(added)
        + "\n\nGate them with assert_workspace_admin or require_permission. If the endpoint "
        "carries its own auth scheme (public webhook, A2A, OAuth callback), add it to the "
        "baseline's `ungated` list in the same commit with a comment in the PR body."
    )


def test_no_gated_endpoint_lost_its_gate():
    baseline = json.loads(BASELINE.read_text())
    current = current_inventory()

    lost = sorted(set(baseline["gated"]) - set(current["gated"]))
    assert not lost, "Endpoints that used to be gated no longer are:\n  " + "\n  ".join(lost)
```

- [ ] **Step 2: Generate the baseline from the current tree**

Run:

```bash
cd agentarea-platform && uv run python -c "
import json, sys
sys.path.insert(0, 'apps/api/tests')
from test_route_authz_inventory import current_inventory, BASELINE
BASELINE.write_text(json.dumps(current_inventory(), indent=2) + '\n')
inv = current_inventory()
print('gated', len(inv['gated']), 'ungated', len(inv['ungated']))
"
```

Expected: prints counts. `ungated` should be in the low 200s and `gated` in the 30s; the exact split depends on Tasks 3 and 4 having landed.

- [ ] **Step 3: Verify the ratchet passes on a clean tree**

Run: `cd agentarea-platform && uv run python -m pytest apps/api/tests/test_route_authz_inventory.py -v`
Expected: 2 passed

- [ ] **Step 4: Verify the ratchet actually catches a regression**

Add a throwaway endpoint to `apps/api/agentarea_api/api/v1/audit.py`:

```python
@router.post("/ratchet-probe")
async def ratchet_probe() -> dict:
    return {}
```

Run: `cd agentarea-platform && uv run python -m pytest apps/api/tests/test_route_authz_inventory.py -v`
Expected: FAIL naming `POST /audit-logs/ratchet-probe`. Then delete the probe endpoint and rerun — 2 passed. A ratchet that has not been seen to fail is not known to work.

- [ ] **Step 5: Commit**

```bash
git add agentarea-platform/apps/api/tests/test_route_authz_inventory.py \
        agentarea-platform/apps/api/tests/route_authz_inventory.json
git commit -m "test(authz): ratchet the route authorization inventory"
```

---

### Task 6: Verify the admin tuples exist in every environment

**Files:**
- Read only: `agentarea-platform/scripts/20260722_backfill_resource_authz.py`

**Interfaces:**
- Consumes: the deployed OpenFGA store; `POST /v1/access-control/check`.
- Produces: no code. A recorded answer per environment, and a re-run of the idempotent backfill wherever the answer is no.

This task is a runbook, not an edit. Task 1 makes admin real; if a workspace has no `admin` tuple, its owner is locked out of policy, wallet and graph writes the moment Task 2 ships. The backfill script already writes these tuples (`:64`), so the question is only whether it has been run everywhere.

- [ ] **Step 1: Check one known workspace per environment**

For each environment, with an owner's token:

```bash
curl -s -X POST "$API/v1/access-control/check" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"namespace":"Workspace","object":"'"$WORKSPACE_ID"'","relation":"admin","subject_id":"User:'"$OWNER_USER_ID"'"}'
```

Expected: `{"allowed": true}`. Note that this endpoint is itself admin-gated, so run it before Task 2 deploys, while the gate still admits any member.

- [ ] **Step 2: Enumerate workspaces missing an owner admin tuple**

Run the backfill in its reporting mode against each environment, following the usage block at the top of `scripts/20260722_backfill_resource_authz.py`. It is idempotent: existing tuples are skipped, so a re-run is safe even where it has already been applied.

- [ ] **Step 3: Record the result before deploying Task 2**

Write the per-environment answer into the PR body: environment, workspace count, tuples written. A deploy of Task 2 without this recorded is a deploy that might lock out an owner, and the symptom — 403 on policy and wallet writes for the person who owns the workspace — looks identical to the bug this plan fixes.

---

## Out of scope — the next plans

This plan makes the existing gates deny. It does not change who may see what. Explicitly deferred, in order:

1. **Least-privilege membership.** Tasks become `resource:<id>` objects via `grant_resource_owner`; invitations write a `role_assignment` on `project:<ws>-root` carrying a chosen role; task reads filter through the graph; existing members are backfilled to a reader role. One PR — splitting it either breaks invitations or leaves reads unguarded. No model change needed.
2. **Sharing and explainability.** Per-agent and per-task grants, which need one additive model edge (`resource#parent: [resource]`); `expand` on `OpenFGAClient`; `/access-control/resolve` generalized off its four hardcoded kinds and made to show inherited hops.
3. **Actor-aware policy.** The per-user policy layer is resolved from the task creator (`resolver_adapter.py:71`), so a guest writing into someone else's conversation runs under the owner's spend cap. Requires deciding how the snapshot in `execution_state` is refreshed mid-task.
4. **The remaining ungated surface.** 237 endpoints today, frozen by Task 5. Secrets writes, provider configs, triggers, projects, registries and clients each need a gate decision. The ratchet makes this a shrinking number rather than a sweep.
