"""The source-type catalog must hand the UI a ready icon URL for every entry.

Which source types exist is an open set that grows by configuration, so the
frontend carries no table of them -- it renders whatever ``icon_url`` it is
given. That only holds if every catalog entry resolves to an asset that is
actually shipped, which is what these tests pin down.
"""

import json
from pathlib import Path

import agentarea_api
from agentarea_api.api.v1._icons import CHANNEL_ICON_NAMESPACE, build_icon_url
from agentarea_streams.domain.source_types import SourceTypeEntry

ICON_DIR = Path(agentarea_api.__file__).parent / "static" / "icons" / CHANNEL_ICON_NAMESPACE
CATALOG = Path(__file__).resolve().parents[4] / "data" / "catalog" / "source-types.json"


def _entries() -> list[SourceTypeEntry]:
    raw = json.loads(CATALOG.read_text())["source_types"]
    return [SourceTypeEntry.model_validate(entry) for entry in raw]


def test_every_catalog_entry_declares_an_icon():
    for entry in _entries():
        assert entry.icon, f"{entry.slug} has no icon"


def test_every_declared_icon_is_shipped():
    # A missing file renders as a broken image in the listing, and the frontend
    # has no per-entry fallback to save it -- by design.
    for entry in _entries():
        if entry.icon.startswith(("http://", "https://")):
            continue
        assert (ICON_DIR / f"{entry.icon}.svg").is_file(), (
            f"{entry.slug} points at missing {entry.icon}.svg"
        )


def test_catalog_icon_resolves_into_the_channels_namespace(monkeypatch):
    monkeypatch.setenv("AGENTAREA_API_URL", "https://api.agentarea.ai")
    from agentarea_common.config.app import get_app_settings

    get_app_settings.cache_clear()

    assert (
        build_icon_url(CHANNEL_ICON_NAMESPACE, "github")
        == "https://api.agentarea.ai/static/icons/channels/github.svg"
    )


def test_namespaces_do_not_collide():
    from agentarea_api.api.v1._provider_icons import build_provider_icon_url

    assert build_provider_icon_url("github") != build_icon_url(CHANNEL_ICON_NAMESPACE, "github")
