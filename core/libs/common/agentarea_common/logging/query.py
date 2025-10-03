"""Utilities for querying and filtering audit logs."""

import json
from datetime import datetime
from typing import Any
from uuid import UUID

from ..auth.context import UserContext


class AuditLogQuery:
    """Utility for querying audit logs with workspace context."""

    def __init__(self, log_file_path: str = "audit.log"):
        """Initialize audit log query utility.

        Args:
            log_file_path: Path to the audit log file
        """
        self.log_file_path = log_file_path

    def _parse_log_line(self, line: str) -> dict[str, Any] | None:
        """Parse a log line into a structured dictionary.

        Args:
            line: Raw log line

        Returns:
            Parsed log entry or None if parsing fails
        """
        try:
            return json.loads(line.strip())
        except (json.JSONDecodeError, ValueError):
            return None

    def _matches_filters(self, log_entry: dict[str, Any], **filters: Any) -> bool:
        """Check if log entry matches the given filters.

        Args:
            log_entry: Parsed log entry
            **filters: Filter criteria

        Returns:
            True if entry matches all filters
        """
        for key, value in filters.items():
            if key == "start_time" and "timestamp" in log_entry:
                entry_time = datetime.fromisoformat(log_entry["timestamp"].replace("Z", "+00:00"))
                if entry_time < value:
                    return False
            elif key == "end_time" and "timestamp" in log_entry:
                entry_time = datetime.fromisoformat(log_entry["timestamp"].replace("Z", "+00:00"))
                if entry_time > value:
                    return False
            elif key in log_entry:
                if log_entry[key] != value:
                    return False
            elif "audit_event" in log_entry and key in log_entry["audit_event"]:
                if log_entry["audit_event"][key] != value:
                    return False
            else:
                # Filter key not found in entry
                return False

        return True

    def query_logs(
        self,
        workspace_id: str | None = None,
        user_id: str | None = None,
        resource_type: str | None = None,
        action: str | None = None,
        resource_id: str | UUID | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        limit: int | None = None,
        **additional_filters: Any,
    ) -> list[dict[str, Any]]:
        """Query audit logs with filtering support.

        Args:
            workspace_id: Filter by workspace ID
            user_id: Filter by user ID (created_by)
            resource_type: Filter by resource type
            action: Filter by action type
            resource_id: Filter by specific resource ID
            start_time: Filter by start time
            end_time: Filter by end time
            limit: Maximum number of results to return
            **additional_filters: Additional filter criteria

        Returns:
            List of matching log entries
        """
        filters = {}

        if workspace_id:
            filters["workspace_id"] = workspace_id
        if user_id:
            filters["user_id"] = user_id
        if resource_type:
            filters["resource_type"] = resource_type
        if action:
            filters["action"] = action
        if resource_id:
            filters["resource_id"] = str(resource_id)
        if start_time:
            filters["start_time"] = start_time
        if end_time:
            filters["end_time"] = end_time

        filters.update(additional_filters)

        results = []

        try:
            with open(self.log_file_path) as f:
                for line in f:
                    if limit and len(results) >= limit:
                        break

                    log_entry = self._parse_log_line(line)
                    if log_entry and self._matches_filters(log_entry, **filters):
                        results.append(log_entry)

        except FileNotFoundError:
            # Log file doesn't exist yet
            pass

        return results

    def get_user_activity(
        self,
        user_context: UserContext,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """Get activity logs for a specific user in their workspace.

        Args:
            user_context: User and workspace context
            start_time: Filter by start time
            end_time: Filter by end time
            limit: Maximum number of results

        Returns:
            List of user's activity log entries
        """
        return self.query_logs(
            workspace_id=user_context.workspace_id,
            user_id=user_context.user_id,
            start_time=start_time,
            end_time=end_time,
            limit=limit,
        )

    def get_workspace_activity(
        self,
        workspace_id: str,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """Get activity logs for an entire workspace.

        Args:
            workspace_id: Workspace ID to filter by
            start_time: Filter by start time
            end_time: Filter by end time
            limit: Maximum number of results

        Returns:
            List of workspace activity log entries
        """
        return self.query_logs(
            workspace_id=workspace_id, start_time=start_time, end_time=end_time, limit=limit
        )

    def get_resource_history(
        self,
        resource_type: str,
        resource_id: str | UUID,
        workspace_id: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """Get history for a specific resource.

        Args:
            resource_type: Type of resource
            resource_id: ID of the resource
            workspace_id: Optional workspace filter
            limit: Maximum number of results

        Returns:
            List of resource history log entries
        """
        return self.query_logs(
            resource_type=resource_type,
            resource_id=resource_id,
            workspace_id=workspace_id,
            limit=limit,
        )

    def get_error_logs(
        self,
        workspace_id: str | None = None,
        user_id: str | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """Get error logs with optional filtering.

        Args:
            workspace_id: Filter by workspace ID
            user_id: Filter by user ID
            start_time: Filter by start time
            end_time: Filter by end time
            limit: Maximum number of results

        Returns:
            List of error log entries
        """
        return self.query_logs(
            action="error",
            workspace_id=workspace_id,
            user_id=user_id,
            start_time=start_time,
            end_time=end_time,
            limit=limit,
        )
