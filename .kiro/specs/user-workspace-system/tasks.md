# Implementation Plan - Workspace-Scoped Model

## Core Changes (High Priority)

- [x] 1. Create user and workspace context infrastructure

  - Implement UserContext dataclass for holding user and workspace information
  - Create basic context handling utilities for user_id and workspace_id
  - _Requirements: 1.1, 1.2, 1.4, 1.5_

- [x] 2. Implement FastAPI context dependency

  - Create get_user_context dependency function for extracting user and workspace context
  - Add error handling for missing context information
  - Create UserContextDep type alias for easier endpoint usage
  - Write unit tests for context dependency
  - _Requirements: 1.1, 1.2, 1.3, 1.4_

- [x] 3. Create WorkspaceScopedMixin to replace WorkspaceAwareMixin

  - Create new WorkspaceScopedMixin with workspace_id and created_by fields
  - Remove user_id field (replaced by created_by for audit purposes)
  - Add helper methods for workspace and creator checks
  - Update base model imports across the codebase
  - _Requirements: 3.1, 3.2, 3.3, 3.4_

- [x] 4. Create database migration to rename user_id to created_by

  - Generate Alembic migration to rename user_id columns to created_by
  - Remove updated_by columns from tables that have them
  - Update database indexes to use created_by instead of user_id
  - Test migration rollback functionality
  - _Requirements: 3.1, 3.2, 3.3, 3.4_

- [x] 5. Update WorkspaceAwareRepository to WorkspaceScopedRepository

  - Rename and update repository base class for workspace-scoped model
  - Change create() method to populate created_by instead of user_id
  - Update filtering logic to be workspace-scoped (not user-scoped)
  - Modify list_all() to return all workspace resources, not just user's
  - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5_

- [x] 6. Fix MCP Server Instance model to use proper base model

  - Update MCPServerInstance to inherit from BaseModel and WorkspaceScopedMixin
  - Remove manual workspace_id field definition
  - Add created_by field for audit trail
  - Update repository to use workspace-scoped filtering
  - _Requirements: 2.4, 3.1, 3.2, 3.3_

- [x] 7. Update all models to use WorkspaceScopedMixin

  - Update Agent model to use WorkspaceScopedMixin instead of WorkspaceAwareMixin
  - Update TaskORM to use WorkspaceScopedMixin instead of WorkspaceAwareMixin
  - Update TriggerORM and TriggerExecutionORM to use WorkspaceScopedMixin
  - Update Provider/Model configs and specs to use WorkspaceScopedMixin
  - Remove any manual user_id/workspace_id field definitions
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 3.1, 3.2, 3.3_

- [x] 8. Update all repositories to use WorkspaceScopedRepository

  - Update AgentRepository to extend WorkspaceScopedRepository
  - Update TaskRepository to extend WorkspaceScopedRepository
  - Update TriggerRepository to extend WorkspaceScopedRepository
  - Update MCPServerRepository to extend WorkspaceScopedRepository
  - Update MCPServerInstanceRepository to extend WorkspaceScopedRepository
  - Update ProviderConfigRepository to extend WorkspaceScopedRepository
  - Update ModelInstanceRepository to extend WorkspaceScopedRepository
  - _Requirements: 4.1, 4.2, 4.3, 4.4_

- [x] 9. Update API endpoints to return workspace-scoped resources
  - Update agent endpoints to return all workspace agents (not just user's)
  - Update task endpoints to return all workspace tasks
  - Update trigger endpoints to return all workspace triggers
  - Update MCP endpoints to return all workspace MCP instances
  - Add optional ?created_by=me filtering for user's created resources
  - _Requirements: 1.1, 1.2, 2.1, 2.2, 2.3, 2.4_

## Repository and Service Updates (Medium Priority)

- [x] 10. Implement repository factory pattern

  - Create RepositoryFactory class for dependency injection
  - Add get_repository_factory FastAPI dependency
  - Create RepositoryFactoryDep type alias
  - Ensure factory properly injects user context into repositories
  - _Requirements: 4.1, 4.2, 4.5_

- [x] 11. Update service layer dependency injection
  - Modify service dependencies to use RepositoryFactory instead of direct repositories
  - Update AgentService, TaskService, TriggerService to use factory pattern
  - Update MCPServerInstanceService to use workspace-scoped repositories
  - Ensure all services automatically get user context through repositories
  - _Requirements: 4.1, 4.2, 4.5_

## Polish and Testing (Low Priority)

- [x] 12. Implement workspace error handling

  - Create custom exception classes for workspace-related errors
  - Add error handler for workspace access violations
  - Ensure 404 responses for cross-workspace access attempts
  - Add proper error logging with workspace context
  - _Requirements: 3.5, 6.1, 6.2, 6.3, 6.4_

- [ ] 13. Add workspace context to API responses

  - Include workspace_id in response headers for all endpoints
  - Add workspace metadata to list response formats
  - Include workspace context in error responses
  - Ensure consistent workspace information across all API responses
  - _Requirements: 7.1, 7.2, 7.3, 7.5_

- [x] 14. Implement audit logging with workspace context

  - Update logging to include created_by and workspace_id in all log entries
  - Add structured logging for resource creation, updates, and deletions
  - Include workspace context in error logging
  - Ensure audit logs support filtering by creator and workspace
  - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5_

- [x] 15. Write comprehensive tests for workspace isolation

  - Create unit tests for WorkspaceScopedRepository functionality
  - Write integration tests for workspace data isolation
  - Add tests for JWT token extraction and validation
  - Create tests for cross-workspace access prevention
  - Test error handling for invalid workspace access
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 3.5_

- [x] 16. Update existing service tests

  - Modify existing service tests to provide user context
  - Update repository tests to use WorkspaceScopedRepository
  - Add workspace isolation assertions to existing test suites
  - Ensure all tests pass with new authentication requirements
  - _Requirements: 4.1, 4.2, 4.3, 4.4_

- [ ] 17. Create development and testing utilities
  - Add development mode JWT token generation utilities
  - Create test fixtures for different user and workspace contexts
  - Add helper functions for creating test JWT tokens
  - Implement workspace switching utilities for development
  - _Requirements: 1.5, 7.4_

## Documentation Updates

- [x] 18. Update requirements document

  - Change references from "user_id and workspace_id" to "workspace_id and created_by"
  - Update acceptance criteria to reflect workspace-scoped (not user-scoped) isolation
  - Remove user-level isolation requirements
  - Focus on workspace-level data isolation

- [x] 19. Update design document
  - Update architecture diagrams to show workspace-scoped model
  - Change code examples to use WorkspaceScopedMixin
  - Update repository patterns to show workspace-scoped filtering
  - Reflect new API behavior (workspace resources, not user resources)
