"""Each provider's chat and model-list URLs come from its profile, not from a branch per vendor."""

import pytest

from agentarea_agents_sdk.models.provider_profiles import (
    PROVIDER_PROFILES,
    Transport,
    profile_for,
)


@pytest.mark.parametrize(
    "provider, chat_url",
    [
        ("openai", "https://api.openai.com/v1/chat/completions"),
        ("groq", "https://api.groq.com/openai/v1/chat/completions"),
        ("perplexity", "https://api.perplexity.ai/chat/completions"),
        ("zai", "https://api.z.ai/api/paas/v4/chat/completions"),
        ("gemini", "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"),
        ("deepinfra", "https://api.deepinfra.com/v1/openai/chat/completions"),
        ("novita", "https://api.novita.ai/v3/openai/chat/completions"),
        ("volcengine", "https://ark.cn-beijing.volces.com/api/v3/chat/completions"),
        ("cohere_chat", "https://api.cohere.ai/compatibility/v1/chat/completions"),
        ("together_ai", "https://api.together.xyz/v1/chat/completions"),
        ("anthropic", "https://api.anthropic.com/v1/chat/completions"),
    ],
)
def test_a_public_provider_is_called_at_its_own_address(provider, chat_url):
    assert profile_for(provider).resolve_api_url(None, "/chat/completions") == chat_url


def test_the_model_list_follows_the_same_prefix_as_chat():
    assert (
        profile_for("gemini").resolve_models_url(None)
        == "https://generativelanguage.googleapis.com/v1beta/openai/models"
    )


def test_an_endpoint_url_wins_over_the_public_address():
    assert (
        profile_for("openai").resolve_api_url("https://gateway.example/v1", "/chat/completions")
        == "https://gateway.example/v1/chat/completions"
    )


def test_an_unknown_provider_needs_its_own_endpoint():
    profile = profile_for("bedrock")

    assert profile.requires_endpoint_url
    assert profile.transport is Transport.OPENAI
    assert profile.resolve_api_url(None, "/chat/completions") is None


@pytest.mark.parametrize("key", sorted(PROVIDER_PROFILES))
def test_every_public_address_is_https(key):
    base = PROVIDER_PROFILES[key].base_url
    assert base is None or base.startswith("https://")


def test_only_anthropic_speaks_the_messages_api():
    assert [k for k, p in PROVIDER_PROFILES.items() if p.transport is Transport.ANTHROPIC] == [
        "anthropic"
    ]
