---
title: Changelog
description: Notable AgentArea features, fixes, and compatibility changes by release.
---

# Changelog

All notable changes to AgentArea will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

<Info>
Stay up to date with the latest AgentArea releases, bug fixes, and new features.
</Info>

## [Unreleased]

### Added
- MCP OAuth 2.0 authorization server support with per-user token issuance
- Compound MCP servers: aggregate multiple MCP servers behind a single endpoint
- MCP access token management API with scope-based permissions
- Skill membership model for fine-grained agent capability sharing
- OAuth link flow for connecting external MCP providers to workspaces

### Changed
- MCP manager proxy layer refactored for direct container routing (removed intermediate registry)
- Skill repository updated to support member-based access control

---

## [0.8.0] - 2026-01-20

### Added
- **Skills System**: Reusable skill definitions that can be attached to agents across workspaces
- **Skill Sharing**: Workspace-scoped skill library with publish/subscribe model
- **MCP Auth Configs**: Store and manage authentication configurations per MCP server
- **Encrypted Secrets Store**: AES-256 encrypted secrets table for provider credentials
- **Warm Pool**: Pre-warmed agent container pool to reduce cold-start latency

### Changed
- **MCP Server Instances**: Full lifecycle management including start, stop, restart, and health monitoring
- **Container Health Checks**: Improved readiness probes with configurable retry backoff
- **Worker Configuration**: Temporal worker now supports dynamic activity registration

### Fixed
- **MCP Validation**: Resolved false-positive validation failures for SSE-based MCP servers
- **Container Networking**: Fixed DNS resolution race on multi-container MCP startup
- **Session Affinity**: Corrected sticky routing for long-running SSE connections

### Security
- **Secrets Encryption**: All provider API keys now encrypted at rest before database storage
- **Scope Validation**: MCP tool invocations validated against declared server scopes

---

## [0.7.0] - 2025-10-14

### Added
- **Event Triggers**: Webhook and scheduled triggers that launch agent tasks automatically
- **Webhook Endpoints**: Inbound webhook receiver with HMAC signature verification
- **A2A Protocol**: Agent-to-Agent communication following the Google A2A spec draft
- **A2A Auth**: Bearer token authentication for cross-agent task delegation
- **Well-Known Agent Descriptors**: `/.well-known/agent.json` endpoint for agent discovery
- **A2A Validation**: Request/response schema validation for inter-agent calls

### Changed
- **Task Events**: Extended event schema to include trigger source and parent task references
- **Router**: API router reorganized into domain groups (agents, mcp, triggers, a2a)

### Fixed
- **Trigger Deduplication**: Fixed duplicate task creation on rapid webhook delivery
- **Event Ordering**: Corrected out-of-order SSE events under high concurrency

---

## [0.6.0] - 2025-07-08

### Added
- **Temporal Workflows**: Full Temporal.io integration for durable agent task execution
- **Workflow Signals**: Support for `pause`, `resume`, and `cancel` signals on running tasks
- **Workflow Queries**: Real-time task status queries without polling the database
- **Activity Factory**: `make_agent_activities()` factory for composable workflow activities
- **LLM Provider Abstraction**: Unified interface across OpenAI, Anthropic, and compatible providers
- **Provider Specs & Configs**: Registry of supported LLM providers with per-workspace configuration
- **Model Specs & Instances**: Declare supported models and instantiate them per agent

### Changed
- **Agent Tasks**: Task execution moved from synchronous API handlers into Temporal workflows
- **Worker App**: Dedicated Temporal worker process separate from the API server
- **SSE Streaming**: Event streaming now sourced from Redis pub/sub backed by DB persistence

### Removed
- **Synchronous Task Execution**: Inline task execution removed; all tasks now go through Temporal

### Fixed
- **Workflow Replay**: Fixed non-determinism errors caused by datetime calls inside workflow code
- **Redis Reconnect**: Improved Redis client reconnect logic on transient connection drops

---

## [0.5.0] - 2025-04-22

### Added
- **MCP Server Manager (Go)**: Standalone Go service for MCP container orchestration and lifecycle
- **Container Validation**: Pre-launch validation of MCP server images and configurations
- **Health Monitoring**: Continuous health checks with automatic container restart on failure
- **MCP Proxy Routing**: HTTP proxy layer routing requests to the correct MCP container by workspace
- **Helm Charts**: Production-grade Kubernetes deployment charts for all platform services
- **Bootstrap Job**: One-shot Kubernetes job for initial platform provisioning

### Changed
- **MCP Provisioning**: MCP servers now run in isolated containers managed by the Go service
- **Configuration**: Centralized environment-based config with support for Kubernetes ConfigMaps and Secrets
- **Docker Compose**: Dev stack updated to include MCP manager service

### Fixed
- **Container Cleanup**: Orphaned containers now cleaned up on manager restart
- **Port Allocation**: Fixed port collision when multiple MCP servers started simultaneously

---

## [0.4.0] - 2025-01-30

### Added
- **Workspace Scoping**: All entities now scoped to workspaces via `WorkspaceScopedMixin`
- **UserContext**: `UserContext(user_id, workspace_id)` required across all repositories and services
- **Repository Factory**: `RepositoryFactory` provides workspace-scoped repository instances per request
- **DI Container**: Dependency injection container (`agentarea_common.di.container`) for singleton/factory registration
- **MCP Server Specifications**: Catalog of available MCP server types with schema validation
- **Workspace Configuration API**: Per-workspace settings for model defaults and resource limits
- **Real-time Task Events**: SSE endpoint streaming task lifecycle events to the frontend

### Changed
- **Database Schema**: Migration 001 baseline established; all tables include `workspace_id` foreign key
- **API Versioning**: All endpoints moved under `/v1/` prefix
- **Error Responses**: Standardized RFC 7807 problem detail format for all error responses

### Deprecated
- **Legacy Auth System**: Old authentication system replaced by Ory Hydra/Kratos (removed in v0.5.0)

### Fixed
- **Race Conditions**: Fixed concurrent agent creation under the same workspace
- **Migration Ordering**: Resolved Alembic dependency chain issues across multiple heads

---

## [0.3.0] - 2025-01-14

### Added
- **Ory Integration**: Ory Kratos for identity management and Ory Hydra for OAuth 2.0
- **Consent Flow**: OAuth consent page in the web app with session-based approval
- **MCP Integration**: Initial Model Context Protocol server management endpoints
- **Provider Configs**: Store LLM provider credentials per workspace
- **Interactive API Docs**: Swagger UI with request examples for all endpoints

### Changed
- **Authentication**: Replaced custom JWT handling with Ory session cookies and token introspection
- **Frontend**: Next.js app updated with Ory Elements React components for auth flows
- **Database**: Added indexes on `workspace_id` and `created_at` columns for common query patterns

### Removed
- **Legacy Auth Endpoints**: Custom `/auth/login` and `/auth/register` endpoints removed

### Fixed
- **Database Migrations**: Fixed migration ordering issues introduced in v0.2.x
- **Container Networking**: Resolved service discovery problems in Docker Compose
- **Redis Connection Pooling**: Fixed connection leak on high request volume

### Security
- **OAuth 2.0**: Full authorization code flow with PKCE via Ory Hydra
- **Rate Limiting**: Authentication endpoints protected by per-IP rate limiting
- **Audit Logging**: Auth events now written to structured audit log

---

## [0.2.1] - 2025-01-14

### Added
- **MCP Integration**: Enhanced Model Context Protocol server management
- **Docker Improvements**: Better container orchestration with health checks
- **API Documentation**: Interactive Swagger UI with comprehensive examples
- **Development Tools**: Hot reloading and debugging capabilities

### Changed
- **Performance**: Improved database query optimization
- **Error Handling**: More descriptive error messages and better logging
- **Authentication**: Enhanced JWT token management and refresh logic

### Fixed
- **Database Migrations**: Fixed migration ordering issues
- **Container Networking**: Resolved service discovery problems in Docker Compose
- **Memory Leaks**: Fixed Redis connection pooling issues

### Security
- **Dependencies**: Updated all dependencies to latest secure versions
- **Authentication**: Implemented rate limiting for authentication endpoints
- **Logging**: Removed sensitive data from application logs

---

## [0.2.0] - 2024-12-15

### Added
- **Multi-Agent Communication**: Basic agent-to-agent messaging framework
- **MCP Server Management**: Dynamic provisioning and lifecycle management
- **Real-time Events**: Redis-based event system for system coordination
- **Agent Templates**: Pre-built agent configurations for common use cases
- **CLI Tool**: Command-line interface for development and operations

### Changed
- **Database Schema**: Improved entity relationships and indexing
- **API Structure**: Refactored REST endpoints for better consistency
- **Configuration**: Environment-based configuration management

### Deprecated
- **Legacy Auth**: Old authentication system (will be removed in v0.3.0)

### Removed
- **Mock Services**: Removed development mock services
- **Legacy Endpoints**: Removed deprecated API endpoints

### Fixed
- **Race Conditions**: Fixed concurrent agent creation issues
- **Memory Usage**: Optimized agent state management
- **Connection Handling**: Improved database connection pooling

---

## [0.1.2] - 2024-11-20

### Added
- **Health Checks**: Comprehensive system health monitoring
- **Metrics Collection**: Basic Prometheus metrics integration
- **Container Logging**: Structured logging with JSON format

### Changed
- **Docker Images**: Optimized image sizes and build times
- **Database Performance**: Added indexes for common queries

### Fixed
- **Startup Issues**: Fixed service initialization order
- **Configuration Loading**: Resolved environment variable precedence
- **Network Timeouts**: Improved timeout handling for external services

---

## [0.1.1] - 2024-10-30

### Added
- **Basic Web Interface**: Simple React frontend for agent management
- **Agent Configuration**: JSON-based agent configuration system
- **Error Tracking**: Centralized error logging and reporting

### Changed
- **API Responses**: Standardized response format across all endpoints
- **Documentation**: Improved API documentation with examples

### Fixed
- **CORS Issues**: Fixed cross-origin request handling
- **Session Management**: Resolved session timeout problems
- **File Uploads**: Fixed multipart form data handling

---

## [0.1.0] - 2024-10-01

### Added
- **Initial Release**: Core AgentArea platform functionality
- **Agent Management**: Create, configure, and manage AI agents
- **REST API**: Comprehensive RESTful API for all operations
- **Authentication**: JWT-based authentication system
- **Database Integration**: PostgreSQL with SQLAlchemy ORM
- **Message Queue**: Redis-based message passing
- **Container Support**: Docker and Docker Compose setup
- **MCP Protocol**: Model Context Protocol integration
- **Documentation**: Basic setup and usage documentation

### Technical Details
- **Backend**: FastAPI with Python 3.11+
- **Database**: PostgreSQL 15+ with Alembic migrations
- **Cache/Queue**: Redis 7+ for messaging and caching
- **Container**: Docker with multi-stage builds
- **Proxy**: Traefik v3 for load balancing and SSL termination

---

## Release Types

<CardGroup cols={3}>
  <Card title="Major (X.0.0)" icon="rocket">
    Breaking changes, new architecture, major features
  </Card>

  <Card title="Minor (0.X.0)" icon="zap">
    New features, enhancements, backward compatible
  </Card>

  <Card title="Patch (0.0.X)" icon="wrench">
    Bug fixes, security updates, small improvements
  </Card>
</CardGroup>

## Categories

- **Added** for new features
- **Changed** for changes in existing functionality
- **Deprecated** for soon-to-be removed features
- **Removed** for now removed features
- **Fixed** for any bug fixes
- **Security** for vulnerability fixes

## Migration Guides

### Upgrading to v0.8.x

<Tabs>
  <Tab title="Breaking Changes">
    **Skills API:**
    - Skill endpoints moved to `/v1/skills/`
    - Agent tool configuration now references skill IDs instead of inline MCP configs

    **MCP Manager:**
    - MCP proxy registry replaced by direct container routing; remove `MCP_REGISTRY_URL` env var
    - `tools_config` field renamed to `tools` in agent configuration
  </Tab>

  <Tab title="Migration Steps">
    ```bash
    # 1. Backup your database
    pg_dump agentarea > backup_before_v0.8.sql

    # 2. Run migrations
    cd agentarea-platform/apps/api && alembic upgrade head

    # 3. Update MCP manager config
    # Remove MCP_REGISTRY_URL; set MCP_MANAGER_URL instead

    # 4. Restart all services
    make down-dev && make up-dev

    # 5. Verify health
    curl http://localhost:8000/health
    ```
  </Tab>

  <Tab title="Rollback Plan">
    ```bash
    # If issues occur, rollback:
    # 1. Stop services
    docker-compose down

    # 2. Restore database
    psql agentarea < backup_before_v0.8.sql

    # 3. Use previous version
    git checkout v0.7.0
    docker-compose up -d
    ```
  </Tab>
</Tabs>

### Upgrading to v0.2.x

<Tabs>
  <Tab title="Breaking Changes">
    **API Changes:**
    - Authentication endpoints moved from `/auth/` to `/v1/auth/`
    - Agent creation requires `template` field
    - Response format changed for error messages

    **Configuration:**
    - Environment variables now use `AGENTAREA_` prefix
    - Database URL format updated for connection pooling
  </Tab>

  <Tab title="Migration Steps">
    ```bash
    # 1. Backup your database
    pg_dump agentarea > backup_before_v0.2.sql

    # 2. Update configuration
    cp .env .env.backup
    # Update environment variables with new format

    # 3. Run migrations
    cd agentarea-platform/apps/api && alembic upgrade head

    # 4. Update API calls
    # Update your client code to use new endpoints

    # 5. Test thoroughly
    make test
    ```
  </Tab>

  <Tab title="Rollback Plan">
    ```bash
    # If issues occur, rollback:
    # 1. Stop services
    docker-compose down

    # 2. Restore database
    psql agentarea < backup_before_v0.2.sql

    # 3. Use previous version
    git checkout v0.1.2
    docker-compose up -d
    ```
  </Tab>
</Tabs>

## Deprecation Schedule

| Feature | Deprecated In | Removed In | Alternative |
|---------|---------------|------------|-------------|
| Legacy Auth System | v0.2.0 | v0.3.0 | Ory Kratos / Hydra |
| Inline MCP Tool Config | v0.7.0 | v0.9.0 | Skills System |
| Synchronous Task Execution | v0.6.0 | v0.6.0 | Temporal Workflows |

## Security Updates

Security fixes and improvements are documented in release notes. We follow responsible disclosure practices and address security issues promptly.

## Community Contributions

We welcome and appreciate all community contributions! If you've contributed to AgentArea, thank you for helping make the platform better for everyone.

To contribute to future releases:
- Check our [Contributing Guide](/contributing) for guidelines
- Look for "good first issue" labels on GitHub
- Join our [Discord community](/community) for support
- Submit pull requests for bug fixes and features

## Getting Help

<CardGroup cols={2}>
  <Card title="Upgrade Issues" icon="question-circle">
    If you encounter issues upgrading, check our [troubleshooting guide](/troubleshooting) or ask in Discord
  </Card>

  <Card title="Report Bugs" icon="bug">
    Found a bug in the latest release? [Report it on GitHub](https://github.com/agentarea/agentarea/issues)
  </Card>
</CardGroup>

---

<Note>
**Stay Updated**:
- Watch our [GitHub repository](https://github.com/agentarea/agentarea) for release notifications
- Follow [GitHub Discussions](https://github.com/agentarea/agentarea/discussions) for updates
- Subscribe to our release newsletter for detailed release notes
</Note>

---

*For older releases and detailed technical changes, see our [GitHub Releases](https://github.com/agentarea/agentarea/releases) page.*
