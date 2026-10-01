"""What a model produces."""

from enum import StrEnum


class ModelKind(StrEnum):
    """What a model produces, which decides every surface it may be bound to.

    An agent's main model is ``chat``; the media toolset takes ``image`` and
    ``video``; the decide toolset and decision-backed trigger conditions take
    ``decision``. A model has exactly one kind.
    """

    CHAT = "chat"
    EMBEDDING = "embedding"
    IMAGE = "image"
    VIDEO = "video"
    DECISION = "decision"

    @property
    def priced_per_token(self) -> bool:
        """Whether a run is billed from the spec's per-token prices.

        The other kinds are billed at the cost the provider reports per call, so a
        spec of theirs carries no per-token price and no context window.
        """
        return self in (ModelKind.CHAT, ModelKind.EMBEDDING)
