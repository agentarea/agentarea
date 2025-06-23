# AgentArea Development Tasks

## 🎯 Current Status
**✅ COMPLETED: Unified MCP Architecture Implementation**

The major architectural refactoring has been completed successfully:
- Removed `provider_type` field - logic now determined by mcp-infrastructure based on `json_spec` content
- Implemented unified `json_spec` field for all configuration (similar to Airbyte connectors)
- Renamed `server_id` to `server_spec_id`
- Cleaned up outdated integration services and event bridge components

---

## 📋 Active Tasks

### Backend & API
- [ ] Implement proper authentication and authorization
- [ ] Add comprehensive API documentation with OpenAPI specs
- [ ] Implement rate limiting and request validation
- [ ] Add comprehensive logging and monitoring
- [ ] Implement backup and recovery procedures

### Frontend
- [ ] Complete MCP instance management UI
- [ ] Add real-time status updates for MCP instances
- [ ] Implement agent configuration interface
- [ ] Add monitoring dashboard

### DevOps & Infrastructure
- [ ] Set up CI/CD pipelines
- [ ] Implement proper environment management (dev/staging/prod)
- [ ] Add health checks and monitoring alerts
- [ ] Implement automated testing

### Documentation
- [ ] Create user guides and tutorials
- [ ] Document API endpoints and schemas
- [ ] Add deployment guides
- [ ] Create troubleshooting documentation

---

## 🚀 Future Enhancements
- [ ] Multi-tenant support
- [ ] Plugin system for custom MCP providers
- [ ] Advanced scheduling and orchestration
- [ ] Integration with external monitoring systems
- [ ] Performance optimization and caching

---

## 📝 Notes
- Architecture is now clean and follows event-driven patterns
- MCP Infrastructure handles all deployment logic automatically
- AgentArea focuses on data management and user interface

# Next Actions Plan

1. Analyze API definitions in `core/agentarea/api/v1` to identify correct endpoints & payload schemas for:
   - LLM model specifications & instances
   - MCP server specifications & instances
   - Agent creation
   - Task creation

2. Update `core/comprehensive_e2e_test.py` to align with the current API:
   - Use trailing slashes on collection endpoints to avoid redirect issues.
   - Correct paths for MCP server **instances** (`/mcp-server-instances/`).
   - Adjust payload fields for MCP server specification (now requires `docker_image_url`, `version`, `tags`, etc.).
   - Adapt MCP server instance payload to match `json_spec` schema.
   - Modify agent-creation payload to use the new schema (`instruction`, `model_id`, `tools_config`).
   - Update task creation step to new REST payload (`message`, `agent_id`, optional `user_id`).
   - Simplify success checks to the new responses (HTTP 201 + JSON `id`).

3. Remove duplicate `/tasks` routes to prevent clashes:
   - Delete the `/tasks` and `/tasks/stream` endpoints defined in `core/agentarea/api/v1/chat.py` – these duplicate the dedicated `tasks.py` router.

4. Run the test suite locally to ensure the updated E2E test passes and that API startup has no route collisions.

5. Commit changes as two logical commits:
   - "refactor: align comprehensive E2E test with current API"
   - "chore: remove duplicate /tasks endpoints from chat router"
