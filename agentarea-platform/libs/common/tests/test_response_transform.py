"""A connector can declare how a vendor's response is reshaped before the agent sees it."""

import base64

import pytest
from agentarea_common.response_transform import ResponseTransformError, apply_response_transform

XML = (
    '<?xml version="1.0" encoding="utf-8"?><yandexsearch version="1.0"><response>'
    '<results><grouping><group><doc id="a"><url>https://a.example</url><title>A</title></doc>'
    '</group><group><doc id="b"><url>https://b.example</url><title>B <hlword>b</hlword></title>'
    "</doc></group></grouping></results></response></yandexsearch>"
)

STEPS = [{"decode": "base64", "at": "$.rawData"}, {"parse": "xml", "at": "$.rawData"}]


def _body(xml: str) -> dict:
    return {"rawData": base64.b64encode(xml.encode()).decode()}


def test_base64_xml_becomes_json():
    body = apply_response_transform(STEPS, _body(XML))

    groups = body["rawData"]["yandexsearch"]["response"]["results"]["grouping"]["group"]
    assert [g["doc"]["@id"] for g in groups] == ["a", "b"]
    assert groups[0]["doc"]["url"] == "https://a.example"
    assert groups[1]["doc"]["title"] == {"#text": "B", "hlword": "b"}
    assert body["rawData"]["yandexsearch"]["@version"] == "1.0"


def test_no_steps_leave_the_body_alone():
    body = {"a": 1}
    assert apply_response_transform([], body) is body


def test_a_document_with_a_doctype_is_refused():
    evil = '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><x>&a;</x>'

    with pytest.raises(ResponseTransformError, match="DOCTYPE"):
        apply_response_transform(STEPS, _body(evil))


def test_a_missing_field_is_an_error():
    with pytest.raises(ResponseTransformError, match=r"\$\.rawData"):
        apply_response_transform(STEPS, {"other": 1})


@pytest.mark.parametrize(
    "steps",
    [[{"decode": "rot13", "at": "$.x"}], [{"parse": "yaml", "at": "$.x"}], [{"at": "$.x"}]],
)
def test_an_unknown_step_is_refused(steps):
    with pytest.raises(ResponseTransformError):
        apply_response_transform(steps, {"x": "eA=="})
