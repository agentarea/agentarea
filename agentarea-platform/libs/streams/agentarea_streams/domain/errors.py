from uuid import UUID

from .keys import MAX_EVENT_BYTES


class StreamError(Exception):
    """Base for stream failures a caller can act on."""


class PayloadTooLargeError(StreamError):
    def __init__(self, size: int):
        super().__init__(
            f"Event data is {size} bytes; the limit is {MAX_EVENT_BYTES}. "
            "Attach large content as a workspace file and send its reference."
        )
        self.size = size


class StreamQuotaExceededError(StreamError):
    def __init__(self, workspace_id: str, limit: int):
        super().__init__(f"Workspace {workspace_id} exceeded {limit} events per minute")
        self.workspace_id = workspace_id
        self.limit = limit


class StreamNotFoundError(StreamError):
    def __init__(self, stream_id: UUID | str):
        super().__init__(f"Stream {stream_id} not found")
        self.stream_id = stream_id


class TriggerSubscriptionNotFoundError(StreamError):
    def __init__(self, trigger_id: UUID | str):
        super().__init__(f"No stream subscription for trigger {trigger_id}")
        self.trigger_id = trigger_id


class ForwardLoopError(StreamError):
    """A forward that would write into its own input, or past the causation depth."""


class LeaseLostError(StreamError):
    """Another dispatcher took the subscription; this one must stop writing for it."""
