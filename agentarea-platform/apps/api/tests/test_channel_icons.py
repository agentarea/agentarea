"""The trigger catalog must hand the UI a ready icon URL for every channel.

Which channels exist is an open set that grows by configuration, so the
frontend carries no table of them — it renders whatever ``icon_url`` it is
given. That only holds if every catalog entry resolves to an asset that is
actually shipped, which is what these tests pin down.
"""

from pathlib import Path

import agentarea_api
from agentarea_api.api.v1._icons import CHANNEL_ICON_NAMESPACE, build_icon_url
from agentarea_triggers.domain.channel_events import get_trigger_catalog

ICON_DIR = Path(agentarea_api.__file__).parent / "static" / "icons" / CHANNEL_ICON_NAMESPACE


def test_every_catalog_entry_declares_an_icon():
    for entry in get_trigger_catalog():
        assert entry.get("icon"), f"{entry['id']} has no icon"


def test_every_declared_icon_is_shipped():
    # A missing file renders as a broken image in the listing, and the frontend
    # has no per-channel fallback to save it — by design.
    for entry in get_trigger_catalog():
        icon = entry["icon"]
        if icon.startswith(("http://", "https://")):
            continue
        assert (ICON_DIR / f"{icon}.svg").is_file(), f"{entry['id']} points at missing {icon}.svg"


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
