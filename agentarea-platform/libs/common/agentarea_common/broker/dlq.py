"""Dead letters: the field a consumer records the failure in, and replay back to the source."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass

from .interface import BrokerClient

logger = logging.getLogger(__name__)

DEAD_LETTER_REASON_FIELD = "fatal_reason"
# The topic a dead letter came from, for a dead-letter topic shared by several partitions.
DEAD_LETTER_SOURCE_FIELD = "source_topic"
_DEAD_LETTER_FIELDS = frozenset({DEAD_LETTER_REASON_FIELD, DEAD_LETTER_SOURCE_FIELD})


@dataclass(frozen=True)
class ReplayResult:
    moved: int
    skipped: int = 0


def _target_of(fields: dict[str, str], targets: Sequence[str]) -> str | None:
    source = fields.get(DEAD_LETTER_SOURCE_FIELD)
    if len(targets) == 1:
        return targets[0] if source in (None, targets[0]) else None
    return source if source in targets else None


async def replay_dead_letters(
    broker: BrokerClient,
    *,
    dlq_stream: str,
    targets: Sequence[str],
    start: str = "-",
    end: str = "+",
    batch_size: int = 100,
) -> ReplayResult:
    """Move dead letters with ids in [`start`, `end`] from `dlq_stream` back to their source.

    The source is the one stream of `targets`, or, for a dead-letter stream
    shared by several partitions, the one the dead letter names; a dead letter
    naming no stream of `targets` stays. Each message is appended to its source
    without the dead-letter fields and removed from the dead-letter stream in
    one step, so a second run, or two operators at once, replays each once.
    """
    moved = 0
    skipped = 0
    cursor = start
    while True:
        batch = await broker.read_range(dlq_stream, start=cursor, end=end, count=batch_size)
        for msg in batch:
            target_stream = _target_of(msg.fields, targets)
            if target_stream is None:
                skipped += 1
                logger.error(
                    "dead letter %s on %s names source %r, not one of %s; left in place",
                    msg.id,
                    dlq_stream,
                    msg.fields.get(DEAD_LETTER_SOURCE_FIELD),
                    ", ".join(targets),
                )
                continue
            fields = {k: v for k, v in msg.fields.items() if k not in _DEAD_LETTER_FIELDS}
            new_id = await broker.move(dlq_stream, msg.id, target_stream, fields)
            if new_id is None:
                logger.info("dead letter %s on %s was already replayed", msg.id, dlq_stream)
                continue
            moved += 1
            logger.info(
                "replayed dead letter %s from %s to %s as %s (reason: %s)",
                msg.id,
                dlq_stream,
                target_stream,
                new_id,
                msg.fields.get(DEAD_LETTER_REASON_FIELD),
            )
        if len(batch) < batch_size:
            break
        cursor = f"({batch[-1].id}"
    logger.info("replayed %d dead letters from %s (%d left in place)", moved, dlq_stream, skipped)
    return ReplayResult(moved=moved, skipped=skipped)
