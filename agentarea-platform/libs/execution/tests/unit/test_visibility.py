"""Tests for event visibility filtering."""

from agentarea_execution.workflows.visibility import (
    EventVisibility,
    PresentationMode,
    is_visible,
)


class TestEventVisibility:
    """Test event visibility categories."""

    def test_result_events_visible_in_all_modes(self):
        """Result events should be visible in every presentation mode."""
        for event_type in EventVisibility.RESULT:
            assert is_visible(event_type, PresentationMode.VERBOSE)
            assert is_visible(event_type, PresentationMode.CONCISE)
            assert is_visible(event_type, PresentationMode.SUMMARY)
            assert is_visible(event_type, PresentationMode.SILENT)

    def test_interaction_events_visible_except_silent(self):
        """Interaction events should be hidden in silent mode."""
        for event_type in EventVisibility.INTERACTION:
            assert is_visible(event_type, PresentationMode.VERBOSE)
            assert is_visible(event_type, PresentationMode.CONCISE)
            assert is_visible(event_type, PresentationMode.SUMMARY)
            assert not is_visible(event_type, PresentationMode.SILENT)

    def test_status_events_visible_in_verbose_and_concise(self):
        """Status events should only be visible in verbose and concise modes."""
        for event_type in EventVisibility.STATUS:
            assert is_visible(event_type, PresentationMode.VERBOSE)
            assert is_visible(event_type, PresentationMode.CONCISE)
            assert not is_visible(event_type, PresentationMode.SUMMARY)
            assert not is_visible(event_type, PresentationMode.SILENT)

    def test_internal_events_only_verbose(self):
        """Internal events should only be visible in verbose mode."""
        for event_type in EventVisibility.INTERNAL:
            assert is_visible(event_type, PresentationMode.VERBOSE)
            assert not is_visible(event_type, PresentationMode.CONCISE)
            assert not is_visible(event_type, PresentationMode.SUMMARY)
            assert not is_visible(event_type, PresentationMode.SILENT)

    def test_unknown_event_not_visible(self):
        """Unknown event types should not be visible."""
        assert not is_visible("SomeRandomEvent", PresentationMode.CONCISE)

    def test_unknown_presentation_falls_back_to_concise(self):
        """Unknown presentation mode should fall back to concise behavior."""
        assert is_visible("task.completed", "unknown_mode")
        assert not is_visible("llm.call.chunk", "unknown_mode")

    def test_canonical_emit_names_are_visible(self):
        """The emit-side now canonicalizes event types; the visibility gate must
        recognize the canonical names for events that flow through channels."""
        # Terminal (RESULT) — visible everywhere including silent.
        assert is_visible("task.completed", PresentationMode.SILENT)
        assert is_visible("task.failed", PresentationMode.SILENT)
        assert is_visible("task.cancelled", PresentationMode.SILENT)
        # Interaction — visible except silent.
        assert is_visible("input.request", PresentationMode.CONCISE)
        assert not is_visible("input.request", PresentationMode.SILENT)
        # Status — verbose + concise only.
        assert is_visible("tool.call", PresentationMode.CONCISE)
        assert not is_visible("tool.call", PresentationMode.SILENT)
        # Internal — verbose only.
        assert is_visible("llm.call.chunk", PresentationMode.VERBOSE)
        assert not is_visible("llm.call.chunk", PresentationMode.CONCISE)

    def test_no_overlap_between_categories(self):
        """Event categories should not overlap."""
        all_categories = [
            EventVisibility.RESULT,
            EventVisibility.INTERACTION,
            EventVisibility.STATUS,
            EventVisibility.INTERNAL,
        ]
        for i, cat_a in enumerate(all_categories):
            for cat_b in all_categories[i + 1 :]:
                assert not cat_a & cat_b, f"Overlap found: {cat_a & cat_b}"
