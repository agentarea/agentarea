from uuid import UUID


class StreamError(Exception):
    """Base for stream failures a caller can act on."""


class StreamQuotaExceededError(StreamError):
    def __init__(self, workspace_id: str, limit: int):
        super().__init__(f"Workspace {workspace_id} exceeded {limit} events per minute")
        self.workspace_id = workspace_id
        self.limit = limit


class StreamNotFoundError(StreamError):
    def __init__(self, stream_id: UUID | str):
        super().__init__(f"Stream {stream_id} not found")
        self.stream_id = stream_id


class StreamEventNotFoundError(StreamError):
    """No stream of the workspace holds an event with this id (or it aged out)."""


class StreamNameTakenError(StreamError):
    """Another stream in the workspace already has this name."""

    def __init__(self, name: str, message: str | None = None):
        super().__init__(message or f"A stream named {name!r} already exists in this workspace")
        self.name = name


class StreamSourceNotFoundError(StreamError):
    def __init__(self, source_id: UUID | str):
        super().__init__(f"Source {source_id} not found in this stream")
        self.source_id = source_id


class StreamInUseError(StreamError):
    """Triggers listen to the stream or forwards write into it; deleting it would strand them."""

    def __init__(self, stream_id: UUID, trigger_ids: list[UUID], forwards: list[tuple[UUID, UUID]]):
        reasons = []
        if trigger_ids:
            listed = ", ".join(str(t) for t in trigger_ids)
            reasons.append(
                f"trigger {listed} subscribes to it; delete the trigger first"
                if len(trigger_ids) == 1
                else f"triggers {listed} subscribe to it; delete those triggers first"
            )
        if forwards:
            listed = ", ".join(f"{sub} on stream {stream}" for sub, stream in forwards)
            reasons.append(
                f"forward {listed} writes into it; remove that forward from its stream first"
                if len(forwards) == 1
                else f"forwards {listed} write into it; remove each forward from its stream first"
            )
        super().__init__(f"Stream {stream_id} is in use: {'; '.join(reasons)}")
        self.stream_id = stream_id
        self.trigger_ids = trigger_ids
        self.forwards = forwards


class TriggerSubscriptionNotFoundError(StreamError):
    def __init__(self, trigger_id: UUID | str):
        super().__init__(
            f"Trigger {trigger_id} has no stream subscription, so its filter cannot be "
            "changed; its stream may have been deleted. Delete the trigger and create it "
            "again on a stream that exists"
        )
        self.trigger_id = trigger_id


class SubscriptionNotFoundError(StreamError):
    def __init__(self, subscription_id: UUID | str):
        super().__init__(f"Subscription {subscription_id} not found in this stream")
        self.subscription_id = subscription_id


class NotAForwardError(StreamError):
    """A trigger's subscription lives and dies with its trigger, never on its own."""

    def __init__(self, subscription_id: UUID, trigger_id: UUID | None):
        super().__init__(
            f"Subscription {subscription_id} belongs to trigger {trigger_id}, not a forward; "
            "it is removed by deleting the trigger"
        )
        self.subscription_id = subscription_id
        self.trigger_id = trigger_id


class ForwardLoopError(StreamError):
    """A forward that would write into its own input, or past the causation depth."""
