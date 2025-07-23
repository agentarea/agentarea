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
  - Write API integration tests
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 3.1, 3.2, 3.3, 3.4, 4.3_

- [ ] 13. Enhance business logic safety mechanisms

  - Create automatic trigger disabling after consecutive failures (business logic)
  - Configure Temporal retry policies and timeouts for trigger execution workflows
  - Remove application-level rate limiting (move to infrastructure layer)
  - Write unit tests for trigger disabling logic
  - _Requirements: 9.1, 9.3, 9.4, 9.5_
  - _Note: Execution timeouts, retries, and backoff are handled by Temporal workflows_

- [ ] 14. Build monitoring and execution history

  - Implement trigger execution recording with detailed metadata
  - Add execution history querying with pagination and filtering
  - Create trigger performance metrics and monitoring
  - Implement execution status tracking and error logging
  - Add trigger execution correlation with created tasks
  - Write unit tests for monitoring and history functionality
  - _Requirements: 4.1, 4.2, 4.3, 4.4_

- [ ] 15. Add comprehensive error handling and logging

  - Implement structured logging for all trigger operations using existing patterns
  - Add proper error handling for LLM service failures
  - Create error recovery mechanisms for scheduler and webhook failures
  - Implement graceful degradation when external services are unavailable
  - Add comprehensive error logging with correlation IDs
  - Write tests for error scenarios and recovery
  - _Requirements: 2.5, 4.4, 8.5, 9.5_

- [ ] 16. Complete service integration and dependency injection

  - Fix get_webhook_manager dependency function in API services
  - Add TriggerService to existing service dependency injection container
  - Integrate Temporal client for schedule management in TriggerService
  - Create configuration management for trigger system settings
  - Add health checks for trigger system components (database, temporal, dependencies)
  - Add metrics endpoints for monitoring (Prometheus-compatible)
  - Write integration tests for service integration
  - _Requirements: All requirements - system integration_

- [ ] 17. Infrastructure layer configuration (DevOps/Platform team)

  - Configure ingress-level rate limiting for webhook endpoints
  - Set up webhook signature verification at load balancer/WAF level
  - Implement IP whitelisting and geographic filtering for webhooks
  - Configure request size limits and timeout handling at ingress
  - Set up SSL/TLS termination and certificate management
  - Configure load balancer health checks and failover
  - Set up monitoring, metrics collection, and alerting (Prometheus/Grafana)
  - Configure distributed tracing and log aggregation
  - _Note: This task should be handled by infrastructure/platform team, not application developers_

- [ ] 18. Write integration tests and end-to-end scenarios
  - Create end-to-end tests for cron trigger creation and execution
  - Write integration tests for webhook trigger processing
  - Add tests for LLM condition evaluation with real scenarios
  - Create performance tests for high-volume webhook processing
  - Implement tests for trigger lifecycle and error scenarios
  - Add tests for TaskService integration and task creation
  - _Requirements: All requirements - system validation_
