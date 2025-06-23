from enum import Enum


class EventType(Enum):
    TASK_CREATED = "TaskCreated"
    TASK_UPDATED = "TaskUpdated"
    TASK_COMPLETED = "TaskCompleted"
    TASK_FAILED = "TaskFailed"
    TASK_STATUS_CHANGED = "TaskStatusChanged"
    TASK_ASSIGNED = "TaskAssigned"
    TASK_CANCELED = "TaskCanceled"
    TASK_INPUT_REQUIRED = "TaskInputRequired"
    TASK_ARTIFACT_ADDED = "TaskArtifactAdded"
