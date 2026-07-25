"""Tests for the trigger catalog — the channel registry served to the UI."""

from agentarea_triggers.domain.channel_events import (
    CHANNEL_EVENTS,
    TRIGGER_CATALOG,
    get_trigger_catalog,
)


def test_every_event_channel_has_a_catalog_entry():
    # A channel with an event registry but no catalog entry is invisible in the
    # UI and falls back to the generic webhook — every registry key must be
    # reachable from the catalog.
    catalog_webhook_types = {
        entry["webhook_type"] for entry in TRIGGER_CATALOG if entry.get("webhook_type")
    }
    missing = set(CHANNEL_EVENTS) - catalog_webhook_types
    assert not missing, f"CHANNEL_EVENTS channels missing from TRIGGER_CATALOG: {missing}"


def test_catalog_entries_have_required_fields():
    for entry in TRIGGER_CATALOG:
        assert entry.get("id"), f"catalog entry without id: {entry}"
        assert entry.get("name"), f"catalog entry {entry['id']} has no name"
        assert entry.get("kind") in {"schedule", "messaging", "event"}, (
            f"catalog entry {entry['id']} has unknown kind {entry.get('kind')!r}"
        )
        assert entry.get("backend_type") in {"cron", "webhook", "polling"}


def test_catalog_merges_events_for_webhook_channels():
    catalog = {entry["id"]: entry for entry in get_trigger_catalog()}
    assert "pull_request" in catalog["github"]["events"]
    assert "payment_intent.succeeded" in catalog["stripe"]["events"]
    assert "Issue" in catalog["linear"]["events"]
