"""The manifest is what a platform registry is: reconcile applies every field of it.

A changed ``source_url``, ``source_type``, ``source_ref`` or ``source_path`` used
to be ignored for an existing registry, so moving a source silently kept syncing
the old one. They are applied now (the service clears the stored ETag, so the
next sync reads the new source in full), as are ``mode``, ``trust``,
``recommendation_priority`` and the credentials reference. A ``github`` entry is
a skills registry without fetching anything to find out.
"""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from agentarea_api import cli


class RecordingService:
    def __init__(self):
        self.updates: list[dict] = []

    async def update_registry(self, registry_id, **fields):
        self.updates.append(fields)
        return SimpleNamespace(id=registry_id, **fields)


def _existing(**fields):
    values = {
        "id": uuid4(),
        "name": "acme",
        "registry_type": "skills",
        "source_type": "url",
        "source_url": "https://old.example/skills.json",
        "source_ref": None,
        "source_path": None,
        "mode": "mirror",
        "trust": "official",
        "recommendation_priority": 100,
        "credentials_secret_ref": None,
    }
    return SimpleNamespace(**{**values, **fields})


async def test_a_moved_source_is_applied_to_the_existing_registry():
    service = RecordingService()
    existing = _existing()

    changes = await cli.reconcile_existing_registry(
        service,
        existing,
        {
            "name": "acme",
            "type": "skills",
            "source_type": "github",
            "source_url": "acme/skills",
            "source_ref": "main",
            "source_path": "skills",
        },
        credentials_secret_ref=None,
    )

    assert changes == ["source_type", "source_url", "source_ref", "source_path"]
    assert service.updates == [
        {
            "source_type": "github",
            "source_url": "acme/skills",
            "source_ref": "main",
            "source_path": "skills",
        }
    ]


async def test_an_unchanged_entry_changes_nothing():
    service = RecordingService()
    existing = _existing()

    changes = await cli.reconcile_existing_registry(
        service,
        existing,
        {"name": "acme", "source_url": existing.source_url, "mode": "mirror"},
        credentials_secret_ref=None,
    )

    assert changes == []
    assert service.updates == []


async def test_labels_priority_and_credentials_are_applied_together():
    service = RecordingService()
    secret = uuid4()

    changes = await cli.reconcile_existing_registry(
        service,
        _existing(),
        {
            "name": "acme",
            "source_url": "https://old.example/skills.json",
            "mode": "upstream",
            "trust": "community",
            "recommendation_priority": 10,
        },
        credentials_secret_ref=secret,
    )

    assert changes == ["mode", "trust", "recommendation_priority", "credentials_secret_ref"]
    assert service.updates == [
        {
            "mode": "upstream",
            "trust": "community",
            "recommendation_priority": 10,
            "credentials_secret_ref": secret,
        }
    ]


async def test_credentials_dropped_from_the_entry_are_dropped_from_the_registry():
    service = RecordingService()

    changes = await cli.reconcile_existing_registry(
        service,
        _existing(credentials_secret_ref=uuid4()),
        {"name": "acme", "source_url": "https://old.example/skills.json"},
        credentials_secret_ref=None,
    )

    assert changes == ["credentials_secret_ref"]
    assert service.updates == [{"credentials_secret_ref": None}]


async def test_a_changed_type_is_refused_with_what_to_do():
    with pytest.raises(ValueError, match="new name"):
        await cli.reconcile_existing_registry(
            RecordingService(),
            _existing(),
            {"name": "acme", "type": "agents", "source_url": "https://old.example/skills.json"},
            credentials_secret_ref=None,
        )


def _never_detect(_url):
    raise AssertionError("a github entry is not fetched to detect its type")


def test_a_github_entry_is_a_skills_registry_without_detection():
    entry = {"name": "acme", "source_type": "github", "source_url": "acme/skills"}

    assert cli.manifest_registry_type(entry, _never_detect) == "skills"


def test_a_github_entry_of_another_type_is_refused():
    entry = {"name": "acme", "type": "agents", "source_type": "github", "source_url": "a/b"}

    with pytest.raises(ValueError, match="holds skills"):
        cli.manifest_registry_type(entry, _never_detect)


def test_an_index_entry_without_a_type_is_detected_from_its_source():
    entry = {"name": "acme", "source_url": "https://x.example/agents.json"}

    assert cli.manifest_registry_type(entry, lambda _url: "agents") == "agents"
    assert cli.manifest_registry_type({**entry, "type": "skills"}, _never_detect) == "skills"
