"""Discovery decides each model's kind from what the provider says it outputs."""

import httpx
from agentarea_llm.application.model_discovery_service import ModelDiscoveryService
from agentarea_llm.domain.models import ModelKind


def _openrouter_model(model_id: str, output_modalities: list[str]) -> dict:
    return {
        "id": model_id,
        "name": model_id,
        "context_length": 32_000,
        "architecture": {
            "modality": "text->text",
            "input_modalities": ["text"],
            "output_modalities": output_modalities,
        },
        "pricing": {"prompt": "0.000001", "completion": "0.000002"},
    }


def _kinds(payload: dict) -> dict[str, ModelKind | None]:
    models = ModelDiscoveryService()._parse_response("openrouter", payload)
    return {m.model_name: m.kind for m in models}


def test_output_modalities_decide_the_kind():
    kinds = _kinds(
        {
            "data": [
                _openrouter_model("text-model", ["text"]),
                _openrouter_model("image-model", ["image", "text"]),
                _openrouter_model("embedder", ["embeddings"]),
                _openrouter_model("jev", ["decisions"]),
                _openrouter_model("video-model", ["video"]),
            ]
        }
    )

    assert kinds == {
        "text-model": ModelKind.CHAT,
        "image-model": ModelKind.IMAGE,
        "embedder": ModelKind.EMBEDDING,
        "jev": ModelKind.DECISION,
        "video-model": ModelKind.VIDEO,
    }


def test_a_listing_without_architecture_is_chat():
    assert _kinds({"data": [{"id": "gpt-4o"}]}) == {"gpt-4o": ModelKind.CHAT}


def test_an_output_no_surface_takes_has_no_kind():
    assert _kinds({"data": [_openrouter_model("tts", ["speech"])]}) == {"tts": None}


# Recorded from GET https://openrouter.ai/api/v1/models?output_modalities=all
# (2026-10-01): a decision model, which the plain listing leaves out.
_TEV1 = {
    "id": "togethercomputer/tev1-4b-experimental",
    "canonical_slug": "togethercomputer/tev1-4b-experimental-20260923",
    "name": "Together: Tev1 4B Experimental",
    "created": 1790795429,
    "description": "Tev1 4B Experimental is an experimental decision model from Together AI.",
    "context_length": 32768,
    "architecture": {
        "modality": "text->decisions",
        "input_modalities": ["text"],
        "output_modalities": ["decisions"],
        "tokenizer": "Qwen3",
        "instruct_type": None,
    },
    "pricing": {"prompt": "0.000000042", "completion": "0"},
    "top_provider": {"context_length": 32768, "max_completion_tokens": 8, "is_moderated": False},
}


async def test_openrouter_discovery_lists_every_output_modality():
    seen: list[httpx.URL] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url)
        return httpx.Response(
            200,
            json={
                "data": [
                    _openrouter_model("chat-model", ["text"]),
                    _openrouter_model("flux", ["image"]),
                    _openrouter_model("veo", ["video"]),
                    _openrouter_model("tts", ["speech"]),
                    _TEV1,
                ]
            },
        )

    service = ModelDiscoveryService(transport=httpx.MockTransport(handler))
    models = await service.discover("openrouter", "sk-test")

    assert [(url.path, url.params.get("output_modalities")) for url in seen] == [
        ("/api/v1/models", "all")
    ]
    assert {m.model_name: m.kind for m in models} == {
        "chat-model": ModelKind.CHAT,
        "flux": ModelKind.IMAGE,
        "veo": ModelKind.VIDEO,
        "tts": None,
        "togethercomputer/tev1-4b-experimental": ModelKind.DECISION,
    }
    tev1 = next(m for m in models if m.kind is ModelKind.DECISION)
    assert tev1.context_window == 32768


async def test_other_providers_keep_their_plain_listing():
    seen: list[httpx.URL] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url)
        return httpx.Response(200, json={"data": [{"id": "gpt-4o"}]})

    await ModelDiscoveryService(transport=httpx.MockTransport(handler)).discover("openai", "sk")

    assert [str(url) for url in seen] == ["https://api.openai.com/v1/models"]
