"""How the workspace feed reads its kind filter."""

from agentarea_streams.domain.feed import FeedFilter


def test_a_kind_ending_in_a_wildcard_is_a_prefix():
    assert FeedFilter(kind="order.*").kind_prefix() == "order."
    assert FeedFilter(kind="order.*").exact_kind() is None


def test_any_other_kind_is_exact():
    assert FeedFilter(kind="order.paid").exact_kind() == "order.paid"
    assert FeedFilter(kind="order.paid").kind_prefix() is None
    assert FeedFilter(kind="order*").exact_kind() == "order*"


def test_no_kind_filters_nothing():
    assert FeedFilter().kind_prefix() is None
    assert FeedFilter().exact_kind() is None
