"""Domain events the streams context publishes through the transactional outbox."""

# A stream's subscriptions were added, changed or removed; data carries stream_id.
SUBSCRIPTIONS_CHANGED = "streams.subscriptions.changed"
