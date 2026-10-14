"""A tool's images reach a vision model as image parts; other models get text."""

import pytest
from agentarea_execution.tool_images import (
    attach_tool_images,
    images_to_attach,
    resolve_tool_images,
    store_tool_images,
)

SHEET = {"id": "mcp_tool_1_image_1", "mime_type": "image/png", "size": 10}
PLAN = {"id": "mcp_tool_1_image_2", "mime_type": "image/jpeg", "size": 10}


def _conversation(*refs_per_call):
    calls = [
        {"id": f"c{i}", "type": "function", "function": {"name": "sheets", "arguments": "{}"}}
        for i in range(len(refs_per_call))
    ]
    messages = [
        {"role": "user", "content": "read the drawing"},
        {"role": "assistant", "content": "", "tool_calls": calls},
    ]
    for i, refs in enumerate(refs_per_call):
        tool = {"role": "tool", "content": f"result {i}", "tool_call_id": f"c{i}", "name": "sheets"}
        if refs:
            tool["attachments"] = refs
        messages.append(tool)
    messages.append({"role": "assistant", "content": "done"})
    return messages


def test_images_follow_the_tool_results_as_one_user_message():
    messages = _conversation([SHEET, PLAN], [])
    out = attach_tool_images(
        messages,
        {SHEET["id"]: "data:image/png;base64,AAA", PLAN["id"]: "data:image/jpeg;base64,BBB"},
        vision=True,
    )

    assert [m["role"] for m in out] == ["user", "assistant", "tool", "tool", "user", "assistant"]
    assert all("attachments" not in m for m in out)
    assert out[2]["content"] == "result 0"
    assert out[4]["content"] == [
        {"type": "text", "text": "Images returned by sheets (call c0):"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAA"}},
        {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,BBB"}},
    ]


def test_a_model_without_vision_is_told_in_text_and_sent_no_image():
    out = attach_tool_images(_conversation([SHEET]), {}, vision=False)

    assert [m["role"] for m in out] == ["user", "assistant", "tool", "assistant"]
    assert out[2]["content"] == (
        f"result 0\n[image {SHEET['id']} not shown: this model does not read images]"
    )


def test_unread_and_older_images_are_named_not_dropped():
    out = attach_tool_images(_conversation([SHEET, PLAN]), {PLAN["id"]: None}, vision=True)

    assert out[2]["content"].splitlines() == [
        "result 0",
        f"[image {SHEET['id']} from an earlier step is no longer attached]",
        f"[image {PLAN['id']} could not be loaded]",
    ]
    assert [m["role"] for m in out] == ["user", "assistant", "tool", "assistant"]


def test_only_the_newest_images_are_attached():
    refs = [{"id": f"i{n}", "mime_type": "image/png", "size": 1} for n in range(5)]
    assert images_to_attach(_conversation(refs[:3], refs[3:]), limit=2) == ["i3", "i4"]


def test_a_conversation_without_images_is_unchanged():
    messages = _conversation([], [])
    assert attach_tool_images(messages, {}, vision=True) == messages


@pytest.mark.asyncio
async def test_resolve_reads_only_what_it_attaches_and_builds_data_urls():
    reads: list[str] = []

    async def read_image(image_id):
        reads.append(image_id)
        if image_id == PLAN["id"]:
            raise OSError("gone")
        return b"\x89PNG"

    out = await resolve_tool_images(
        _conversation([SHEET, PLAN]), read_image=read_image, vision=True
    )

    assert reads == [SHEET["id"], PLAN["id"]]
    assert out[3]["content"][1] == {
        "type": "image_url",
        "image_url": {"url": "data:image/png;base64,iVBORw=="},
    }
    assert out[2]["content"].endswith(f"[image {PLAN['id']} could not be loaded]")

    reads.clear()
    await resolve_tool_images(_conversation([SHEET]), read_image=read_image, vision=False)
    assert reads == []


@pytest.mark.asyncio
async def test_stored_images_become_references_and_a_failed_one_a_note():
    stored: dict[str, tuple[bytes, str]] = {}

    class Store:
        async def store_image(self, image_id, data, mime_type):
            stored[image_id] = (data, mime_type)

    images = [
        {"mime_type": "image/png", "data": "iVBORw=="},
        {"mime_type": "image/png", "data": "not base64!"},
    ]
    refs, notes = await store_tool_images(images, store=Store(), output_id="mcp_tool_7")

    assert refs == [{"id": "mcp_tool_7_image_1", "mime_type": "image/png", "size": 4}]
    assert stored == {"mcp_tool_7_image_1": (b"\x89PNG", "image/png")}
    assert notes == ["[image 2 could not be stored]"]


def test_a_logged_tool_entry_comes_back_with_its_images():
    from agentarea_tasks.domain.models import ConversationEntry

    entry = ConversationEntry(
        seq=3, role="tool", content="x", tool_call_id="c0", attachments=[SHEET]
    )
    plain = ConversationEntry(seq=4, role="assistant", content="y")

    assert entry.as_message()["attachments"] == [SHEET]
    assert "attachments" not in plain.as_message()
