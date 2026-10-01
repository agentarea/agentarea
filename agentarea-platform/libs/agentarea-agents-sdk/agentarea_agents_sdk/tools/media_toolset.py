"""Image and video generation toolset.

Generated media is written to the task's live workspace (the sandbox filesystem
the shell and file tools see) and reported through ``artifact_paths``; its cost,
already converted to the billing currency, comes back as ``model_cost``. The models are the workspace's
model instances named in the toolset settings (``image_model_id``,
``video_model_id``); the platform resolves them into ``backend``.

Video generation is asynchronous: ``generate_video`` returns a job id and
``get_video`` polls it, saving the file once it is ready.
"""

from __future__ import annotations

import json
import logging
import mimetypes
import uuid
from decimal import Decimal
from typing import Any, Protocol

from .decorator_tool import Toolset, tool_method
from .file_toolset import StorageClient
from .tool_authz import unrestricted
from .tool_definition import toolset

logger = logging.getLogger(__name__)

MEDIA_TOOLSET = "agentarea/media"

_MEDIA_DIR = "media"


class MediaFile(Protocol):
    content: bytes
    media_type: str


class BilledFile(MediaFile, Protocol):
    cost: Decimal


class SubmittedJob(Protocol):
    job_id: str
    status: str


class VideoJobCheck(Protocol):
    job_id: str
    status: str
    error: str | None
    video: MediaFile | None
    cost_usd: Decimal | None
    cost: Decimal | None
    file_path: str | None


class MediaBackend(Protocol):
    async def generate_image(self, prompt: str, *, size: str | None = None) -> BilledFile: ...

    async def submit_video(
        self,
        prompt: str,
        *,
        duration: int | None = None,
        resolution: str | None = None,
        aspect_ratio: str | None = None,
    ) -> SubmittedJob: ...

    async def check_video(self, job_id: str) -> VideoJobCheck: ...

    async def record_video_saved(
        self, job_id: str, file_path: str, cost_usd: Decimal, cost: Decimal
    ) -> bool: ...


def _extension(media_type: str) -> str:
    return mimetypes.guess_extension(media_type) or ".bin"


@toolset(
    namespace=MEDIA_TOOLSET,
    display_name="Media Generation",
    description=(
        "Generate images and videos with the workspace's image and video models; "
        "the files are saved to the task workspace."
    ),
    category="media",
    plane="runtime",
)
class MediaToolset(Toolset):
    def __init__(
        self,
        *,
        workspace_id: str,
        backend: MediaBackend | None = None,
        storage: StorageClient | None = None,
        generate_image: bool = True,
        generate_video: bool = True,
        get_video: bool = True,
    ) -> None:
        # Built bare to read its schema (tool_builders); only the activity wires
        # a backend and a store, and a call without them fails.
        super().__init__()
        if not workspace_id:
            raise ValueError("workspace_id is required: generated files are scoped by it")
        self._backend = backend
        self._storage = storage
        self.workspace_id = workspace_id
        for name, enabled in (
            ("generate_image", generate_image),
            ("generate_video", generate_video),
            ("get_video", get_video),
        ):
            if not enabled:
                self._tool_methods.pop(name, None)

    @property
    def backend(self) -> MediaBackend:
        if self._backend is None:
            raise RuntimeError("agentarea/media has no model backend in this context")
        return self._backend

    async def _save(self, name: str, media: MediaFile) -> str:
        if self._storage is None:
            raise RuntimeError("agentarea/media has no workspace storage in this context")
        path = f"{_MEDIA_DIR}/{name}{_extension(media.media_type)}"
        await self._storage.put(self.workspace_id, path, media.content, media.media_type)
        return path

    @tool_method(effect="write")
    @unrestricted("generates into the calling task's own workspace")
    async def generate_image(self, prompt: str, size: str | None = None) -> dict[str, Any]:
        """Generate an image from a text prompt and save it to the task workspace.

        ``size`` is an optional ``WIDTHxHEIGHT`` hint such as ``1024x1536``.
        """
        image = await self.backend.generate_image(prompt, size=size)
        try:
            path = await self._save(f"image-{uuid.uuid4().hex[:12]}", image)
        except Exception as error:
            # The provider was paid for the image; the charge stands even though
            # the file could not be kept.
            logger.error("Generated image could not be saved: %s", error, exc_info=True)
            return {
                "success": False,
                "result": f"The image was generated but could not be saved: {error}",
                "error": str(error),
                "model_cost": str(image.cost),
            }
        return {
            "success": True,
            "result": json.dumps(
                {"file_path": path, "media_type": image.media_type, "size": len(image.content)}
            ),
            "artifact_paths": [path],
            "model_cost": str(image.cost),
        }

    @tool_method(effect="write")
    @unrestricted("generates into the calling task's own workspace")
    async def generate_video(
        self,
        prompt: str,
        duration: int | None = None,
        resolution: str | None = None,
        aspect_ratio: str | None = None,
    ) -> str:
        """Start generating a video from a text prompt; returns a job id for get_video.

        ``duration`` is in seconds; ``resolution`` like ``720p``; ``aspect_ratio``
        like ``16:9``. Generation takes minutes: poll ``get_video`` with the job id.
        """
        job = await self.backend.submit_video(
            prompt, duration=duration, resolution=resolution, aspect_ratio=aspect_ratio
        )
        return json.dumps({"job_id": job.job_id, "status": job.status})

    @tool_method(effect="write")
    @unrestricted("reads a job the calling task submitted")
    async def get_video(self, job_id: str) -> dict[str, Any]:
        """Check a video job; once it is done the video is saved to the task workspace."""
        check = await self.backend.check_video(job_id)
        if check.file_path:
            saved: dict[str, Any] = {
                "success": True,
                "result": json.dumps(
                    {"job_id": job_id, "status": check.status, "file_path": check.file_path}
                ),
                "artifact_paths": [check.file_path],
            }
            if check.cost is not None:
                saved["model_cost"] = str(check.cost)
            return saved
        if check.video is None:
            if check.error:
                return {
                    "success": False,
                    "result": json.dumps(
                        {"job_id": job_id, "status": check.status, "error": check.error}
                    ),
                    "error": check.error,
                }
            return {
                "success": True,
                "result": json.dumps({"job_id": job_id, "status": check.status}),
            }

        if check.cost_usd is None or check.cost is None:
            raise RuntimeError("the video model reported no cost")
        path = await self._save(f"video-{job_id}", check.video)
        billed = await self.backend.record_video_saved(job_id, path, check.cost_usd, check.cost)
        return {
            "success": True,
            "result": json.dumps(
                {
                    "job_id": job_id,
                    "status": check.status,
                    "file_path": path,
                    "media_type": check.video.media_type,
                    "size": len(check.video.content),
                }
            ),
            "artifact_paths": [path],
            "model_cost": str(check.cost) if billed else "0",
        }
