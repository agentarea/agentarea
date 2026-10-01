"""Vocabulary of the non-chat model APIs: video job states and decision questions."""

from enum import StrEnum


class VideoJobStatus(StrEnum):
    """A video generation's state, as the provider reports it (OpenRouter ``/videos``)."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"

    @property
    def is_running(self) -> bool:
        return self in (VideoJobStatus.PENDING, VideoJobStatus.IN_PROGRESS)

    @property
    def is_failed(self) -> bool:
        return self in (VideoJobStatus.FAILED, VideoJobStatus.CANCELLED, VideoJobStatus.EXPIRED)


class DecisionQuestionType(StrEnum):
    """A decision model's question types (``/systemone``); each answer carries its value
    under the key of the same name.
    """

    CHOICE = "choice"
    NOUL = "noul"
    SCORE = "score"
