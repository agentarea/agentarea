# Implementation Plan

- [x] 1. Create trigger library structure and domain models

  - Create core/libs/triggers directory with proper Python package structure
  - Implement trigger domain models (Trigger, CronTrigger, WebhookTrigger, TriggerExecution)
  - Create trigger enums and value objects (TriggerType, TriggerStatus, ExecutionStatus)
  - Write unit tests for domain models
  - _Requirements: 1.1, 1.2, 4.1, 4.2_

- [x] 2. Update trigger database schema and ORM models for scalability

  - Update database migration to replace separate webhook config fields with generic webhook_config JSONB
  - Update TriggerORM model to use generic webhook_config field instead of separate telegram_config, slack_config, github_config
  - Update WebhookTrigger domain model to use generic webhook_config field
  - Ensure backward compatibility during migration
  - Write database integration tests for updated schema
  - _Requirements: 1.1, 1.2, 4.1, 4.2, 7.1-7.5_

- [x] 3. Create trigger repository layer

  - Implement TriggerRepository with CRUD operations using existing BaseRepository pattern
  - Add methods for querying triggers by type, status, agent_id, and webhook_id
  - Implement TriggerExecutionRepository for execution history
  - Write unit tests for repository operations
  - _Requirements: 1.1, 3.1, 3.2, 3.3, 3.4_

- [x] 4. Build core TriggerService with basic CRUD operations

  - Implement TriggerService class following existing service patterns
  - Add CRUD operations for trigger management (create, read, update, delete)
  - Integrate with existing AgentRepository for agent validation
  - Implement trigger lifecycle management (enable/disable/delete)
  - Write unit tests for TriggerService core functionality
  - _Requirements: 1.1, 1.2, 1.3, 3.1, 3.2, 3.3, 3.4_

- [x] 5. Implement Temporal Schedules for cron triggers

  - Create TemporalScheduleManager for schedule management (create/update/delete schedules)
  - Add schedule_cron_trigger and unschedule_cron_trigger methods to TriggerService
  - Integrate Temporal Schedules with trigger lifecycle operations
  - Write unit tests for Temporal Schedule integration
  - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5_

- [x] 6. Create webhook handling infrastructure

  - Add webhook endpoints to existing FastAPI application
  - Implement WebhookManager for URL generation and request processing
  - Create webhook request processing pipeline (parse, validate, execute)
  - Add webhook trigger matching and execution logic
  - Write unit tests for webhook handling
  - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5_

- [x] 7. Move trigger execution workflows and activities to execution package

  - Move TriggerExecutionWorkflow from triggers package to execution/workflows
  - Move trigger execution activities from triggers package to execution/activities
  - Update imports and dependencies to reflect new location
  - Ensure trigger execution follows same patterns as agent execution
  - Update tests to reflect new package structure
  - Clean up old temporal directory and files from triggers package
  - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5_

- [x] 8. Fix TriggerService method inconsistencies and missing functionality

  - Fix schedule_manager property reference (should be temporal_schedule_manager)
  - Implement missing \_record_execution_success and \_record_execution_failure methods
  - Add missing \_build_task_parameters method for task creation
  - Fix execute_trigger method to properly handle task creation and execution
  - Add proper error handling for missing dependencies (task_service, temporal_schedule_manager)
  - Write unit tests for fixed methods
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5_

- [x] 9. Fix remaining TriggerService property references

  - Replace all instances of self.schedule_manager with self.temporal_schedule_manager in TriggerService
  - Update method calls to use correct property name for schedule management
  - Test schedule management operations to ensure they work correctly
  - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5_

- [x] 10. Complete trigger execution engine and TaskService integration

  - Fix task creation logic in trigger execution activities (currently commented out)
  - Integrate TriggerService with existing TaskService for task creation when triggers fire
  - Add proper task parameter building from trigger data and event context
  - Implement execution recording and history tracking
  - Add trigger condition evaluation and matching logic
  - Write unit tests for execution engine
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 4.1, 4.2_

- [x] 11. Add LLM-based condition evaluation

  - Integrate with existing LLMService for natural language condition evaluation
  - Implement condition evaluation for both cron and webhook triggers
  - Add LLM-based parameter extraction from event data
  - Create condition validation and syntax checking
  - Write unit tests for LLM condition evaluation
  - _Requirements: 8.1, 8.2, 8.5_

- [x] 12. Create API endpoints for trigger management

  - Create new triggers.py API module with REST endpoints for trigger CRUD operations
  - Add API endpoints for trigger lifecycle management (enable/disable/delete)
  - Create endpoints for execution history and monitoring
  - Add proper API validation, error handling, and response formatting
  - Implement authentication and authorization using existing A2A patterns
  - Include trigger management endpoints in main API router
  - Remove application-level rate limiting (moved to infrastructure layer)
  - Write API integration tests
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 3.1, 3.2, 3.3, 3.4, 4.3_

- [x] 13. Enhance business logic safety mechanisms

  - Create automatic trigger disabling after consecutive failures (business logic)
  - Configure Temporal retry policies and timeouts for trigger execution workflows
  - Remove application-level rate limiting (move to infrastructure layer)
  - Write unit tests for trigger disabling logic
  - _Requirements: 9.1, 9.3, 9.4, 9.5_
  - _Note: Execution timeouts, retries, and backoff are handled by Temporal workflows_

- [x] 14. Build monitoring and execution history

  - Enhance TriggerExecutionRepository with pagination and filtering methods
  - Add execution history API endpoints with proper pagination
  - Implement execution correlation tracking with created tasks
  - Add execution metrics collection (success rate, average execution time)
  - Write unit tests for execution history and metrics functionality
  - _Requirements: 4.1, 4.2, 4.3, 4.4_

- [x] 15. Complete service integration and dependency injection

  - Add TriggerService to existing service dependency injection container
  - Create configuration management for trigger system settings (failure thresholds, timeouts)
  - Add health checks for trigger system components (database connectivity)
  - Integrate trigger API endpoints into main FastAPI router
  - Write integration tests for service dependency injection
  - _Requirements: All requirements - system integration_

- [x] 16. Add comprehensive error handling and logging

  - Implement structured logging for all trigger operations using existing patterns
  - Add proper error handling for missing dependencies (task_service, temporal_schedule_manager)
  - Enhance webhook validation error handling and user feedback
  - Add correlation IDs to trigger execution logging
  - Write tests for error scenarios and graceful degradation
  - _Requirements: 2.5, 4.4, 8.5, 9.5_

- [x] 17. Write integration tests and end-to-end scenarios
  - Create end-to-end tests for trigger creation, execution, and task creation flow
  - Write integration tests for webhook trigger processing with real HTTP requests
  - Add tests for trigger lifecycle management (enable/disable/delete)
  - Create tests for trigger safety mechanisms and auto-disabling
  - Add performance tests for concurrent trigger execution
  - _Requirements: All requirements - system validation_

- [ ] 18. Fix missing TriggerService method implementations
  - Implement missing `_build_task_parameters` method in TriggerService
  - Implement missing `evaluate_trigger_conditions` method in TriggerService  
  - Fix task creation integration in trigger execution activities
  - Add proper error handling for task creation failures
  - Write unit tests for the fixed methods
  - _Requirements: 2.1, 2.2, 2.3, 8.1, 8.2_

- [ ] 19. Complete end-to-end testing and validation
  - Create comprehensive end-to-end test that validates the complete trigger flow
  - Test cron trigger creation, scheduling, and execution with task creation
  - Test webhook trigger creation, URL generation, and HTTP request processing
  - Validate trigger safety mechanisms work correctly (auto-disable on failures)
  - Test trigger lifecycle operations (enable/disable/delete) with Temporal integration
  - Add performance testing for concurrent trigger executions
  - _Requirements: All requirements - complete system validation_
