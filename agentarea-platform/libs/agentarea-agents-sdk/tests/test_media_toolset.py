"""The media toolset: files land in the workspace, costs reach the result."""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal

import pytest

from agentarea_agents_sdk.tools.code_tools_loader import get_code_tools_metadata
from agentarea_agents_sdk.tools.decorator_tool import ToolsetAdapter
from agentarea_agents_sdk.tools.file_toolset import InMemoryStorage
from agentarea_agents_sdk.tools.media_toolset import MediaToolset

WORKSPACE = "ws-1"


@dataclass
class _File:
    content: bytes
    media_type: str
    cost: Decimal | None = None
    cost_unknown: bool = False


@dataclass
class _Submitted:
    job_id: str
    status: str


@dataclass
class _Check:
    job_id: str
    status: str
    error: str | None = None
    video: _File | None = None
    cost_usd: Decimal | None = None
    cost: Decimal | None = None
    file_path: str | None = None
    cost_unknown: bool = False


class _Backend:
    def __init__(self, check: _Check | None = None, image: _File | None = None):
        self.check = check
        self.image = image or _File(
            content=b"\x89PNG....", media_type="image/png", cost=Decimal("4.00")
        )
        self.saved: list = []
        self.submitted: list = []

    async def generate_image(self, prompt, *, size=None):
        return self.image

    async def submit_video(self, prompt, **options):
        self.submitted.append((prompt, options))
        return _Submitted(job_id="our-job-id", status="pending")

    async def check_video(self, job_id):
        return self.check

    async def record_video_saved(self, job_id, file_path, cost_usd, cost):
        first = not self.saved
        self.saved.append((job_id, file_path, cost_usd, cost))
        return first


def _media(backend: _Backend, storage: InMemoryStorage, **flags) -> ToolsetAdapter:
    return ToolsetAdapter(
        MediaToolset(backend=backend, storage=storage, workspace_id=WORKSPACE, **flags)
    )


async def test_generate_image_saves_the_file_and_reports_path_and_cost():
    storage = InMemoryStorage()
    result = await _media(_Backend(), storage).execute(action="generate_image", prompt="a cat")

    assert result["success"] is True
    [path] = result["artifact_paths"]
    assert path.startswith("media/image-") and path.endswith(".png")
    assert result["model_cost"] == "4.00"
    assert (await storage.get(WORKSPACE, path)) == (b"\x89PNG....", "image/png")
    assert json.loads(result["result"])["file_path"] == path


async def test_generate_video_returns_our_job_id():
    backend = _Backend()
    result = await _media(backend, InMemoryStorage()).execute(
        action="generate_video", prompt="waves", duration=5
    )

    assert json.loads(result["result"]) == {"job_id": "our-job-id", "status": "pending"}
    assert backend.submitted == [
        ("waves", {"duration": 5, "resolution": None, "aspect_ratio": None})
    ]


async def test_a_running_video_reports_status_without_cost():
    backend = _Backend(_Check(job_id="j", status="in_progress"))
    result = await _media(backend, InMemoryStorage()).execute(action="get_video", job_id="j")

    assert result["success"] is True
    assert json.loads(result["result"])["status"] == "in_progress"
    assert "model_cost" not in result


async def test_a_finished_video_is_saved_and_billed_once():
    video = _File(content=b"mp4", media_type="video/mp4")
    backend = _Backend(
        _Check(
            job_id="j",
            status="completed",
            video=video,
            cost_usd=Decimal("1.5"),
            cost=Decimal("150"),
        )
    )
    storage = InMemoryStorage()
    media = _media(backend, storage)

    first = await media.execute(action="get_video", job_id="j")
    second = await media.execute(action="get_video", job_id="j")

    assert first["artifact_paths"] == ["media/video-j.mp4"]
    assert first["model_cost"] == "150"
    assert second["model_cost"] == "0"
    assert backend.saved[0] == ("j", "media/video-j.mp4", Decimal("1.5"), Decimal("150"))
    assert (await storage.get(WORKSPACE, "media/video-j.mp4")) == (b"mp4", "video/mp4")


async def test_an_image_of_unknown_cost_is_saved_and_says_its_cost_is_unknown():
    image = _File(content=b"\x89PNG....", media_type="image/png", cost_unknown=True)
    storage = InMemoryStorage()
    result = await _media(_Backend(image=image), storage).execute(
        action="generate_image", prompt="a cat"
    )

    assert result["success"] is True
    [path] = result["artifact_paths"]
    assert (await storage.get(WORKSPACE, path)) == (b"\x89PNG....", "image/png")
    assert result["cost_unknown"] is True
    assert "model_cost" not in result


async def test_a_finished_video_of_unknown_cost_is_saved_and_says_so():
    video = _File(content=b"mp4", media_type="video/mp4")
    backend = _Backend(_Check(job_id="j", status="completed", video=video, cost_unknown=True))
    storage = InMemoryStorage()

    result = await _media(backend, storage).execute(action="get_video", job_id="j")

    assert result["artifact_paths"] == ["media/video-j.mp4"]
    assert result["cost_unknown"] is True
    assert "model_cost" not in result
    assert backend.saved == [("j", "media/video-j.mp4", None, None)]
    assert (await storage.get(WORKSPACE, "media/video-j.mp4")) == (b"mp4", "video/mp4")


async def test_an_image_that_cannot_be_saved_still_reports_its_cost():
    class _FullDisk(InMemoryStorage):
        async def put(self, *args, **kwargs):
            raise OSError("disk full")

    result = await _media(_Backend(), _FullDisk()).execute(action="generate_image", prompt="a cat")

    assert result["success"] is False
    assert result["model_cost"] == "4.00"
    assert "disk full" in result["error"]


async def test_a_saved_video_reports_the_cost_only_to_its_billing_call():
    billed = _Check(job_id="j", status="completed", file_path="media/v.mp4", cost=Decimal("150"))
    not_billed = _Check(job_id="j", status="completed", file_path="media/v.mp4")

    retry = await _media(_Backend(billed), InMemoryStorage()).execute(action="get_video", job_id="j")
    other = await _media(_Backend(not_billed), InMemoryStorage()).execute(
        action="get_video", job_id="j"
    )

    assert retry["model_cost"] == "150"
    assert "model_cost" not in other


async def test_a_failed_video_is_a_failed_tool_result():
    backend = _Backend(_Check(job_id="j", status="failed", error="moderated"))
    result = await _media(backend, InMemoryStorage()).execute(action="get_video", job_id="j")

    assert result["success"] is False
    assert result["error"] == "moderated"


async def test_a_disabled_method_is_not_offered():
    toolset = MediaToolset(
        backend=_Backend(), storage=InMemoryStorage(), workspace_id=WORKSPACE, generate_video=False
    )

    assert set(toolset._tool_methods) == {"generate_image", "get_video"}


def test_the_toolset_is_registered_as_runtime_with_declared_effects():
    entry = get_code_tools_metadata()["agentarea/media"]

    assert entry["plane"] == "runtime"
    assert entry["available_methods"]
    assert all(m["effect"] in {"read", "write"} for m in entry["available_methods"])


def test_the_schema_builder_can_construct_it_bare():
    from agentarea_agents_sdk.tools.code_tools_loader import create_code_tool_instance

    assert create_code_tool_instance("agentarea/media", {}, extra_kwargs={"workspace_id": WORKSPACE})


def test_the_media_toolset_needs_a_workspace():
    with pytest.raises(ValueError, match="workspace_id"):
        MediaToolset(workspace_id="")


async def test_a_bare_toolset_refuses_to_run():
    result = await ToolsetAdapter(MediaToolset(workspace_id=WORKSPACE)).execute(
        action="generate_image", prompt="a cat"
    )

    assert result["success"] is False
    assert "no model backend" in result["error"]
