"""Tests for A2UI (Agent-to-User Interface) v0.9 event models."""

from uuid import uuid4

from agentarea_common.events.event_models import (
    A2UICreateSurfaceEvent,
    A2UIDeleteSurfaceEvent,
    A2UIUpdateComponentsEvent,
    A2UIUpdateDataModelEvent,
    EventType,
)
from agentarea_execution.workflows.events import (
    A2UICreateSurfaceEvent as WfCreateSurface,
    A2UIDeleteSurfaceEvent as WfDeleteSurface,
    A2UIUpdateComponentsEvent as WfUpdateComponents,
    A2UIUpdateDataModelEvent as WfUpdateDataModel,
    EVENT_CLASS_MAPPING,
    create_event_from_dict,
    event_to_dict,
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


# ── Domain event models (event_models.py) ────────────────────────────────────


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


# ── Workflow event models (workflows/events.py) ──────────────────────────────


class TestWorkflowA2UIEvents:
    """Test the workflow-level A2UI event dataclasses and their mappings."""

    def test_class_mapping_has_all_a2ui_events(self):
        assert "A2UICreateSurface" in EVENT_CLASS_MAPPING
        assert "A2UIUpdateComponents" in EVENT_CLASS_MAPPING
        assert "A2UIUpdateDataModel" in EVENT_CLASS_MAPPING
        assert "A2UIDeleteSurface" in EVENT_CLASS_MAPPING

    def test_create_surface_defaults(self):
        ev = WfCreateSurface(surface_id="s1")
        assert ev.surface_id == "s1"
        assert ev.catalog_id == BASIC_CATALOG
        assert ev.send_data_model is False

    def test_update_components_roundtrip(self):
        ev = WfUpdateComponents(surface_id="s1", components=SAMPLE_COMPONENTS)
        d = event_to_dict(ev)
        assert d["event_type"] == "A2UIUpdateComponents"
        assert len(d["data"]["components"]) == 4

    def test_update_data_model_roundtrip(self):
        ev = WfUpdateDataModel(surface_id="s1", path="/user/name", value="Jane")
        d = event_to_dict(ev)
        assert d["event_type"] == "A2UIUpdateDataModel"
        assert d["data"]["path"] == "/user/name"
        assert d["data"]["value"] == "Jane"

    def test_delete_surface_roundtrip(self):
        ev = WfDeleteSurface(surface_id="s1")
        d = event_to_dict(ev)
        assert d["event_type"] == "A2UIDeleteSurface"
        assert d["data"]["surface_id"] == "s1"

    def test_create_event_from_dict_create_surface(self):
        ev = create_event_from_dict(
            "A2UICreateSurface",
            {"surface_id": "s1", "catalog_id": BASIC_CATALOG},
        )
        assert isinstance(ev, WfCreateSurface)
        assert ev.surface_id == "s1"

    def test_create_event_from_dict_update_components(self):
        ev = create_event_from_dict(
            "A2UIUpdateComponents",
            {"surface_id": "s1", "components": SAMPLE_COMPONENTS},
        )
        assert isinstance(ev, WfUpdateComponents)
        assert len(ev.components) == 4

    def test_create_event_from_dict_update_data_model(self):
        ev = create_event_from_dict(
            "A2UIUpdateDataModel",
            {"surface_id": "s1", "path": "/x", "value": 42},
        )
        assert isinstance(ev, WfUpdateDataModel)
        assert ev.value == 42

    def test_create_event_from_dict_delete_surface(self):
        ev = create_event_from_dict(
            "A2UIDeleteSurface",
            {"surface_id": "s1"},
        )
        assert isinstance(ev, WfDeleteSurface)
        assert ev.surface_id == "s1"
