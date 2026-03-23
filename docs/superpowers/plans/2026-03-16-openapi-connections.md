# OpenAPI Connections Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add ability to register OpenAPI services, parse specs, and store discovered tools as `openapi_connections`.

**Architecture:** New `agentarea_openapi` library in `libs/openapi/` following the same layered pattern as `agentarea_mcp` (domain model, repository, service, API router). Reuses existing `mcp_auth_configs` for auth. OpenAPI spec parsing converts operations to the same tool format used by MCP.

**Tech Stack:** Python 3.12, SQLAlchemy (async), FastAPI, Pydantic v2, httpx, pyyaml (for YAML specs)

**Spec:** `docs/superpowers/specs/2026-03-16-openapi-connections-design.md`

---

## File Structure

```
libs/openapi/
  pyproject.toml
  agentarea_openapi/
    __init__.py
    domain/
      __init__.py
      models.py                # OpenAPIConnection SQLAlchemy model
    infrastructure/
      __init__.py
      repository.py            # CRUD repository
    application/
      __init__.py
      service.py               # Business logic + discover_tools
      spec_parser.py           # OpenAPI spec -> tool definitions

apps/api/agentarea_api/api/v1/
  openapi_connections.py       # FastAPI router (new file)

apps/api/agentarea_api/api/deps/
  services.py                  # Add get_openapi_connection_service (modify)

apps/api/agentarea_api/api/v1/
  router.py                    # Register new router (modify)

apps/api/alembic/versions/
  009_add_openapi_connections_table.py  # Migration (new file)
```

---

## Chunk 1: Library Scaffolding + Domain Model

### Task 1: Create library scaffolding

**Files:**
- Create: `libs/openapi/pyproject.toml`
- Create: `libs/openapi/agentarea_openapi/__init__.py`
- Create: `libs/openapi/agentarea_openapi/domain/__init__.py`
- Create: `libs/openapi/agentarea_openapi/infrastructure/__init__.py`
- Create: `libs/openapi/agentarea_openapi/application/__init__.py`
- Modify: `pyproject.toml` (root workspace)

- [ ] **Step 1: Create `libs/openapi/pyproject.toml`**

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "agentarea-openapi"
version = "0.0.1"
description = "OpenAPI connection management for AgentArea"
license = {text = "Apache-2.0"}
requires-python = ">=3.12"
dependencies = [
    "agentarea-common",
    "pydantic>=2.4.2",
    "httpx>=0.25.0",
    "pyyaml>=6.0",
]

[tool.uv.sources]
agentarea-common = { workspace = true }

[tool.hatch.build.targets.wheel]
packages = ["agentarea_openapi"]
```

- [ ] **Step 2: Create empty `__init__.py` files**

```
libs/openapi/agentarea_openapi/__init__.py          # empty
libs/openapi/agentarea_openapi/domain/__init__.py    # empty
libs/openapi/agentarea_openapi/infrastructure/__init__.py  # empty
libs/openapi/agentarea_openapi/application/__init__.py     # empty
```

- [ ] **Step 3: Register in root workspace**

In `pyproject.toml` (root), add `"libs/openapi"` to `[tool.uv.workspace]` members list.

- [ ] **Step 4: Install dependencies**

Run: `uv sync`
Expected: no errors, new package resolves

- [ ] **Step 5: Commit**

```bash
git add libs/openapi/ pyproject.toml
git commit -m "chore: scaffold agentarea-openapi library"
```

---

### Task 2: Domain model

**Files:**
- Create: `libs/openapi/agentarea_openapi/domain/models.py`
- Create: `libs/openapi/tests/__init__.py`
- Create: `libs/openapi/tests/test_models.py`

- [ ] **Step 1: Write the failing test**

Create `libs/openapi/tests/__init__.py` (empty) and `libs/openapi/tests/test_models.py`:

```python
"""Tests for OpenAPIConnection domain model."""

from agentarea_openapi.domain.models import OpenAPIConnection


class TestOpenAPIConnectionModel:
    def test_create_with_spec_url(self):
        conn = OpenAPIConnection(
            name="Stripe API",
            base_url="https://api.stripe.com",
            spec_url="https://raw.githubusercontent.com/stripe/openapi/master/openapi/spec3.json",
        )
        assert conn.name == "Stripe API"
        assert conn.base_url == "https://api.stripe.com"
        assert conn.spec_url is not None
        assert conn.status == "active"
        assert conn.available_tools == []

    def test_create_with_spec_content(self):
        spec = {"openapi": "3.0.0", "paths": {}}
        conn = OpenAPIConnection(
            name="Internal API",
            base_url="https://internal.example.com",
            spec_content=spec,
        )
        assert conn.spec_content == spec
        assert conn.spec_url is None

    def test_create_minimal(self):
        """Connection can exist with just base_url — tools discovered later."""
        conn = OpenAPIConnection(
            name="My API",
            base_url="https://api.example.com",
        )
        assert conn.spec_url is None
        assert conn.spec_content is None
        assert conn.available_tools == []

    def test_get_and_set_available_tools(self):
        conn = OpenAPIConnection(
            name="Test API",
            base_url="https://api.example.com",
        )
        tools = [
            {"name": "listUsers", "description": "List users", "inputSchema": {"type": "object"}},
        ]
        conn.available_tools = tools
        assert conn.available_tools == tools
        assert len(conn.available_tools) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest libs/openapi/tests/test_models.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agentarea_openapi.domain.models'`

- [ ] **Step 3: Write the model**

Create `libs/openapi/agentarea_openapi/domain/models.py`:

```python
"""Domain model for OpenAPI connections."""

from typing import Any
from uuid import UUID

from agentarea_common.base.models import BaseModel, WorkspaceScopedMixin
from sqlalchemy import JSON, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column


class OpenAPIConnection(BaseModel, WorkspaceScopedMixin):
    """An OpenAPI-based REST API connection.

    Stores the OpenAPI spec and discovered tools. No lifecycle management
    (no start/stop) — these are always-on external APIs.
    """

    __tablename__ = "openapi_connections"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    spec_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    spec_content: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    base_url: Mapped[str] = mapped_column(String(500), nullable=False)
    auth_config_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("mcp_auth_configs.id", ondelete="SET NULL"),
        nullable=True,
    )
    available_tools: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, nullable=False, default=list
    )
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="active")

    def __init__(
        self,
        name: str,
        base_url: str,
        description: str | None = None,
        spec_url: str | None = None,
        spec_content: dict[str, Any] | None = None,
        auth_config_id: UUID | None = None,
        available_tools: list[dict[str, Any]] | None = None,
        status: str = "active",
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.name = name
        self.base_url = base_url
        self.description = description
        self.spec_url = spec_url
        self.spec_content = spec_content
        self.auth_config_id = auth_config_id
        self.available_tools = available_tools or []
        self.status = status
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run python -m pytest libs/openapi/tests/test_models.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add libs/openapi/agentarea_openapi/domain/models.py libs/openapi/tests/
git commit -m "feat(openapi): add OpenAPIConnection domain model"
```

---

## Chunk 2: Spec Parser

### Task 3: OpenAPI spec parser

**Files:**
- Create: `libs/openapi/agentarea_openapi/application/spec_parser.py`
- Create: `libs/openapi/tests/test_spec_parser.py`

- [ ] **Step 1: Write the failing tests**

Create `libs/openapi/tests/test_spec_parser.py`:

```python
"""Tests for OpenAPI spec parser."""

import pytest

from agentarea_openapi.application.spec_parser import parse_openapi_spec


SAMPLE_SPEC = {
    "openapi": "3.0.0",
    "info": {"title": "Test API", "version": "1.0.0"},
    "paths": {
        "/users": {
            "get": {
                "operationId": "listUsers",
                "summary": "List all users",
                "parameters": [
                    {"name": "page", "in": "query", "schema": {"type": "integer"}},
                    {"name": "limit", "in": "query", "schema": {"type": "integer"}},
                ],
            },
            "post": {
                "operationId": "createUser",
                "summary": "Create a user",
                "requestBody": {
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "properties": {
                                    "name": {"type": "string"},
                                    "email": {"type": "string"},
                                },
                                "required": ["name", "email"],
                            }
                        }
                    }
                },
            },
        },
        "/users/{user_id}": {
            "get": {
                "operationId": "getUser",
                "summary": "Get a user by ID",
                "parameters": [
                    {
                        "name": "user_id",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "string"},
                    }
                ],
            },
        },
    },
}


class TestParseOpenAPISpec:
    def test_extracts_all_operations(self):
        tools = parse_openapi_spec(SAMPLE_SPEC)
        names = [t["name"] for t in tools]
        assert "listUsers" in names
        assert "createUser" in names
        assert "getUser" in names
        assert len(tools) == 3

    def test_uses_operation_id(self):
        tools = parse_openapi_spec(SAMPLE_SPEC)
        tool = next(t for t in tools if t["name"] == "listUsers")
        assert tool["description"] == "List all users"

    def test_query_params_in_input_schema(self):
        tools = parse_openapi_spec(SAMPLE_SPEC)
        tool = next(t for t in tools if t["name"] == "listUsers")
        props = tool["inputSchema"]["properties"]
        assert "page" in props
        assert "limit" in props
        assert props["page"]["type"] == "integer"

    def test_path_params_are_required(self):
        tools = parse_openapi_spec(SAMPLE_SPEC)
        tool = next(t for t in tools if t["name"] == "getUser")
        assert "user_id" in tool["inputSchema"]["properties"]
        assert "user_id" in tool["inputSchema"]["required"]

    def test_request_body_as_body_property(self):
        tools = parse_openapi_spec(SAMPLE_SPEC)
        tool = next(t for t in tools if t["name"] == "createUser")
        assert "body" in tool["inputSchema"]["properties"]
        body_schema = tool["inputSchema"]["properties"]["body"]
        assert "name" in body_schema["properties"]
        assert "email" in body_schema["properties"]

    def test_fallback_name_without_operation_id(self):
        spec = {
            "openapi": "3.0.0",
            "info": {"title": "Test", "version": "1.0.0"},
            "paths": {
                "/orders/{order_id}/items": {
                    "get": {
                        "summary": "List order items",
                        "parameters": [
                            {"name": "order_id", "in": "path", "required": True, "schema": {"type": "string"}}
                        ],
                    }
                }
            },
        }
        tools = parse_openapi_spec(spec)
        assert len(tools) == 1
        assert tools[0]["name"] == "get_orders_order_id_items"

    def test_empty_paths(self):
        spec = {"openapi": "3.0.0", "info": {"title": "Empty", "version": "1.0.0"}, "paths": {}}
        tools = parse_openapi_spec(spec)
        assert tools == []

    def test_rejects_swagger_2(self):
        spec = {"swagger": "2.0", "info": {"title": "Old", "version": "1.0.0"}, "paths": {}}
        with pytest.raises(ValueError, match="OpenAPI 3.x"):
            parse_openapi_spec(spec)

    def test_operation_with_no_params_or_body(self):
        spec = {
            "openapi": "3.0.0",
            "info": {"title": "Test", "version": "1.0.0"},
            "paths": {"/health": {"get": {"operationId": "healthCheck", "summary": "Health check"}}},
        }
        tools = parse_openapi_spec(spec)
        assert len(tools) == 1
        assert tools[0]["inputSchema"]["properties"] == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest libs/openapi/tests/test_spec_parser.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write the spec parser**

Create `libs/openapi/agentarea_openapi/application/spec_parser.py`:

```python
"""Parse OpenAPI 3.x specs into tool definitions."""

import re
from typing import Any


def parse_openapi_spec(spec: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract operations from an OpenAPI 3.x spec as tool definitions.

    Each operation becomes a tool with:
    - name: operationId or generated from method + path
    - description: summary or description
    - inputSchema: merged path params, query params, and request body

    Raises ValueError for non-OpenAPI 3.x specs.
    """
    if "swagger" in spec:
        raise ValueError("Swagger 2.0 specs are not supported. Please convert to OpenAPI 3.x.")

    openapi_version = spec.get("openapi", "")
    if not openapi_version.startswith("3."):
        raise ValueError(f"Only OpenAPI 3.x specs are supported, got: {openapi_version!r}")

    paths = spec.get("paths", {})
    tools: list[dict[str, Any]] = []

    for path, path_item in paths.items():
        for method in ("get", "post", "put", "patch", "delete", "head", "options"):
            if method not in path_item:
                continue

            operation = path_item[method]
            name = operation.get("operationId") or _generate_name(method, path)
            description = operation.get("summary") or operation.get("description") or ""

            input_schema = _build_input_schema(operation)

            tools.append({
                "name": name,
                "description": description,
                "inputSchema": input_schema,
            })

    return tools


def _generate_name(method: str, path: str) -> str:
    """Generate a tool name from HTTP method + path.

    /users/{user_id}/orders -> get_users_user_id_orders
    """
    cleaned = re.sub(r"[{}]", "", path)
    segments = [s for s in cleaned.split("/") if s]
    return f"{method}_{'_'.join(segments)}"


def _build_input_schema(operation: dict[str, Any]) -> dict[str, Any]:
    """Build a JSON Schema from operation parameters and request body."""
    properties: dict[str, Any] = {}
    required: list[str] = []

    for param in operation.get("parameters", []):
        param_name = param.get("name", "")
        if not param_name:
            continue

        param_schema = param.get("schema", {"type": "string"})
        properties[param_name] = param_schema

        if param.get("required", False):
            required.append(param_name)

    request_body = operation.get("requestBody")
    if request_body:
        content = request_body.get("content", {})
        json_content = content.get("application/json", {})
        body_schema = json_content.get("schema")
        if body_schema:
            properties["body"] = body_schema
            if request_body.get("required", True):
                required.append("body")

    return {
        "type": "object",
        "properties": properties,
        "required": required,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run python -m pytest libs/openapi/tests/test_spec_parser.py -v`
Expected: 9 passed

- [ ] **Step 5: Commit**

```bash
git add libs/openapi/agentarea_openapi/application/spec_parser.py libs/openapi/tests/test_spec_parser.py
git commit -m "feat(openapi): add OpenAPI spec parser with tool extraction"
```

---

## Chunk 3: Repository + Service

### Task 4: Repository

**Files:**
- Create: `libs/openapi/agentarea_openapi/infrastructure/repository.py`

- [ ] **Step 1: Write the repository**

```python
"""Repository for OpenAPIConnection CRUD operations."""

from agentarea_common.auth.context import UserContext
from agentarea_common.base.workspace_scoped_repository import WorkspaceScopedRepository
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from agentarea_openapi.domain.models import OpenAPIConnection


class OpenAPIConnectionRepository(WorkspaceScopedRepository[OpenAPIConnection]):
    def __init__(self, session: AsyncSession, user_context: UserContext):
        super().__init__(session, OpenAPIConnection, user_context)

    async def list_connections(
        self,
        status: str | None = None,
        search: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[OpenAPIConnection], int]:
        query = select(self.model_class).where(self._get_workspace_filter())

        if status:
            query = query.where(self.model_class.status == status)
        if search:
            pattern = f"%{search}%"
            query = query.where(
                or_(
                    self.model_class.name.ilike(pattern),
                    self.model_class.description.ilike(pattern),
                )
            )

        count_query = select(func.count()).select_from(query.subquery())
        total = (await self.session.execute(count_query)).scalar_one()

        query = query.order_by(self.model_class.created_at.desc())
        if offset > 0:
            query = query.offset(offset)
        if limit > 0:
            query = query.limit(limit)

        result = await self.session.execute(query)
        return list(result.scalars().all()), total
```

- [ ] **Step 2: Commit**

```bash
git add libs/openapi/agentarea_openapi/infrastructure/repository.py
git commit -m "feat(openapi): add OpenAPIConnection repository"
```

---

### Task 5: Service with discover_tools

**Files:**
- Create: `libs/openapi/agentarea_openapi/application/service.py`
- Create: `libs/openapi/tests/test_service.py`

- [ ] **Step 1: Write the failing test**

Create `libs/openapi/tests/test_service.py`:

```python
"""Tests for OpenAPIConnectionService."""

import json
from unittest.mock import AsyncMock, patch

import pytest

from agentarea_openapi.application.service import OpenAPIConnectionService
from agentarea_openapi.domain.models import OpenAPIConnection


SAMPLE_SPEC = {
    "openapi": "3.0.0",
    "info": {"title": "Test API", "version": "1.0.0"},
    "paths": {
        "/users": {
            "get": {
                "operationId": "listUsers",
                "summary": "List users",
            }
        }
    },
}


class TestDiscoverTools:
    @pytest.fixture
    def service(self):
        mock_factory = AsyncMock()
        mock_factory.create_repository.return_value = AsyncMock()
        return OpenAPIConnectionService(repository_factory=mock_factory)

    @pytest.mark.asyncio
    async def test_discover_from_spec_content(self, service):
        """If connection has spec_content, parse it directly."""
        conn = OpenAPIConnection(
            name="Test",
            base_url="https://api.example.com",
            spec_content=SAMPLE_SPEC,
        )
        service._repo = AsyncMock()
        service._repo.get_by_id.return_value = conn

        result = await service.discover_tools(conn.id)

        assert result["tools_discovered"] == 1
        assert result["tools"][0]["name"] == "listUsers"

    @pytest.mark.asyncio
    async def test_discover_from_spec_url(self, service):
        """If connection has spec_url but no content, fetch it."""
        conn = OpenAPIConnection(
            name="Test",
            base_url="https://api.example.com",
            spec_url="https://api.example.com/openapi.json",
        )
        service._repo = AsyncMock()
        service._repo.get_by_id.return_value = conn

        with patch("agentarea_openapi.application.service.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_resp = AsyncMock()
            mock_resp.status_code = 200
            mock_resp.text = json.dumps(SAMPLE_SPEC)
            mock_resp.raise_for_status = lambda: None
            mock_client.get.return_value = mock_resp
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await service.discover_tools(conn.id)

        assert result["tools_discovered"] == 1

    @pytest.mark.asyncio
    async def test_discover_no_spec(self, service):
        """If no spec_url or spec_content, raise ValueError."""
        conn = OpenAPIConnection(
            name="Test",
            base_url="https://api.example.com",
        )
        service._repo = AsyncMock()
        service._repo.get_by_id.return_value = conn

        with pytest.raises(ValueError, match="No spec"):
            await service.discover_tools(conn.id)

    @pytest.mark.asyncio
    async def test_discover_not_found(self, service):
        service._repo = AsyncMock()
        service._repo.get_by_id.return_value = None

        with pytest.raises(ValueError, match="not found"):
            await service.discover_tools("nonexistent-id")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest libs/openapi/tests/test_service.py -v`
Expected: FAIL

- [ ] **Step 3: Write the service**

Create `libs/openapi/agentarea_openapi/application/service.py`:

```python
"""Service layer for OpenAPI connection management."""

import json
import logging
from typing import Any
from uuid import UUID

import httpx
import yaml

from agentarea_openapi.application.spec_parser import parse_openapi_spec
from agentarea_openapi.domain.models import OpenAPIConnection
from agentarea_openapi.infrastructure.repository import OpenAPIConnectionRepository

logger = logging.getLogger(__name__)


class OpenAPIConnectionService:
    def __init__(
        self,
        repository_factory: Any,
        secret_manager: Any | None = None,
    ) -> None:
        self._repo: OpenAPIConnectionRepository = repository_factory.create_repository(
            OpenAPIConnectionRepository
        )
        self._secret_manager = secret_manager

    async def create_connection(
        self,
        name: str,
        base_url: str,
        description: str | None = None,
        spec_url: str | None = None,
        spec_content: dict[str, Any] | None = None,
        auth_config_id: UUID | None = None,
    ) -> OpenAPIConnection:
        connection = OpenAPIConnection(
            name=name,
            base_url=base_url,
            description=description,
            spec_url=spec_url,
            spec_content=spec_content,
            auth_config_id=auth_config_id,
        )
        return await self._repo.create(connection)

    async def get_connection(self, connection_id: UUID) -> OpenAPIConnection | None:
        return await self._repo.get_by_id(str(connection_id))

    async def list_connections(
        self,
        status: str | None = None,
        search: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[OpenAPIConnection], int]:
        return await self._repo.list_connections(
            status=status, search=search, limit=limit, offset=offset
        )

    async def update_connection(
        self, connection_id: UUID, **fields: Any
    ) -> OpenAPIConnection | None:
        return await self._repo.update(str(connection_id), **fields)

    async def delete_connection(self, connection_id: UUID) -> bool:
        return await self._repo.delete(str(connection_id))

    async def discover_tools(self, connection_id: UUID) -> dict[str, Any]:
        """Fetch/parse the OpenAPI spec and store discovered tools."""
        conn = await self._repo.get_by_id(str(connection_id))
        if not conn:
            raise ValueError(f"Connection {connection_id} not found")

        spec = conn.spec_content
        if not spec:
            spec = await self._fetch_spec(conn)

        tools = parse_openapi_spec(spec)

        conn.available_tools = tools
        conn.spec_content = spec
        await self._repo.session.commit()
        await self._repo.session.refresh(conn)

        return {
            "connection_id": str(conn.id),
            "tools_discovered": len(tools),
            "tools": [{"name": t["name"], "description": t["description"]} for t in tools],
        }

    async def _fetch_spec(self, conn: OpenAPIConnection) -> dict[str, Any]:
        """Fetch OpenAPI spec from spec_url."""
        if not conn.spec_url:
            raise ValueError(
                f"No spec_url or spec_content for connection {conn.name}. "
                "Provide a spec_url or upload spec_content."
            )

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(conn.spec_url)
            resp.raise_for_status()

        text = resp.text
        if conn.spec_url.endswith((".yaml", ".yml")):
            return yaml.safe_load(text)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return yaml.safe_load(text)

    async def test_connection(self, connection_id: UUID) -> dict[str, Any]:
        """Make a health check request to the base_url."""
        conn = await self._repo.get_by_id(str(connection_id))
        if not conn:
            raise ValueError(f"Connection {connection_id} not found")

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(conn.base_url)
            return {
                "status": "reachable",
                "status_code": resp.status_code,
            }
        except httpx.RequestError as e:
            return {
                "status": "unreachable",
                "error": str(e),
            }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run python -m pytest libs/openapi/tests/test_service.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add libs/openapi/agentarea_openapi/application/service.py libs/openapi/tests/test_service.py
git commit -m "feat(openapi): add service with discover_tools and spec fetching"
```

---

## Chunk 4: Migration + API + Wiring

### Task 6: Alembic migration

**Files:**
- Create: `apps/api/alembic/versions/009_add_openapi_connections_table.py`

- [ ] **Step 1: Write the migration**

```python
"""Add openapi_connections table.

Revision ID: 009_add_openapi_connections_table
Revises: 008_add_skill_members_table
Create Date: 2026-03-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "009_add_openapi_connections_table"
down_revision: str = "008_add_skill_members_table"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "openapi_connections",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workspace_id", sa.String(255), nullable=False),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("spec_url", sa.Text(), nullable=True),
        sa.Column("spec_content", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("base_url", sa.String(500), nullable=False),
        sa.Column(
            "auth_config_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("mcp_auth_configs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "available_tools",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
        ),
        sa.Column("status", sa.String(50), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_openapi_connections_workspace_id", "openapi_connections", ["workspace_id"])


def downgrade() -> None:
    op.drop_index("ix_openapi_connections_workspace_id", table_name="openapi_connections")
    op.drop_table("openapi_connections")
```

- [ ] **Step 2: Commit**

```bash
git add apps/api/alembic/versions/009_add_openapi_connections_table.py
git commit -m "feat(openapi): add migration for openapi_connections table"
```

---

### Task 7: API router

**Files:**
- Create: `apps/api/agentarea_api/api/v1/openapi_connections.py`

- [ ] **Step 1: Write the router**

```python
"""API endpoints for OpenAPI connections."""

import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from agentarea_api.api.deps.services import get_openapi_connection_service
from agentarea_openapi.application.service import OpenAPIConnectionService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/openapi-connections", tags=["openapi-connections"])


class OpenAPIConnectionCreate(BaseModel):
    name: str = Field(..., max_length=255)
    base_url: str = Field(..., max_length=500)
    description: str | None = None
    spec_url: str | None = None
    spec_content: dict[str, Any] | None = None
    auth_config_id: UUID | None = None


class OpenAPIConnectionUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    base_url: str | None = None
    spec_url: str | None = None
    spec_content: dict[str, Any] | None = None
    auth_config_id: UUID | None = None


class OpenAPIConnectionResponse(BaseModel):
    id: UUID
    name: str
    base_url: str
    description: str | None = None
    spec_url: str | None = None
    auth_config_id: UUID | None = None
    available_tools: list[dict[str, Any]] = []
    status: str
    created_at: Any
    updated_at: Any

    model_config = {"from_attributes": True}


@router.post("/", response_model=OpenAPIConnectionResponse, status_code=201)
async def create_connection(
    request: OpenAPIConnectionCreate,
    service: OpenAPIConnectionService = Depends(get_openapi_connection_service),
):
    try:
        conn = await service.create_connection(
            name=request.name,
            base_url=request.base_url,
            description=request.description,
            spec_url=request.spec_url,
            spec_content=request.spec_content,
            auth_config_id=request.auth_config_id,
        )
        return OpenAPIConnectionResponse.model_validate(conn)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/", response_model=list[OpenAPIConnectionResponse])
async def list_connections(
    status: str | None = Query(None),
    search: str | None = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    service: OpenAPIConnectionService = Depends(get_openapi_connection_service),
):
    connections, _total = await service.list_connections(
        status=status, search=search, limit=limit, offset=offset
    )
    return [OpenAPIConnectionResponse.model_validate(c) for c in connections]


@router.get("/{connection_id}", response_model=OpenAPIConnectionResponse)
async def get_connection(
    connection_id: UUID,
    service: OpenAPIConnectionService = Depends(get_openapi_connection_service),
):
    conn = await service.get_connection(connection_id)
    if not conn:
        raise HTTPException(status_code=404, detail="Connection not found")
    return OpenAPIConnectionResponse.model_validate(conn)


@router.patch("/{connection_id}", response_model=OpenAPIConnectionResponse)
async def update_connection(
    connection_id: UUID,
    request: OpenAPIConnectionUpdate,
    service: OpenAPIConnectionService = Depends(get_openapi_connection_service),
):
    fields = request.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(status_code=400, detail="No fields to update")

    conn = await service.update_connection(connection_id, **fields)
    if not conn:
        raise HTTPException(status_code=404, detail="Connection not found")
    return OpenAPIConnectionResponse.model_validate(conn)


@router.delete("/{connection_id}", status_code=204)
async def delete_connection(
    connection_id: UUID,
    service: OpenAPIConnectionService = Depends(get_openapi_connection_service),
):
    deleted = await service.delete_connection(connection_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Connection not found")


@router.post("/{connection_id}/discover-tools")
async def discover_tools(
    connection_id: UUID,
    service: OpenAPIConnectionService = Depends(get_openapi_connection_service),
):
    try:
        return await service.discover_tools(connection_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logger.error(f"Failed to discover tools for {connection_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to discover tools") from e


@router.post("/{connection_id}/test")
async def test_connection(
    connection_id: UUID,
    service: OpenAPIConnectionService = Depends(get_openapi_connection_service),
):
    try:
        return await service.test_connection(connection_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
```

- [ ] **Step 2: Commit**

```bash
git add apps/api/agentarea_api/api/v1/openapi_connections.py
git commit -m "feat(openapi): add API router for openapi-connections"
```

---

### Task 8: Wire up DI and router registration

**Files:**
- Modify: `apps/api/agentarea_api/api/deps/services.py`
- Modify: `apps/api/agentarea_api/api/v1/router.py`

- [ ] **Step 1: Add service dependency**

In `apps/api/agentarea_api/api/deps/services.py`, add:

```python
# Import at top
from agentarea_openapi.application.service import OpenAPIConnectionService

# Add dependency function
async def get_openapi_connection_service(
    repository_factory: RepositoryFactoryDep,
    secret_manager: BaseSecretManagerDep = None,
) -> OpenAPIConnectionService:
    return OpenAPIConnectionService(
        repository_factory=repository_factory,
        secret_manager=secret_manager,
    )
```

- [ ] **Step 2: Register router**

In `apps/api/agentarea_api/api/v1/router.py`, add:

```python
from . import openapi_connections

# Add after other protected router registrations
protected_v1_router.include_router(openapi_connections.router)
```

- [ ] **Step 3: Commit**

```bash
git add apps/api/agentarea_api/api/deps/services.py apps/api/agentarea_api/api/v1/router.py
git commit -m "feat(openapi): wire up DI and register API router"
```

---

### Task 9: Run all tests and verify

- [ ] **Step 1: Run library tests**

Run: `uv run python -m pytest libs/openapi/tests/ -v`
Expected: all tests pass

- [ ] **Step 2: Run API tests to check for import errors**

Run: `uv run python -m pytest apps/api/ -v --co` (collect only — verifies imports resolve)
Expected: no import errors

- [ ] **Step 3: Final commit if any fixes needed**

```bash
git add -A
git commit -m "fix(openapi): address test/import issues"
```
