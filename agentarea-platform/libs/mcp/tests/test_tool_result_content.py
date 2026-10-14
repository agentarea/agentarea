"""An MCP tool result's content blocks: text for every model, images kept as images."""

import base64

from agentarea_mcp.tool_result import MAX_TOOL_IMAGE_BYTES, MAX_TOOL_IMAGES, split_tool_content
from mcp_types import (
    BlobResourceContents,
    EmbeddedResource,
    ImageContent,
    ResourceLink,
    TextContent,
    TextResourceContents,
)

PNG = base64.b64encode(b"\x89PNG fake sheet").decode()


def test_text_blocks_join_and_no_images():
    text, images = split_tool_content([TextContent(text="a"), TextContent(text="b")])
    assert text == "a\nb"
    assert images == []


def test_an_image_block_is_kept_as_an_image_and_named_in_the_text():
    text, images = split_tool_content(
        [TextContent(text="sheet A-101"), ImageContent(data=PNG, mime_type="image/png")]
    )
    assert images == [{"mime_type": "image/png", "data": PNG}]
    assert text == "sheet A-101\n[image 1: image/png]"


def test_an_embedded_image_resource_is_an_image_and_a_text_resource_is_its_text():
    text, images = split_tool_content(
        [
            EmbeddedResource(
                resource=BlobResourceContents(
                    uri="file:///sheets/a101.jpg", mime_type="image/jpeg", blob=PNG
                )
            ),
            EmbeddedResource(
                resource=TextResourceContents(
                    uri="file:///notes.md", mime_type="text/markdown", text="# notes"
                )
            ),
            EmbeddedResource(
                resource=BlobResourceContents(
                    uri="file:///plan.pdf", mime_type="application/pdf", blob=PNG
                )
            ),
        ]
    )
    assert images == [{"mime_type": "image/jpeg", "data": PNG}]
    assert text.splitlines() == [
        "[image 1: image/jpeg file:///sheets/a101.jpg]",
        "[resource file:///notes.md]",
        "# notes",
        "[resource file:///plan.pdf: application/pdf, not shown]",
    ]


def test_a_resource_link_names_its_uri():
    text, _ = split_tool_content([ResourceLink(uri="https://x/y.dwg", name="y.dwg")])
    assert text == "[resource link https://x/y.dwg]"


def test_images_a_model_cannot_take_are_named_not_carried():
    too_big = base64.b64encode(b"x" * (MAX_TOOL_IMAGE_BYTES + 1)).decode()
    blocks = [
        ImageContent(data=PNG, mime_type="image/svg+xml"),
        ImageContent(data=too_big, mime_type="image/png"),
        *[ImageContent(data=PNG, mime_type="image/png") for _ in range(MAX_TOOL_IMAGES + 1)],
    ]
    text, images = split_tool_content(blocks)
    lines = text.splitlines()
    assert len(images) == MAX_TOOL_IMAGES
    assert lines[0] == "[image omitted: image/svg+xml is not a supported image type]"
    assert lines[1].startswith("[image omitted: image/png is larger than")
    assert lines[-1] == f"[image omitted: more than {MAX_TOOL_IMAGES} images in one result]"
