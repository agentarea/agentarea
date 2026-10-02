"""Event publisher utilities for activities."""

import logging
import time
from collections.abc import Callable
from datetime import UTC, datetime
from uuid import uuid4

from agentarea_common.broker import BrokerClient
from agentarea_common.events.contract import LLM_CHUNK
from agentarea_common.events.task_stream import publish_task_event

logger = logging.getLogger(__name__)

# Each chunk carries the whole reply so far, so one per provider delta sends
# O(n^2) bytes; deltas inside this window collapse into the next snapshot.
CHUNK_PUBLISH_INTERVAL_SECONDS = 0.1


def create_event_publisher(
    broker_client: BrokerClient,
    task_id: str,
    execution_id: str | None = None,
    iteration: int | None = None,
    *,
    min_interval_seconds: float = CHUNK_PUBLISH_INTERVAL_SECONDS,
    clock: Callable[[], float] = time.monotonic,
):
    """Create a publisher that converts callback deltas into chunk snapshots.

    ``execution_id`` and ``iteration`` identify the LLM call this chunk belongs
    to. The read side supersedes by part id, and an llm part's id is built from
    exactly these two fields, so a chunk without them cannot be matched to the
    call it is streaming and never renders as text.

    Each snapshot carries cumulative ``chunk`` text and ``thinking`` reasoning
    for this invocation, including the empty final callback. A new publisher
    starts a fresh snapshot for a retry of the same part. At most one snapshot
    goes out per ``min_interval_seconds``; the final one and the first after a
    switch between text and thinking always go out.

    Snapshots are XADDed to the per-task live stream (ADR-0018) only; the DB
    keeps durable events, and the completed call supersedes the last snapshot.
    """
    text = ""
    thinking = ""
    published_at: float | None = None
    published_type: str | None = None

    async def publish_chunk_event(
        chunk: str,
        chunk_index: int,
        is_final: bool = False,
        chunk_type: str = "text",
    ):
        """Publish LLM chunk event.

        Args:
            chunk: The incoming delta for the selected channel.
            chunk_index: Sequence number.
            is_final: Whether this is the last chunk.
            chunk_type: "text" for regular content, "thinking" for reasoning blocks.
        """
        nonlocal text, thinking, published_at, published_type

        if chunk_type == "thinking":
            thinking += chunk
        else:
            text += chunk

        now = clock()
        if not (
            is_final
            or published_at is None
            or chunk_type != published_type
            or now - published_at >= min_interval_seconds
        ):
            return
        published_at, published_type = now, chunk_type

        try:
            await publish_task_event(
                broker_client,
                task_id=task_id,
                event_type=LLM_CHUNK,
                data={
                    "task_id": task_id,
                    "execution_id": execution_id,
                    "iteration": iteration,
                    "chunk": text,
                    "thinking": thinking,
                    "chunk_index": chunk_index,
                    "is_final": is_final,
                    "chunk_type": chunk_type,
                },
                event_id=str(uuid4()),
                timestamp=datetime.now(UTC).isoformat(),
            )
        except Exception:
            # A snapshot is superseded by the next one and by the completed
            # call, so a lost one must not fail (and re-bill) the model call.
            logger.error(f"Failed to publish chunk event for task {task_id}", exc_info=True)

    return publish_chunk_event


def _is_auth_error(error: Exception) -> bool:
    """Check if error is authentication-related."""
    error_str = str(error).lower()
    error_type = type(error).__name__
    return (
        "authenticationerror" in error_type.lower()
        or "api_key" in error_str
        or "authentication" in error_str
        or "unauthorized" in error_str
        or "401" in error_str
    )


def _is_rate_limit_error(error: Exception) -> bool:
    """Check if error is rate limiting-related."""
    error_str = str(error).lower()
    error_type = type(error).__name__
    return (
        "ratelimiterror" in error_type.lower()
        or "rate limit" in error_str
        or "too many requests" in error_str
        or "429" in error_str
    )


def _is_quota_error(error: Exception) -> bool:
    """Check if error is quota/billing-related."""
    error_str = str(error).lower()
    return (
        "quota" in error_str
        or "billing" in error_str
        or "exceeded" in error_str
        or "insufficient funds" in error_str
        or "insufficient balance" in error_str
        or "no resource package" in error_str
        or "please recharge" in error_str
    )


def _is_model_error(error: Exception) -> bool:
    """Check if error is model-related."""
    error_str = str(error).lower()
    return "model" in error_str and (
        "not found" in error_str or "does not exist" in error_str or "invalid" in error_str
    )


def _is_non_retryable_error(error: Exception) -> bool:
    """Determine if error should not be retried.

    A rate limit (429) is transient and takes precedence: retry it with backoff.
    Without this, the quota check's broad ``"exceeded"`` match swallows
    "rate limit exceeded" and wrongly fails the whole task fast.
    """
    if _is_rate_limit_error(error):
        return False
    error_str = str(error).lower()
    accounting_contract_error = (
        "usage accounting unavailable" in error_str
        or "returned no usage" in error_str
        or "pricing is not configured" in error_str
        or "effective policy is missing required runtime limit" in error_str
    )
    # A refused endpoint stays refused until the member changes the config.
    refused_endpoint = "endpoint is not an allowed address" in error_str
    return (
        accounting_contract_error
        or refused_endpoint
        or _is_auth_error(error)
        or _is_quota_error(error)
        or _is_model_error(error)
    )
