"""A provider's chat and model-list URLs come from the values its spec carries."""

import pytest

from agentarea_agents_sdk.models.provider_profiles import (
    DEFAULT_PROFILE,
    AuthStyle,
    ModelListShape,
    ProviderProfile,
    Transport,
)

GEMINI = ProviderProfile(base_url="https://generativelanguage.googleapis.com/v1beta/openai")
OLLAMA = ProviderProfile(
    auth=AuthStyle.NONE, models_path="/api/tags", list_shape=ModelListShape.MODELS_NAME
)


@pytest.mark.parametrize(
    "profile, chat_url",
    [
        (ProviderProfile(base_url="https://api.openai.com/v1"), "https://api.openai.com/v1/chat/completions"),
        (ProviderProfile(base_url="https://api.perplexity.ai"), "https://api.perplexity.ai/chat/completions"),
        (GEMINI, "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"),
        (ProviderProfile(base_url="https://api.z.ai/api/paas/v4/"), "https://api.z.ai/api/paas/v4/chat/completions"),
    ],
)
def test_the_catalog_base_url_is_the_api_root_as_given(profile, chat_url):
    assert profile.resolve_api_url(None, "/chat/completions") == chat_url


@pytest.mark.parametrize(
    "endpoint_url, chat_url",
    [
        ("https://gateway.example/v1", "https://gateway.example/v1/chat/completions"),
        ("https://gateway.example", "https://gateway.example/v1/chat/completions"),
        ("localhost:11434", "http://localhost:11434/v1/chat/completions"),
    ],
)
def test_a_typed_endpoint_may_be_the_server_root_or_its_v1_base(endpoint_url, chat_url):
    assert GEMINI.resolve_api_url(endpoint_url, "/chat/completions") == chat_url


def test_the_model_list_sits_under_the_same_root_as_chat():
    assert (
        GEMINI.resolve_models_url(None)
        == "https://generativelanguage.googleapis.com/v1beta/openai/models"
    )


def test_a_listing_outside_the_api_root_hangs_off_the_address_itself():
    assert OLLAMA.resolve_models_url("http://localhost:11434") == "http://localhost:11434/api/tags"
    assert OLLAMA.resolve_models_url(None) is None


def test_a_model_list_query_is_kept():
    profile = ProviderProfile(
        base_url="https://openrouter.ai/api/v1", models_query="output_modalities=all"
    )
    assert (
        profile.resolve_models_url(None)
        == "https://openrouter.ai/api/v1/models?output_modalities=all"
    )


def test_a_spec_without_values_is_openai_compatible_and_needs_an_endpoint():
    assert DEFAULT_PROFILE.requires_endpoint_url
    assert DEFAULT_PROFILE.transport is Transport.OPENAI
    assert DEFAULT_PROFILE.resolve_api_url(None, "/chat/completions") is None


def test_stored_values_round_trip():
    profile = ProviderProfile(
        base_url="https://api.anthropic.com/v1",
        transport=Transport.ANTHROPIC,
        auth=AuthStyle.API_KEY_HEADER,
    )
    assert ProviderProfile.from_mapping(profile.as_mapping()) == profile
    assert ProviderProfile.from_mapping(None) == DEFAULT_PROFILE


def test_an_unknown_transport_is_refused():
    with pytest.raises(ValueError, match="bedrock"):
        ProviderProfile.from_mapping({"transport": "bedrock"})


@pytest.mark.parametrize(
    "auth, headers",
    [
        (AuthStyle.BEARER, {"Authorization": "Bearer k"}),
        (AuthStyle.API_KEY_HEADER, {"x-api-key": "k", "anthropic-version": "2023-06-01"}),
        (AuthStyle.NONE, {}),
    ],
)
def test_the_key_is_presented_as_the_spec_says(auth, headers):
    assert ProviderProfile(auth=auth).build_headers("k") == headers
