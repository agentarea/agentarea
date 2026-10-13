"""The content of an MCP tool result as the model receives it: text, and images."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

# The image types every vision provider behind litellm accepts.
SUPPORTED_IMAGE_TYPES = frozenset({"image/png", "image/jpeg", "image/gif", "image/webp"})
# Anthropic's per-image limit, the strictest of the providers.
MAX_TOOL_IMAGE_BYTES = 5 * 1024 * 1024
MAX_TOOL_IMAGES = 8


def _decoded_size(data: str) -> int:
    return len(data) * 3 // 4


def split_tool_content(blocks: Iterable[Any]) -> tuple[str, list[dict[str, str]]]:
    """The result's text, and its images as ``{"mime_type", "data"}`` (base64).

    Every image is named in the text where it appeared, so a model that cannot
    see images still learns one was returned; one that cannot be carried says why.
    """
    parts: list[str] = []
    images: list[dict[str, str]] = []

    def image(mime_type: str, data: str, uri: str | None = None) -> None:
        if mime_type not in SUPPORTED_IMAGE_TYPES:
            parts.append(f"[image omitted: {mime_type} is not a supported image type]")
        elif _decoded_size(data) > MAX_TOOL_IMAGE_BYTES:
            parts.append(
                f"[image omitted: {mime_type} is larger than {MAX_TOOL_IMAGE_BYTES} bytes]"
            )
        elif len(images) >= MAX_TOOL_IMAGES:
            parts.append(f"[image omitted: more than {MAX_TOOL_IMAGES} images in one result]")
        else:
            images.append({"mime_type": mime_type, "data": data})
            label = f"{mime_type} {uri}" if uri else mime_type
            parts.append(f"[image {len(images)}: {label}]")

    for block in blocks:
        block_type = getattr(block, "type", None)
        if block_type == "text":
            parts.append(getattr(block, "text", "") or "")
        elif block_type == "image":
            image(block.mime_type, block.data)
        elif block_type == "resource":
            resource = block.resource
            mime_type = resource.mime_type or ""
            blob = getattr(resource, "blob", None)
            if blob is not None and mime_type.startswith("image/"):
                image(mime_type, blob, resource.uri)
            elif blob is not None:
                parts.append(f"[resource {resource.uri}: {mime_type or 'binary'}, not shown]")
            else:
                parts.append(f"[resource {resource.uri}]\n{resource.text}")
        elif block_type == "resource_link":
            parts.append(f"[resource link {block.uri}]")
        else:
            parts.append(str(block))
    return "\n".join(parts), images
