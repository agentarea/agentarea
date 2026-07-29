"""Tests for A2UI (Agent-to-User Interface) v0.9 event models."""

from uuid import uuid4

from agentarea_common.events.event_models import (
    A2UICreateSurfaceEvent,
    A2UIDeleteSurfaceEvent,
    A2UIUpdateComponentsEvent,
    A2UIUpdateDataModelEvent,
    EventType,
)

BASIC_CATALOG = "https://a2ui.org/specification/v0_9/basic_catalog.json"

SAMPLE_COMPONENTS = [
    {"id": "root", "component": "Column", "children": ["title", "btn"]},
    {"id": "title", "component": "Text", "text": "Hello"},
    {
        "id": "btn",
        "component": "Button",
        "child": "btn_label",
        "action": {"event": {"name": "clicked"}},
    },
    {"id": "btn_label", "component": "Text", "text": "Click me"},
]


class TestA2UICreateSurfaceEvent:
    def test_defaults(self):
        ev = A2UICreateSurfaceEvent(
            aggregate_id="task-1",
            task_id=uuid4(),
            execution_id="exec-1",
            agent_id=uuid4(),
            surface_id="s1",
        )
        assert ev.event_type == EventType.A2UI_CREATE_SURFACE
        assert ev.surface_id == "s1"
        assert ev.catalog_id == BASIC_CATALOG
        assert ev.theme is None
        assert ev.send_data_model is False

    def test_custom_theme(self):
        ev = A2UICreateSurfaceEvent(
            aggregate_id="task-1",
            task_id=uuid4(),
            execution_id="exec-1",
            agent_id=uuid4(),
            surface_id="s1",
            theme={"primaryColor": "#00BFFF", "agentDisplayName": "TestBot"},
        )
        assert ev.theme["primaryColor"] == "#00BFFF"

    def test_to_envelope(self):
        ev = A2UICreateSurfaceEvent(
            aggregate_id="task-1",
            task_id=uuid4(),
            execution_id="exec-1",
            agent_id=uuid4(),
            surface_id="s1",
        )
        envelope = ev.to_envelope()
        assert envelope.event_type == "workflow.A2UICreateSurface"
        assert "surface_id" in envelope.data

    def test_serialization_roundtrip(self):
        ev = A2UICreateSurfaceEvent(
            aggregate_id="task-1",
            task_id=uuid4(),
            execution_id="exec-1",
            agent_id=uuid4(),
            surface_id="s1",
            catalog_id=BASIC_CATALOG,
        )
        data = ev.model_dump()
        restored = A2UICreateSurfaceEvent(**data)
        assert restored.surface_id == ev.surface_id
        assert restored.catalog_id == ev.catalog_id


class TestA2UIUpdateComponentsEvent:
    def test_with_components(self):
        ev = A2UIUpdateComponentsEvent(
            aggregate_id="task-1",
            task_id=uuid4(),
            execution_id="exec-1",
            agent_id=uuid4(),
            surface_id="s1",
            components=SAMPLE_COMPONENTS,
        )
        assert ev.event_type == EventType.A2UI_UPDATE_COMPONENTS
        assert len(ev.components) == 4
        assert ev.components[0]["id"] == "root"
        assert ev.components[0]["component"] == "Column"

    def test_to_envelope(self):
        ev = A2UIUpdateComponentsEvent(
            aggregate_id="task-1",
            task_id=uuid4(),
            execution_id="exec-1",
            agent_id=uuid4(),
            surface_id="s1",
            components=SAMPLE_COMPONENTS,
        )
        envelope = ev.to_envelope()
        assert envelope.event_type == "workflow.A2UIUpdateComponents"
        assert len(envelope.data["components"]) == 4


class TestA2UIUpdateDataModelEvent:
    def test_defaults(self):
        ev = A2UIUpdateDataModelEvent(
            aggregate_id="task-1",
            task_id=uuid4(),
            execution_id="exec-1",
            agent_id=uuid4(),
            surface_id="s1",
        )
        assert ev.path == "/"
        assert ev.value is None

    def test_with_path_and_value(self):
        ev = A2UIUpdateDataModelEvent(
            aggregate_id="task-1",
            task_id=uuid4(),
            execution_id="exec-1",
            agent_id=uuid4(),
            surface_id="s1",
            path="/user/name",
            value="Jane Doe",
        )
        assert ev.path == "/user/name"
        assert ev.value == "Jane Doe"

    def test_to_envelope(self):
        ev = A2UIUpdateDataModelEvent(
            aggregate_id="task-1",
            task_id=uuid4(),
            execution_id="exec-1",
            agent_id=uuid4(),
            surface_id="s1",
            path="/user/name",
            value="Jane Doe",
        )
        envelope = ev.to_envelope()
        assert envelope.event_type == "workflow.A2UIUpdateDataModel"
        assert envelope.data["path"] == "/user/name"
        assert envelope.data["value"] == "Jane Doe"


class TestA2UIDeleteSurfaceEvent:
    def test_basic(self):
        ev = A2UIDeleteSurfaceEvent(
            aggregate_id="task-1",
            task_id=uuid4(),
            execution_id="exec-1",
            agent_id=uuid4(),
            surface_id="s1",
        )
        assert ev.event_type == EventType.A2UI_DELETE_SURFACE
        assert ev.surface_id == "s1"

    def test_to_envelope(self):
        ev = A2UIDeleteSurfaceEvent(
            aggregate_id="task-1",
            task_id=uuid4(),
            execution_id="exec-1",
            agent_id=uuid4(),
            surface_id="s1",
        )
        envelope = ev.to_envelope()
        assert envelope.event_type == "workflow.A2UIDeleteSurface"
