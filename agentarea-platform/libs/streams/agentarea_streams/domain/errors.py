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


class StreamManagedByPlatformError(StreamError):
    """The platform stream, or its source, is the platform's: members read it and subscribe to it."""


class StreamInUseError(StreamError):
    """Triggers listen to it, or forwards or processors write into it: deleting would strand them."""

    def __init__(
        self,
        stream_id: UUID,
        trigger_ids: list[UUID],
        forwards: list[tuple[UUID, UUID]],
        processors: list[tuple[UUID, UUID]] | None = None,
    ):
        processors = processors or []
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
        if processors:
            listed = ", ".join(f"{sub} on stream {stream}" for sub, stream in processors)
            reasons.append(
                f"processor {listed} writes into it; delete that processor first "
                "(streams_delete_processor)"
                if len(processors) == 1
                else f"processors {listed} write into it; delete each processor first "
                "(streams_delete_processor)"
            )
        super().__init__(f"Stream {stream_id} is in use: {'; '.join(reasons)}")
        self.stream_id = stream_id
        self.trigger_ids = trigger_ids
        self.forwards = forwards
        self.processors = processors


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


class ExternalSubscriptionLimitError(StreamError):
    def __init__(self, limit: int):
        super().__init__(f"The workspace already has {limit} external subscriptions")
        self.limit = limit


class ProcessorCodeError(StreamError):
    """A processor's code that cannot be run, or that holds a secret; refused at create."""


class ProcessorLoopError(StreamError):
    """A processor that would write into its own input stream, or with no output at all."""


class NotAProcessorError(StreamError):
    def __init__(self, subscription_id: UUID):
        super().__init__(f"Subscription {subscription_id} is not a processor")
        self.subscription_id = subscription_id


class ProcessorFailedError(Exception):
    """The code ran and failed: an error reaction, never retried."""


class ProcessorRuntimeUnavailableError(Exception):
    """The sandbox could not run the code; the event is redelivered."""
