# Architecture Decision Records (ADR)

This document captures key architectural decisions made during the development of the AgentArea MCP infrastructure.

## ADR-001: Container Runtime Selection - Podman over Docker

**Date:** 2024-12
**Status:** Accepted
**Context:** Need to choose a container runtime for the MCP Manager service

**Decision:** Use Podman as the container runtime instead of Docker

**Rationale:**
- **Rootless containers**: Better security model with user namespace isolation
- **Daemonless architecture**: No privileged daemon required, reducing attack surface
- **Docker compatibility**: Drop-in replacement for Docker CLI commands
- **Resource efficiency**: Lower memory footprint compared to Docker daemon
- **Kubernetes alignment**: Better integration with K8s-native container standards

**Consequences:**
- ✅ Enhanced security posture
- ✅ Reduced resource overhead
- ✅ Simplified deployment in restricted environments
- ⚠️ Learning curve for team members familiar with Docker
- ⚠️ Some Docker Compose features may behave differently

---

## ADR-002: Reverse Proxy Migration - Traefik over Caddy

**Date:** 2024-12
**Status:** Accepted
**Context:** Need a reverse proxy for external MCP server access with dynamic routing

**Decision:** Migrate from Caddy to Traefik for reverse proxy functionality

**Rationale:**
- **Dynamic configuration**: File-based configuration updates without restarts
- **Container integration**: Better Docker/Podman label-based service discovery
- **Path-based routing**: Superior support for `/mcp/{slug}/mcp/` URL patterns
- **Middleware support**: Built-in path stripping and header manipulation
- **Monitoring**: Better metrics and dashboard capabilities

**Consequences:**
- ✅ Simplified dynamic routing configuration
- ✅ Better container ecosystem integration
- ✅ More flexible middleware pipeline
- ✅ Improved observability
- ⚠️ Configuration syntax migration required
- ⚠️ Team needs to learn Traefik-specific concepts

**Migration Impact:**
- Removed Caddy-based Docker Compose files
- Updated Go MCP Manager to generate Traefik configuration
- Changed external URL pattern to `localhost:81/mcp/{slug}/mcp/`

---

## ADR-003: MCP Server Container Strategy - agentarea/echo for Testing

**Date:** 2024-12
**Status:** Accepted
**Context:** Need a reliable MCP server container for E2E testing and validation

**Decision:** Use `agentarea/echo` as the primary MCP server for testing instead of `mcp/everything` or `mcp/filesystem`

**Rationale:**
- **Reliability**: Purpose-built for testing with predictable behavior
- **MCP protocol compliance**: Full implementation of MCP 2024-11-05 specification
- **Lightweight**: Minimal resource requirements for CI/CD environments
- **Streaming support**: Proper Server-Sent Events implementation
- **Debugging friendly**: Clear logging and error messages

**Consequences:**
- ✅ Consistent E2E test results
- ✅ Faster test execution
- ✅ Better debugging capabilities
- ✅ Reduced flakiness in CI/CD
- ⚠️ Less feature coverage compared to full MCP servers

**Configuration:**
```json
{
  "image": "agentarea/echo",
  "port": 3333,
  "environment": {
    "PORT": "3333",
    "MCP_PATH": "/mcp",
    "LOG_LEVEL": "debug"
  }
}
```

---

## ADR-004: External Access Pattern - Slug-based Routing

**Date:** 2024-12
**Status:** Accepted
**Context:** Need a way to provide external access to dynamically created MCP servers

**Decision:** Implement slug-based routing with pattern `localhost:port/mcp/{slug}/mcp/`

**Rationale:**
- **Isolation**: Each MCP instance gets a unique URL namespace
- **Security**: Slug acts as a simple access token
- **Scalability**: No port conflicts with multiple instances
- **User-friendly**: Predictable URL pattern for client integration
- **Proxy-friendly**: Works well with reverse proxy path-based routing

**Implementation:**
- Slug generation: `{service-name}-{random-suffix}` (e.g., `echo-e2e-test-a1956c3a`)
- Traefik PathPrefix rule: `/mcp/{slug}`
- StripPrefix middleware removes `/mcp/{slug}` before forwarding
- Final container receives clean `/mcp/` requests

**Consequences:**
- ✅ Clean separation between MCP instances
- ✅ No port management complexity
- ✅ Easy client integration
- ✅ Secure by default (slug obscurity)
- ⚠️ URL length increases with slug
- ⚠️ Slug management required for cleanup

---

## ADR-005: Event-Driven Architecture - Redis Pub/Sub

**Date:** 2024-12
**Status:** Accepted
**Context:** Need communication between Core API and Go MCP Manager for container lifecycle

**Decision:** Use Redis Pub/Sub for event-driven communication between services

**Rationale:**
- **Decoupling**: Services don't need direct HTTP communication
- **Reliability**: Message persistence and delivery guarantees
- **Scalability**: Can handle high-throughput event streams
- **Existing infrastructure**: Redis already used for other purposes
- **Event sourcing**: Natural fit for domain events pattern

**Event Flow:**
1. Core API publishes `mcp_server_instance.created` events to Redis
2. Go MCP Manager subscribes to events and processes them
3. Container creation, Traefik configuration, and cleanup handled asynchronously

**Consequences:**
- ✅ Loose coupling between services
- ✅ Better fault tolerance
- ✅ Easier to add new event consumers
- ✅ Natural audit trail
- ⚠️ Eventual consistency model
- ⚠️ Debugging complexity with async flows

---

## ADR-006: Configuration Management - File-based Dynamic Config

**Date:** 2024-12
**Status:** Accepted
**Context:** Need to dynamically configure Traefik routing without service restarts

**Decision:** Use file-based dynamic configuration for Traefik with automatic reloading

**Rationale:**
- **Zero-downtime updates**: Configuration changes without service restart
- **Atomic updates**: File replacement ensures consistency
- **Version control friendly**: Configuration can be tracked in Git
- **Debugging**: Easy to inspect current routing configuration
- **Backup/restore**: Simple file-based backup strategy

**Implementation:**
- Configuration file: `mcp-infrastructure/traefik/dynamic.yml`
- Go MCP Manager writes updates atomically
- Traefik watches file for changes and reloads automatically
- Each MCP instance gets dedicated router, service, and middleware

**Consequences:**
- ✅ Fast configuration updates
- ✅ No service disruption during changes
- ✅ Easy troubleshooting and debugging
- ✅ Configuration versioning possible
- ⚠️ File system dependency
- ⚠️ Concurrent write protection needed

---

## ADR-007: Testing Strategy - Comprehensive E2E Flow

**Date:** 2024-12
**Status:** Accepted
**Context:** Need reliable testing approach for the complete MCP infrastructure

**Decision:** Implement comprehensive E2E testing covering the full flow from API to external access

**Test Coverage:**
1. **Health Checks**: Verify all services are running
2. **MCP Server Specification**: Create server definitions via API
3. **MCP Instance Creation**: Create instances from specifications
4. **Event Processing**: Verify Redis pub/sub communication
5. **Container Management**: Validate Podman container creation
6. **Environment Variables**: Check proper variable injection
7. **Internal Connectivity**: Test MCP protocol communication
8. **External Routing**: Validate Traefik proxy functionality
9. **Cleanup**: Ensure proper resource cleanup

**Rationale:**
- **Confidence**: Full system validation before deployment
- **Regression prevention**: Catch breaking changes early
- **Documentation**: Tests serve as executable documentation
- **CI/CD integration**: Automated validation in pipelines

**Consequences:**
- ✅ High confidence in system reliability
- ✅ Clear understanding of system behavior
- ✅ Faster debugging when issues occur
- ✅ Better onboarding for new developers
- ⚠️ Longer test execution time
- ⚠️ More complex test environment setup

---

## ADR-008: Security Model - Network Isolation + Slug Obscurity

**Date:** 2024-12
**Status:** Accepted
**Context:** Need to secure MCP server instances while maintaining accessibility

**Decision:** Implement defense-in-depth security with network isolation and slug-based access control

**Security Layers:**
1. **Network Isolation**: MCP containers on dedicated network
2. **No Direct Port Exposure**: All access through reverse proxy
3. **Slug-based Access**: Unique, unpredictable URLs for each instance
4. **Path Validation**: Strict routing rules in Traefik
5. **Container Isolation**: Rootless containers with limited privileges

**Rationale:**
- **Defense in depth**: Multiple security layers
- **Principle of least privilege**: Minimal required access
- **Secure by default**: No accidental exposure
- **Scalable**: Security model works with many instances

**Consequences:**
- ✅ Strong security posture
- ✅ No accidental exposure of services
- ✅ Audit trail through proxy logs
- ✅ Easy to add authentication later
- ⚠️ Slightly more complex URL management
- ⚠️ Debugging requires proxy access

---

## ADR-009: Development Workflow - Docker Compose for Local Development

**Date:** 2024-12
**Status:** Accepted
**Context:** Need efficient local development environment for the MCP infrastructure

**Decision:** Use Docker Compose with `docker-compose.dev.yaml` for local development

**Components:**
- **Core API**: Python FastAPI service (port 8000)
- **Go MCP Manager**: Container management service (port 7999)
- **Traefik**: Reverse proxy (port 81)
- **Redis**: Event bus and caching
- **PostgreSQL**: Primary database

**Rationale:**
- **Consistency**: Same environment across all developers
- **Isolation**: Services don't interfere with host system
- **Rapid iteration**: Quick service restart and debugging
- **Production parity**: Similar to production deployment

**Consequences:**
- ✅ Consistent development environment
- ✅ Easy onboarding for new developers
- ✅ Reduced "works on my machine" issues
- ✅ Simple service orchestration
- ⚠️ Docker/Podman dependency for development
- ⚠️ Resource usage on developer machines

---

## ADR-010: Code Organization - Monorepo with Clear Boundaries

**Date:** 2024-12
**Status:** Accepted
**Context:** Need to organize code for multiple services and components

**Decision:** Use monorepo structure with clear service boundaries

**Structure:**
```
agentarea/
├── core/                    # Python Core API
├── mcp-infrastructure/      # Go MCP Manager + Infrastructure
├── frontend/               # React frontend
├── docs/                   # Documentation
├── tests/                  # Integration tests
└── docker-compose.dev.yaml # Development environment
```

**Rationale:**
- **Atomic changes**: Related changes across services in single commit
- **Shared tooling**: Common CI/CD, linting, and testing setup
- **Easier refactoring**: Cross-service changes are simpler
- **Single source of truth**: All code in one repository

**Consequences:**
- ✅ Simplified dependency management
- ✅ Easier cross-service refactoring
- ✅ Single CI/CD pipeline
- ✅ Consistent tooling and standards
- ⚠️ Larger repository size
- ⚠️ Need clear service boundaries to avoid coupling

---

## Decision Summary

| ADR | Decision | Status | Impact |
|-----|----------|--------|---------|
| 001 | Podman over Docker | ✅ Accepted | Security, Resource efficiency |
| 002 | Traefik over Caddy | ✅ Accepted | Dynamic routing, Better integration |
| 003 | agentarea/echo for testing | ✅ Accepted | Reliable E2E tests |
| 004 | Slug-based routing | ✅ Accepted | Scalable external access |
| 005 | Redis Pub/Sub events | ✅ Accepted | Service decoupling |
| 006 | File-based dynamic config | ✅ Accepted | Zero-downtime updates |
| 007 | Comprehensive E2E testing | ✅ Accepted | System reliability |
| 008 | Network isolation + slugs | ✅ Accepted | Defense-in-depth security |
| 009 | Docker Compose dev env | ✅ Accepted | Consistent development |
| 010 | Monorepo organization | ✅ Accepted | Simplified management |

## Future Considerations

### Potential Future ADRs:
- **Authentication/Authorization**: JWT tokens, OAuth integration
- **Monitoring/Observability**: Prometheus, Grafana, distributed tracing
- **High Availability**: Multi-instance deployment, load balancing
- **Backup/Recovery**: Database backups, disaster recovery procedures
- **Performance Optimization**: Caching strategies, connection pooling
- **Kubernetes Migration**: Production deployment on K8s clusters

### Review Schedule:
- **Quarterly**: Review existing ADRs for relevance
- **Major releases**: Evaluate architectural decisions impact
- **New features**: Create ADRs for significant architectural changes

---

*Last updated: December 2024*
*Next review: March 2025* 