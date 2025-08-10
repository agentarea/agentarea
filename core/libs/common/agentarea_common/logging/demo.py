"""Demonstration of audit logging with workspace context."""

import asyncio

from ..auth.context import UserContext
from .audit_logger import get_audit_logger
from .config import setup_logging
from .context_logger import get_context_logger
from .query import AuditLogQuery


async def demo_audit_logging():
    """Demonstrate audit logging functionality."""
    print("=== AgentArea Audit Logging Demo ===\n")

    # Setup logging
    setup_logging(
        level="INFO",
        enable_structured_logging=True,
        enable_audit_logging=True
    )

    # Create user contexts for different users/workspaces
    user1_context = UserContext(user_id="alice", workspace_id="workspace-alpha")
    user2_context = UserContext(user_id="bob", workspace_id="workspace-beta")

    # Get loggers
    audit_logger = get_audit_logger()
    context_logger1 = get_context_logger("agentarea.demo", user1_context)
    context_logger2 = get_context_logger("agentarea.demo", user2_context)

    print("1. Demonstrating context-aware logging:")
    context_logger1.info("Alice is performing an action")
    context_logger2.info("Bob is performing an action")
    print()

    print("2. Demonstrating audit logging for resource operations:")

    # Alice creates an agent
    audit_logger.log_create(
        resource_type="agent",
        user_context=user1_context,
        resource_id="agent-001",
        resource_data={"name": "Alice's Agent", "model": "gpt-4"},
        endpoint="/api/v1/agents",
        method="POST"
    )

    # Bob creates a task
    audit_logger.log_create(
        resource_type="task",
        user_context=user2_context,
        resource_id="task-001",
        resource_data={"description": "Process documents", "agent_id": "agent-002"},
        endpoint="/api/v1/tasks",
        method="POST"
    )

    # Alice updates her agent
    audit_logger.log_update(
        resource_type="agent",
        user_context=user1_context,
        resource_id="agent-001",
        resource_data={"name": "Alice's Updated Agent"},
        endpoint="/api/v1/agents/agent-001",
        method="PUT"
    )

    # Bob reads a task
    audit_logger.log_read(
        resource_type="task",
        user_context=user2_context,
        resource_id="task-001",
        endpoint="/api/v1/tasks/task-001",
        method="GET"
    )

    # Alice lists her agents
    audit_logger.log_list(
        resource_type="agent",
        user_context=user1_context,
        count=3,
        filters={"status": "active"},
        endpoint="/api/v1/agents",
        method="GET"
    )

    # Simulate an error
    audit_logger.log_error(
        resource_type="agent",
        user_context=user1_context,
        error="Database connection timeout",
        resource_id="agent-001",
        endpoint="/api/v1/agents/agent-001",
        method="DELETE",
        error_code="DB_TIMEOUT"
    )

    # Alice deletes an agent
    audit_logger.log_delete(
        resource_type="agent",
        user_context=user1_context,
        resource_id="agent-002",
        endpoint="/api/v1/agents/agent-002",
        method="DELETE"
    )

    print()
    print("3. Demonstrating audit log querying:")

    # Wait a moment for logs to be written
    await asyncio.sleep(0.1)

    # Query audit logs (this would work if we had actual log files)
    query = AuditLogQuery("audit.log")

    print("   - Querying Alice's activity:")
    alice_activity = query.get_user_activity(user1_context, limit=10)
    print(f"     Found {len(alice_activity)} activities for Alice")

    print("   - Querying workspace-alpha activity:")
    workspace_activity = query.get_workspace_activity("workspace-alpha", limit=10)
    print(f"     Found {len(workspace_activity)} activities in workspace-alpha")

    print("   - Querying agent resource history:")
    agent_history = query.get_resource_history("agent", "agent-001", limit=10)
    print(f"     Found {len(agent_history)} history entries for agent-001")

    print("   - Querying error logs:")
    error_logs = query.get_error_logs(workspace_id="workspace-alpha", limit=10)
    print(f"     Found {len(error_logs)} error entries in workspace-alpha")

    print()
    print("4. Key features demonstrated:")
    print("   ✓ Structured JSON logging with workspace context")
    print("   ✓ Automatic user_id and workspace_id inclusion")
    print("   ✓ Audit events for CRUD operations")
    print("   ✓ Error logging with context")
    print("   ✓ Queryable audit logs by user, workspace, resource")
    print("   ✓ Context-aware loggers for regular application logging")

    print("\n=== Demo Complete ===")


if __name__ == "__main__":
    asyncio.run(demo_audit_logging())
