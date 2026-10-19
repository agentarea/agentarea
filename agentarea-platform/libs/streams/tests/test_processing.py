"""What the platform did with an event, from its routing and its recorded reactions."""

import pytest
from agentarea_streams.domain.processing import ProcessingStatus, processing_status


@pytest.mark.parametrize(
    ("routed", "subscribers", "reacted", "skipped", "errors", "expected"),
    [
        (False, None, 0, 0, 0, ProcessingStatus.QUEUED),
        (True, 3, 1, 0, 0, ProcessingStatus.PROCESSING),
        (True, 3, 0, 0, 0, ProcessingStatus.PROCESSING),
        (True, 3, 3, 1, 0, ProcessingStatus.HANDLED),
        (True, 1, 1, 0, 0, ProcessingStatus.HANDLED),
        (True, 3, 2, 0, 1, ProcessingStatus.ERROR),
        (True, 3, 3, 2, 1, ProcessingStatus.ERROR),
        (True, 0, 0, 0, 0, ProcessingStatus.NO_HANDLERS),
        (True, 3, 3, 3, 0, ProcessingStatus.SKIPPED),
    ],
)
def test_every_status(routed, subscribers, reacted, skipped, errors, expected):
    assert (
        processing_status(
            routed=routed,
            subscribers=subscribers,
            reacted=reacted,
            skipped=skipped,
            errors=errors,
        )
        is expected
    )


def test_a_subscription_resumed_after_routing_still_ends_the_event():
    assert (
        processing_status(routed=True, subscribers=1, reacted=2, skipped=0, errors=0)
        is ProcessingStatus.HANDLED
    )
    assert (
        processing_status(routed=True, subscribers=0, reacted=1, skipped=1, errors=0)
        is ProcessingStatus.SKIPPED
    )


def test_a_routed_event_names_its_subscriber_count():
    with pytest.raises(ValueError, match="subscribers"):
        processing_status(routed=True, subscribers=None, reacted=0, skipped=0, errors=0)
