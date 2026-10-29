"""Images a tool returned, kept out of the run's history and shown to the model.

The tool activity stores each image with the task's offloaded context and puts
only a reference on the tool message (``attachments``). When the model is
called, the references become image parts of a user message placed right after
the tool results: no provider accepts an image inside a tool message in the
OpenAI chat format, and every vision model accepts one there.
"""

from __future__ import annotations

import base64
import logging
from collections.abc import Awaitable, Callable, Mapping
from typing import Any, Protocol

from agentarea_mcp.tool_result import MAX_TOOL_IMAGES

logger = logging.getLogger(__name__)

# Images re-sent on every turn cost tokens on every turn: only the newest go.
MAX_IMAGES_PER_MODEL_CALL = MAX_TOOL_IMAGES


def stored_image_id(output_id: str, index: int) -> str:
    return f"{output_id}_image_{index}"


class ImageStore(Protocol):
    async def store_image(self, image_id: str, data: bytes, mime_type: str) -> None: ...


async def store_tool_images(
    images: list[dict[str, str]], *, store: ImageStore, output_id: str
) -> tuple[list[dict[str, Any]], list[str]]:
    """Store a tool's base64 images; their references, and a note per image not kept.

    The note numbers the image as the tool result's text does.
    """
    refs: list[dict[str, Any]] = []
    notes: list[str] = []
    for index, image in enumerate(images, start=1):
        image_id = stored_image_id(output_id, index)
        try:
            data = base64.b64decode(image["data"], validate=True)
            await store.store_image(image_id, data, image["mime_type"])
        except Exception:
            logger.warning("Tool image %s could not be stored", image_id, exc_info=True)
            notes.append(f"[image {index} could not be stored]")
            continue
        refs.append({"id": image_id, "mime_type": image["mime_type"], "size": len(data)})
    return refs, notes


def images_to_attach(
    messages: list[dict[str, Any]], limit: int = MAX_IMAGES_PER_MODEL_CALL
) -> list[str]:
    """Ids of the newest ``limit`` images referenced by the conversation."""
    ids = [
        ref["id"]
        for message in messages
        if message.get("role") == "tool"
        for ref in message.get("attachments") or []
    ]
    return ids[-limit:] if limit else []


def attach_tool_images(
    messages: list[dict[str, Any]],
    data_urls: Mapping[str, str | None],
    *,
    vision: bool,
) -> list[dict[str, Any]]:
    """The conversation as the model receives it, with tool images in place.

    ``data_urls`` holds the images to show, by id; ``None`` for one that could
    not be read. An image left out, or one the model cannot see, is named in
    its tool message instead, so the model knows it exists.
    """
    out: list[dict[str, Any]] = []
    shown: list[tuple[dict[str, Any], list[str]]] = []

    def flush() -> None:
        if not shown:
            return
        parts: list[dict[str, Any]] = []
        for message, urls in shown:
            name = message.get("name") or "the tool"
            parts.append(
                {
                    "type": "text",
                    "text": f"Images returned by {name} (call {message.get('tool_call_id')}):",
                }
            )
            parts.extend({"type": "image_url", "image_url": {"url": url}} for url in urls)
        out.append({"role": "user", "content": parts})
        shown.clear()

    for message in messages:
        refs = message.get("attachments") or []
        message = {key: value for key, value in message.items() if key != "attachments"}
        if message.get("role") != "tool":
            flush()
            out.append(message)
            continue
        out.append(message)
        if not refs:
            continue
        urls: list[str] = []
        notes: list[str] = []
        for ref in refs:
            if not vision:
                notes.append(f"[image {ref['id']} not shown: this model does not read images]")
            elif ref["id"] not in data_urls:
                notes.append(f"[image {ref['id']} from an earlier step is no longer attached]")
            elif (url := data_urls[ref["id"]]) is None:
                notes.append(f"[image {ref['id']} could not be loaded]")
            else:
                urls.append(url)
        if notes:
            message["content"] = "\n".join([str(message.get("content") or ""), *notes])
        if urls:
            shown.append((message, urls))
    flush()
    return out


async def resolve_tool_images(
    messages: list[dict[str, Any]],
    *,
    read_image: Callable[[str], Awaitable[bytes]],
    vision: bool,
) -> list[dict[str, Any]]:
    """``attach_tool_images`` with the newest images read from storage."""
    data_urls: dict[str, str | None] = {}
    if vision:
        mime_by_id = {
            ref["id"]: ref["mime_type"]
            for message in messages
            for ref in message.get("attachments") or []
        }
        for image_id in images_to_attach(messages):
            try:
                data = base64.b64encode(await read_image(image_id)).decode("ascii")
                data_urls[image_id] = f"data:{mime_by_id[image_id]};base64,{data}"
            except Exception:
                logger.warning("Tool image %s could not be read", image_id, exc_info=True)
                data_urls[image_id] = None
    return attach_tool_images(messages, data_urls, vision=vision)
