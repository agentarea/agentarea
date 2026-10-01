# Plugin Architecture, IaC Config & Permission Service

**Date:** 2026-03-16
**Status:** Draft
**Branch:** jamakase/infra-fix

## Problem

AgentArea needs three related capabilities:

1. **Infrastructure-as-Code configuration** for system-level MCP servers, agents, skills, and models — avoiding manual DB creation through the UI.
2. **Permission service** that protects system entities in cloud deployments while keeping OSS unrestricted.
3. **Plugin architecture** that cleanly separates OSS from enterprise code, allowing enterprise features (Keto ReBAC, audit logging, billing, etc.) to be added without modifying OSS.

These are interconnected: the permission service is the first plugin, and system entity protection depends on both the permission service and the IaC reconciler.

## Design

### 1. Plugin/Extension Architecture

#### Overview

The OSS codebase defines extension points (abstract interfaces). Enterprise features register implementations via Python entrypoints. At startup, the DI container discovers and wires them in automatically.

#### Extension Registry

```
agentarea-platform/libs/common/agentarea_common/extensions/
  __init__.py
  registry.py       # ExtensionRegistry class
  discovery.py      # Entrypoint scanning + DI wiring
```

**ExtensionRegistry** maintains a mapping of interface name to factory callable:

```python
class ExtensionRegistry:
    _factories: dict[str, Callable[[], Any]] = {}

    @classmethod
    def register(cls, interface: str, factory: Callable[[], Any]):
        """Register a factory that creates an extension instance."""
        cls._factories[interface] = factory

    @classmethod
    def get_factory(cls, interface: str) -> Callable[[], Any] | None:
        return cls._factories.get(interface)

    @classmethod
    def has(cls, interface: str) -> bool:
        return interface in cls._factories

    @classmethod
    def clear(cls):
        """Clear all registrations (for testing)."""
        cls._factories.clear()
```

Note: Uses factory callables (not raw classes) so enterprise implementations can receive their own dependencies (e.g., `KetoPermissionService` needs a `keto_client`).

**Discovery** scans Python entrypoints at startup:

```python
from importlib.metadata import entry_points

def discover_extensions():
    """Scan installed packages for agentarea extensions.

    Each entrypoint must point to a factory callable that returns
    an instance of the corresponding interface.
    """
    for ep in entry_points(group="agentarea.extensions"):
        factory = ep.load()
        ExtensionRegistry.register(ep.name, factory)
```

Called once during application startup (in `main.py` and worker entrypoint), before DI container initialization.

#### Extension Points

Each extension point is an ABC in the OSS codebase with an OSS default implementation:

| Extension Point | Interface | OSS Default | Enterprise Example |
|---|---|---|---|
| `permissions` | `PermissionService` | `SimplePermissionService` | `KetoPermissionService` |
| `audit` | `AuditService` | `NoOpAuditService` | `StructuredAuditService` |
| `quotas` | `QuotaService` | `UnlimitedQuotaService` | `UsageMeteringService` |
| `governance` | `GovernanceService` | `NoOpGovernanceService` | `PolicyEngineService` |

Only `permissions` is implemented in this change. Others are listed to show the pattern scales.

#### DI Wiring

During container initialization. Note: `register_singleton` takes an **instance**, `register_factory` takes a **callable**:

```python
from agentarea_common.extensions import ExtensionRegistry, discover_extensions

# 1. Discover plugins (call once at startup)
discover_extensions()

# 2. Wire permission service
# Use enterprise factory if registered, otherwise OSS default
perm_factory = ExtensionRegistry.get_factory("permissions")
if perm_factory:
    container.register_factory(PermissionService, perm_factory)
else:
    container.register_singleton(PermissionService, SimplePermissionService())
```

The enterprise factory handles its own dependency construction:

```python
# In agentarea-enterprise, the entrypoint points to this factory:
def create_keto_permission_service() -> KetoPermissionService:
    keto_client = OryKetoClient(url=os.environ["KETO_READ_URL"])
    return KetoPermissionService(keto_client)
```

### 2. Feature Service

> **Scope note:** The plugin discovery mechanism IS the primary feature toggle for implementation swapping. `FeatureService` is for behaviors that are NOT plugin-driven — UI presentation, API response shape, rate limits, etc.

Controls deployment-mode-specific behaviors that don't warrant a full plugin. Lives in `agentarea_common/features/`.

```python
class DeploymentMode(str, Enum):
    OSS = "oss"
    ENTERPRISE = "enterprise"

class FeatureService:
    def __init__(self, mode: DeploymentMode = DeploymentMode.OSS):
        self.mode = mode

    @property
    def show_system_entity_badge(self) -> bool:
        """UI: show 'System' badge on system entities."""
        return self.mode == DeploymentMode.ENTERPRISE

    @property
    def system_entities_read_only_in_ui(self) -> bool:
        """UI: disable edit controls for system entities."""
        return self.mode == DeploymentMode.ENTERPRISE

    @property
    def enable_usage_metering(self) -> bool:
        return self.mode == DeploymentMode.ENTERPRISE
```

- Configured via `DEPLOYMENT_MODE` env var (defaults to `oss`).
- Registered as singleton in DI container: `container.register_singleton(FeatureService, FeatureService(mode))`.
- Does NOT control which `PermissionService` implementation is used — that's determined by plugin discovery.

**Location:** `agentarea-platform/libs/common/agentarea_common/features/service.py`

### 3. Permission Service

#### Interface

```python
# agentarea_common/auth/permission.py

class PermissionService(ABC):
    @abstractmethod
    async def check(
        self,
        user_id: str,
        permission: str,
        resource_type: str,
        resource_id: str,
    ) -> bool:
        """Check if user has permission on a resource.

        Args:
            user_id: The user requesting access.
            permission: Action being performed (view, edit, delete, execute).
            resource_type: Entity type (agent, mcp_server, skill, model, trigger, etc.).
            resource_id: ID of the specific resource.

        Returns:
            True if allowed, False if denied.
        """
        ...
```

#### OSS Implementation

```python
# agentarea_common/auth/simple_permission.py

class SimplePermissionService(PermissionService):
    """Workspace-scoped permission checks. No external dependencies."""

    async def check(self, user_id, permission, resource_type, resource_id) -> bool:
        # OSS: all operations allowed within workspace scope.
        # Workspace isolation is enforced at the repository layer.
        return True
```

The OSS implementation trusts the repository layer's existing workspace scoping. No additional restrictions — self-hosters have full control.

#### Enterprise Implementation (in `agentarea-enterprise` repo)

```python
# agentarea_enterprise/permissions/keto.py

class KetoPermissionService(PermissionService):
    """Keto ReBAC permission checks."""

    def __init__(self, keto_client: OryKetoClient):
        self.keto = keto_client

    async def check(self, user_id, permission, resource_type, resource_id) -> bool:
        return await self.keto.check(
            namespace=resource_type,
            object=resource_id,
            relation=permission,
            subject_id=user_id,
        )
```

Keto relation tuples define the permission model:

```
# System entities owned by "system" — no user has edit/delete
workspace:system#owner@system

# User owns their agent
agent:abc-123#owner@user:alice

# Workspace members can view workspace resources
workspace:ws-1#member@user:alice
agent:abc-123#parent@workspace:ws-1

# Permission derivation (in Keto namespace config):
# owner of agent can edit, delete
# member of parent workspace can view
# owner of parent workspace can edit, delete
```

**Keto bootstrap:** The enterprise package includes `keto_bootstrap.py` that seeds system relation tuples on startup (e.g., `workspace:system#owner@system`). This runs as part of the bootstrap job when the enterprise package is installed. The "system" subject is synthetic — no JWT maps to it, which is why no user can edit system entities.

#### API Integration

An imperative helper function called inside endpoint bodies (not a FastAPI `Depends`):

```python
# agentarea_common/auth/permission.py

async def require_permission(
    permission: str,
    resource_type: str,
    resource_id: str,
    user_id: str,
) -> None:
    """Check permission and raise 403 if denied.

    Resolves PermissionService from the DI container.
    """
    from agentarea_common.di.container import resolve
    perm_service = resolve(PermissionService)
    if not await perm_service.check(user_id, permission, resource_type, resource_id):
        raise HTTPException(status_code=403, detail="Permission denied")
```

Used in endpoints:

```python
@router.patch("/{agent_id}")
async def update_agent(
    agent_id: UUID,
    data: AgentUpdate,
    user: UserContextDep,
):
    await require_permission("edit", "agent", str(agent_id), user.user_id)
    # ... existing update logic
```

### 4. IaC Config Reconciler

#### Overview

Extends the existing bootstrap system to be idempotent and run on every deploy. Reads YAML config files and upserts system entities into the DB. This is an **additive-only applier** — entities are created and updated but never deleted. Removing an entry from YAML does not delete it from the DB. This is a deliberate safety choice: accidental YAML truncation should not wipe production system entities.

#### YAML Format

Extends existing seed data format in `charts/agentarea/seed-data/`:

```yaml
# mcp_servers.yaml (extends existing mcp_providers.yaml)
mcp_servers:
  - name: github-mcp
    description: "GitHub integration via MCP"
    docker_image_url: ghcr.io/modelcontextprotocol/github
    version: "1.0.0"
    cmd: ["node", "dist/index.js"]
    tags: ["vcs", "github"]
    env_schema:
      GITHUB_TOKEN:
        type: string
        required: true
        secret: true
        secret_ref: github-mcp-token  # K8s Secret reference

# agents.yaml (extends existing)
agents:
  - name: code-reviewer
    description: "Automated code review agent"
    instruction: |
      You are a code review agent. Review PRs for quality, security, and style.
    model: claude-sonnet-4-20250514
    tools:
      - type: mcp
        name: github-mcp
      - type: code
        name: file_read
    skills:
      - code-review-skill

# skills.yaml
skills:
  - name: code-review-skill
    source_type: content
    content: |
      Review code for: security vulnerabilities, performance issues, style violations.

# models.yaml
models:
  providers:
    - name: anthropic
      provider_type: anthropic
      env_schema:
        ANTHROPIC_API_KEY:
          secret: true
          secret_ref: anthropic-api-key
  instances:
    - name: claude-sonnet
      provider: anthropic
      model_spec: claude-sonnet-4-20250514
```

#### Secret References

YAML files reference K8s Secrets by name, never contain actual secret values:

```yaml
env_schema:
  GITHUB_TOKEN:
    secret: true
    secret_ref: github-mcp-token  # Name of K8s Secret
```

At instance activation time, the MCP Manager resolves `secret_ref` to actual values from K8s Secrets. This keeps YAML files safe to commit to git.

Note: The reconciler creates MCP server **specs** (not instances). Instance creation with secret resolution is a separate step — either via the UI, API, or a future IaC extension for instance lifecycle.

#### Reconciler Service

```
agentarea-platform/libs/common/agentarea_common/reconciler/
  __init__.py
  service.py         # ReconcilerService
  parsers.py         # YAML parsing + validation for each entity type
```

**Data access strategy:** The reconciler uses async SQLAlchemy sessions with a synthetic `SystemUserContext`:

```python
# Constant for reconciler and bootstrap operations
SYSTEM_USER_CONTEXT = UserContext(
    user_id="system",
    workspace_id="system",
    roles=[],
)
```

The reconciler uses raw async SQLAlchemy queries (not the workspace-scoped repositories) because:
1. The existing bootstrap scripts use raw SQL — this is consistent.
2. Workspace-scoped repositories filter OUT system entities by default, making them unsuitable for upserting system entities.
3. The reconciler is a trusted internal process, not a user-facing API — repository-level guards are unnecessary.

```python
class ReconcilerService:
    """Additive-only config applier: YAML -> DB for system entities.

    Creates new entities and updates existing ones. Never deletes.
    All entities are created with workspace_id='system', created_by='system'.
    """

    def __init__(self, session_factory: async_sessionmaker):
        self._session_factory = session_factory

    async def reconcile(self, config_dir: str) -> ReconcileResult:
        """Read all YAML files from config_dir and upsert into DB.

        Returns a ReconcileResult with counts of created/updated/errored entities.
        Continues on per-entity errors (logs and collects, doesn't abort).
        """
        result = ReconcileResult()
        for entity_type in ["mcp_servers", "agents", "skills", "models"]:
            file = Path(config_dir) / f"{entity_type}.yaml"
            if not file.exists():
                continue
            try:
                specs = parse_yaml(file, entity_type)
            except YAMLValidationError as e:
                logger.error(f"Invalid YAML in {file}: {e}")
                result.add_error(entity_type, str(e))
                continue
            await self._upsert_entities(entity_type, specs, result)
        return result

    async def _upsert_entities(self, entity_type, specs, result):
        """Upsert with workspace_id='system', created_by='system'."""
        async with self._session_factory() as session:
            for spec in specs:
                try:
                    existing = await session.execute(
                        select(model_class).where(
                            model_class.name == spec.name,
                            model_class.workspace_id == "system",
                        )
                    )
                    entity = existing.scalar_one_or_none()
                    if entity:
                        for key, value in spec.to_update_dict().items():
                            setattr(entity, key, value)
                        result.updated += 1
                    else:
                        entity = model_class(**spec.to_create_dict(),
                                             workspace_id="system",
                                             created_by="system")
                        session.add(entity)
                        result.created += 1
                    await session.commit()
                except Exception as e:
                    await session.rollback()
                    logger.error(f"Failed to upsert {entity_type} '{spec.name}': {e}")
                    result.add_error(entity_type, str(e))
```

#### Bootstrap Integration

The existing bootstrap job (`charts/agentarea/templates/jobs/bootstrap-job.yaml`) already runs on every deploy (it's a standard K8s Job, not a Helm hook — hooks were already removed per the template's comment). Changes:

1. The bootstrap container entrypoint calls `ReconcilerService.reconcile()` via `asyncio.run()` instead of individual `populate_*.py` scripts.
2. Existing `populate_*.py` scripts remain as-is during migration (reconciler replaces them incrementally).
3. Seed data checksum annotation already forces re-runs when ConfigMap content changes.

#### Concurrent reconciliation safety

The bootstrap job has `ttlSecondsAfterFinished: 300` and Kubernetes ensures only one Job pod runs. For additional safety, the reconciler uses per-entity commits (not a single transaction) so partial failures don't block the entire reconciliation.

### 5. System Entity Visibility

**Problem:** Several repositories lack `include_system` support. Entities created with `workspace_id="system"` are invisible to users in those repositories.

Currently, only `MCPServerRepository` and `AgentRepository` override the workspace filter to include system entities. The following repositories need the same treatment:

| Repository | File | Change |
|---|---|---|
| `ModelInstanceRepository` | `libs/llm/agentarea_llm/infrastructure/repository.py` | Add `include_system` filter |
| `ModelSpecRepository` | `libs/llm/agentarea_llm/infrastructure/repository.py` | Add `include_system` filter |
| `ProviderConfigRepository` | `libs/llm/agentarea_llm/infrastructure/repository.py` | Add `include_system` filter |
| `SkillRepository` | `libs/agents/agentarea_agents/infrastructure/skill_repository.py` | Already has system support — verify |

The pattern (from `MCPServerRepository`):

```python
def _get_workspace_filter(self):
    return or_(
        self.model_class.workspace_id == self.user_context.workspace_id,
        (self.model_class.workspace_id == "system") & self.model_class.is_public,
    )
```

**Reserved workspace ID:** Add validation in workspace creation to reject `"system"` as a workspace name, preventing users from creating a workspace that collides with system entities.

### 6. System Entity Protection

No special `managed_by` field needed. Protection is handled entirely through the permission service:

- **OSS**: `SimplePermissionService` allows all operations. Self-hosters can modify system entities freely.
- **Enterprise**: `KetoPermissionService` checks Keto. System entities have `workspace:system#owner@system` — no user has the `edit`/`delete` relation, so mutations are denied.

The UI uses `FeatureService.system_entities_read_only_in_ui` to determine whether to disable edit controls for system entities (presentational only — enforcement is server-side).

### 7. Enterprise Package Structure

Separate private repository (not part of this monorepo):

```
agentarea-enterprise/
  pyproject.toml
  agentarea_enterprise/
    __init__.py
    permissions/
      __init__.py
      keto.py              # KetoPermissionService
      keto_config.py       # Namespace configs
      keto_bootstrap.py    # Seed system relations on startup
      factory.py           # create_keto_permission_service() entrypoint
```

**pyproject.toml** registers the extension via entrypoints:

```toml
[project]
name = "agentarea-enterprise"
version = "0.1.0"
dependencies = [
    "agentarea-common",    # For interfaces (verify distribution name)
    "ory-keto-client",     # Keto SDK
]

[project.entry-points."agentarea.extensions"]
permissions = "agentarea_enterprise.permissions.factory:create_keto_permission_service"
```

**Cloud Docker build** includes `agentarea-enterprise`:

```dockerfile
# Cloud-only layer
RUN pip install agentarea-enterprise --extra-index-url https://private.registry/
```

**OSS Docker build** does not — `SimplePermissionService` is used automatically.

### 8. Observability

- **Reconciler**: logs created/updated/errored counts per entity type at INFO level. Returns `ReconcileResult` for structured reporting.
- **Permission checks**: `require_permission` logs denials at WARNING level with user_id, resource_type, resource_id.
- **Extension discovery**: logs each discovered extension at INFO level during startup.

### 9. Startup Integration

Both the API process (`apps/api/agentarea_api/main.py`) and the Temporal worker (`apps/worker/`) must call `discover_extensions()` at startup, before DI container initialization. Both processes use the DI container and may need permission checks (worker for agent execution authorization).

## File Changes Summary

### New Files (OSS — `agentarea-platform`)

| File | Purpose |
|---|---|
| `libs/common/agentarea_common/extensions/__init__.py` | Extension module exports |
| `libs/common/agentarea_common/extensions/registry.py` | ExtensionRegistry class |
| `libs/common/agentarea_common/extensions/discovery.py` | Entrypoint scanning |
| `libs/common/agentarea_common/features/__init__.py` | Feature module |
| `libs/common/agentarea_common/features/service.py` | FeatureService + DeploymentMode |
| `libs/common/agentarea_common/auth/permission.py` | PermissionService ABC + require_permission helper |
| `libs/common/agentarea_common/auth/simple_permission.py` | OSS implementation |
| `libs/common/agentarea_common/reconciler/__init__.py` | Reconciler module |
| `libs/common/agentarea_common/reconciler/service.py` | ReconcilerService |
| `libs/common/agentarea_common/reconciler/parsers.py` | YAML parsing + validation |

### Modified Files (OSS)

| File | Change |
|---|---|
| `apps/api/agentarea_api/main.py` | Call `discover_extensions()` at startup |
| `apps/worker/agentarea_worker/main.py` | Call `discover_extensions()` at startup |
| `libs/common/agentarea_common/di/container.py` | Register PermissionService + FeatureService |
| `libs/common/agentarea_common/config/app.py` | Add `DEPLOYMENT_MODE` setting |
| `libs/llm/agentarea_llm/infrastructure/repository.py` | Add `include_system` to ModelInstance, ModelSpec, ProviderConfig repos |
| `apps/api/agentarea_api/api/v1/agents.py` | Add `require_permission` on update/delete |
| `apps/api/agentarea_api/api/v1/mcp_servers_specifications.py` | Add `require_permission` on update/delete |
| `apps/api/agentarea_api/api/v1/skills.py` | Add `require_permission` on update/delete |
| `apps/api/agentarea_api/api/v1/model_instances.py` | Add `require_permission` on update/delete |
| `agentarea-bootstrap/code/__init__.py` | Add async reconciler entrypoint |

### New Files (Enterprise — separate `agentarea-enterprise` repo)

| File | Purpose |
|---|---|
| `pyproject.toml` | Package config + entrypoints |
| `agentarea_enterprise/__init__.py` | Package init |
| `agentarea_enterprise/permissions/__init__.py` | Permissions module |
| `agentarea_enterprise/permissions/keto.py` | KetoPermissionService |
| `agentarea_enterprise/permissions/keto_config.py` | Keto namespace config |
| `agentarea_enterprise/permissions/keto_bootstrap.py` | Seed system relations |
| `agentarea_enterprise/permissions/factory.py` | Entrypoint factory function |

## Test Strategy

| Component | Test Type | What to verify |
|---|---|---|
| ExtensionRegistry | Unit | register, get_factory, clear, no-op when empty |
| discover_extensions | Unit | Mock entrypoints, verify registration |
| SimplePermissionService | Unit | Always returns True |
| require_permission | Unit | Resolves from DI, raises 403 on denial |
| ReconcilerService | Integration | Upsert idempotency, error handling, YAML validation |
| System entity visibility | Integration | Repos return system entities alongside workspace entities |
| Permission in endpoints | Functional | 403 when enterprise denies, 200 when OSS allows |
| KetoPermissionService | Integration (enterprise) | Keto check calls, relation tuple evaluation |

## Rollout Plan

1. **Phase 1**: Plugin architecture + Feature service + Permission service interface + OSS implementation
2. **Phase 2**: System entity visibility fixes (repository changes) + require_permission in API endpoints
3. **Phase 3**: IaC reconciler (extend bootstrap)
4. **Phase 4**: Enterprise package scaffold with Keto integration
5. **Phase 5**: UI read-only indicators for system entities

Phases 1-3 can ship together as one PR. Phase 4 is in the enterprise repo. Phase 5 is a frontend change.
