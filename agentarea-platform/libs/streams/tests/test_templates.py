"""Template substitutions: paths, headers, first present key, joins, constants, absence."""

import pytest
from agentarea_streams.domain.templates import (
    TemplateContext,
    TemplateError,
    render,
    render_first,
    render_value,
)

BODY = {
    "update_id": 81234,
    "message": {"chat": {"id": 555, "type": "private"}, "text": "hi", "photo": [{"id": "a"}]},
    "action": None,
    "flag": False,
}
CONTEXT = TemplateContext(body=BODY, headers={"X-GitHub-Event": "push", "Request-Id": "r-1"})


def test_a_body_path_reads_nested_values_and_list_items():
    assert render("{body:message.chat.id}", CONTEXT) == "555"
    assert render("{body:message.photo.0.id}", CONTEXT) == "a"


def test_alternatives_take_the_first_path_present():
    assert render("{body:edited_message.chat.id|message.chat.id}", CONTEXT) == "555"


def test_a_header_is_read_whatever_its_case():
    assert render("{header:x-github-event}", CONTEXT) == "push"
    assert render("{header:REQUEST-ID}", CONTEXT) == "r-1"


def test_first_key_names_the_first_key_the_body_has():
    assert render("{first_key:edited_message|message|callback_query}", CONTEXT) == "message"


def test_literal_text_joins_placeholders():
    assert render("update:{body:update_id}", CONTEXT) == "update:81234"
    assert render("{header:x-github-event}.{body:message.text}", CONTEXT) == "push.hi"


def test_a_template_without_placeholders_is_a_constant():
    assert render("message_received", CONTEXT) == "message_received"


def test_any_missing_placeholder_makes_the_whole_field_absent():
    assert render("{header:x-github-event}.{body:action}", CONTEXT) is None
    assert render("{body:nope}", CONTEXT) is None
    assert render("{header:missing}", CONTEXT) is None
    assert render("{first_key:a|b}", CONTEXT) is None


def test_false_is_a_value_not_an_absence():
    assert render("{body:flag}", CONTEXT) == "false"


def test_the_first_template_that_renders_wins():
    templates = ["{header:x-github-event}.{body:action}", "{header:x-github-event}"]
    assert render_first(templates, CONTEXT) == "push"
    assert render_first(["{body:nope}"], CONTEXT) is None
    assert render_first(None, CONTEXT) is None


def test_an_unknown_placeholder_kind_is_an_error():
    with pytest.raises(TemplateError):
        render("{query:x}", CONTEXT)


def test_a_whole_placeholder_leaf_keeps_its_type_and_missing_leaves_go():
    context = TemplateContext(body=BODY, values={"target": {"chat_id": 555}, "message": "hello"})
    rendered = render_value(
        {"chat_id": "{target:chat_id}", "text": "{message}", "reply": "{target:message_id}"},
        context,
    )
    assert rendered == {"chat_id": 555, "text": "hello"}


def test_an_object_left_with_nothing_is_dropped():
    context = TemplateContext(values={"message": "hi", "target": {}})
    rendered = render_value(
        {"content": "{message}", "message_reference": {"message_id": "{target:message_id}"}},
        context,
    )
    assert rendered == {"content": "hi"}
