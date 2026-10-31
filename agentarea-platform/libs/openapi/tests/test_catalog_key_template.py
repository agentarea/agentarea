"""A catalog API connection's key form, and where the values a person types go."""

import pytest
from agentarea_openapi.application.catalog_key_template import (
    CatalogKeyField,
    CatalogKeyTemplateError,
    catalog_key_credentials,
    catalog_key_template,
)


def _spec(*fields: dict) -> dict:
    return {"connection_type": "openapi", "api_key": {"fields": list(fields)}}


TOKEN = {"name": "Authorization", "location": "header", "scheme": "Token", "label": "API key"}
SECRET = {"name": "X-Secret", "location": "header", "label": "Secret key", "description": "From the profile"}
QUERY_KEY = {"name": "key", "location": "query", "label": "API key"}


def test_an_item_without_an_api_key_block_has_no_key_form():
    assert catalog_key_template({"connection_type": "openapi", "oauth": {}}) is None


def test_fields_keep_their_order_location_label_and_scheme():
    template = catalog_key_template(_spec(TOKEN, SECRET, QUERY_KEY))

    assert template is not None
    assert template.fields == (
        CatalogKeyField(name="Authorization", location="header", label="API key", scheme="Token"),
        CatalogKeyField(
            name="X-Secret", location="header", label="Secret key", description="From the profile"
        ),
        CatalogKeyField(name="key", location="query", label="API key"),
    )


@pytest.mark.parametrize(
    "api_key",
    [
        "Authorization",
        {"fields": []},
        {"fields": "Authorization"},
        {"fields": [{"name": "Authorization", "location": "cookie", "label": "Key"}]},
        {"fields": [{"name": "Bad Header", "location": "header", "label": "Key"}]},
        {"fields": [{"name": "key", "location": "query", "label": ""}]},
        {"fields": [{"name": "Authorization", "location": "header", "label": "Key", "scheme": "Two words"}]},
        {"fields": [TOKEN, {**TOKEN, "label": "Again"}]},
    ],
    ids=[
        "not-an-object",
        "no-fields",
        "fields-not-a-list",
        "unknown-location",
        "bad-header-name",
        "blank-label",
        "scheme-with-space",
        "duplicate-field",
    ],
)
def test_a_malformed_template_is_refused(api_key):
    with pytest.raises(CatalogKeyTemplateError):
        catalog_key_template({"api_key": api_key})


def test_a_header_value_carries_its_scheme_and_a_query_value_is_secret():
    template = catalog_key_template(_spec(TOKEN, SECRET, QUERY_KEY))
    assert template is not None

    headers, params = catalog_key_credentials(
        template, {"Authorization": "abc", "X-Secret": "s3cr3t", "key": "k"}  # pragma: allowlist secret
    )

    assert [(h.name, h.value) for h in headers] == [
        ("Authorization", "Token abc"),
        ("X-Secret", "s3cr3t"),
    ]
    assert [(p.name, p.value, p.secret) for p in params] == [("key", "k", True)]


def test_surrounding_whitespace_in_a_pasted_key_is_dropped():
    template = catalog_key_template(_spec(QUERY_KEY))
    assert template is not None

    _, params = catalog_key_credentials(template, {"key": "  k \n"})

    assert params[0].value == "k"


@pytest.mark.parametrize(
    ("values", "message"),
    [
        ({"Authorization": "abc"}, "Secret key"),
        ({"Authorization": "abc", "X-Secret": "   "}, "Secret key"),
        ({"Authorization": "abc", "X-Secret": "s", "X-Other": "x"}, "X-Other"),
    ],
    ids=["missing", "blank", "unknown"],
)
def test_every_field_needs_a_value_and_nothing_else_is_taken(values, message):
    template = catalog_key_template(_spec(TOKEN, SECRET))
    assert template is not None

    with pytest.raises(ValueError, match=message):
        catalog_key_credentials(template, values)
