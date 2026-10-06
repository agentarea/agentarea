"""Typed clients for image, video and decision models, against recorded wire shapes.

The request and response shapes are OpenRouter's published API
(https://openrouter.ai/openapi.json): ``/videos``, ``/videos/{id}``,
``/videos/{id}/content`` and ``/systemone``. Image generation goes through
LiteLLM, which reaches OpenRouter over chat completions.
"""

import base64
import json
from decimal import Decimal

import httpx
import pytest
from agentarea_llm.infrastructure.model_clients import (
    DecisionModel,
    ImageModel,
    ModelCallError,
    ModelCostUnavailableError,
    ModelEndpoint,
    ModelProviderUnavailableError,
    VideoModel,
)
from litellm.llms.custom_httpx.http_handler import HTTPHandler

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16


def _endpoint(**overrides) -> ModelEndpoint:
    base = {
        "instance_id": "11111111-1111-1111-1111-111111111111",
        "provider_type": "openrouter",
        "model_name": "vendor/model",
        "api_key": "sk-or-test",  # pragma: allowlist secret
        "endpoint_url": None,
        "managed_by": None,
        "input_cost_per_token": None,
        "output_cost_per_token": None,
    }
    return ModelEndpoint(**{**base, **overrides})


def _client_factory(handler):
    return lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler))


# -- image ------------------------------------------------------------------


def _image_handler(seen: dict, *, usage: dict | None, images: list[dict] | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = json.loads(request.content)
        message = {
            "role": "assistant",
            "content": "",
            "images": images
            if images is not None
            else [
                {
                    "type": "image_url",
                    "image_url": {
                        "url": "data:image/png;base64," + base64.b64encode(PNG).decode()
                    },
                }
            ],
        }
        body: dict = {"model": "vendor/model", "choices": [{"message": message}]}
        if usage is not None:
            body["usage"] = usage
        return httpx.Response(200, json=body)

    return handler


def _http_handler(handler) -> HTTPHandler:
    return HTTPHandler(client=httpx.Client(transport=httpx.MockTransport(handler)))


async def test_image_generation_returns_bytes_type_and_provider_cost():
    seen: dict = {}
    usage = {"prompt_tokens": 6, "completion_tokens": 1290, "total_tokens": 1296, "cost": 0.0387}
    model = ImageModel(
        _endpoint(), litellm_client=_http_handler(_image_handler(seen, usage=usage))
    )

    image = await model.generate("a lighthouse at dusk", size="1024x1536")

    assert image.content == PNG
    assert image.media_type == "image/png"
    assert image.cost_usd == Decimal("0.0387")
    assert seen["url"] == "https://openrouter.ai/api/v1/chat/completions"
    assert seen["auth"] == "Bearer sk-or-test"
    assert seen["body"]["model"] == "vendor/model"
    assert seen["body"]["messages"] == [{"role": "user", "content": "a lighthouse at dusk"}]


async def test_image_generation_without_a_provider_cost_is_refused():
    usage = {"prompt_tokens": 6, "completion_tokens": 1290, "total_tokens": 1296}
    model = ImageModel(_endpoint(), litellm_client=_http_handler(_image_handler({}, usage=usage)))

    with pytest.raises(ModelCostUnavailableError):
        await model.generate("a lighthouse")


async def test_image_generation_that_returns_no_image_is_an_error():
    usage = {"prompt_tokens": 6, "completion_tokens": 1, "total_tokens": 7, "cost": 0.001}
    model = ImageModel(
        _endpoint(), litellm_client=_http_handler(_image_handler({}, usage=usage, images=[]))
    )

    with pytest.raises(ModelCallError, match="no image"):
        await model.generate("a lighthouse")


# -- video ------------------------------------------------------------------


async def test_video_submit_posts_the_prompt_and_returns_the_provider_job():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            202,
            json={
                "id": "gen-vid-1-abcdefghijklmnopqrst",
                "polling_url": "https://openrouter.ai/api/v1/videos/gen-vid-1-abcdefghijklmnopqrst",
                "status": "pending",
            },
        )

    model = VideoModel(_endpoint(), http_client_factory=_client_factory(handler))
    job = await model.submit("waves", duration=5, resolution="720p", aspect_ratio="16:9")

    assert job.provider_job_id == "gen-vid-1-abcdefghijklmnopqrst"
    assert job.status == "pending"
    assert seen["url"] == "https://openrouter.ai/api/v1/videos"
    assert seen["auth"] == "Bearer sk-or-test"
    assert seen["body"] == {
        "model": "vendor/model",
        "prompt": "waves",
        "duration": 5,
        "resolution": "720p",
        "aspect_ratio": "16:9",
    }


async def test_video_status_reports_completion_with_cost():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/videos/job-1"
        return httpx.Response(
            200,
            json={
                "id": "job-1",
                "polling_url": "https://openrouter.ai/api/v1/videos/job-1",
                "status": "completed",
                "unsigned_urls": ["https://cdn.example/v.mp4"],
                "usage": {"cost": 1.25, "is_byok": False},
            },
        )

    model = VideoModel(_endpoint(), http_client_factory=_client_factory(handler))
    status = await model.status("job-1")

    assert status.status == "completed"
    assert status.cost_usd == Decimal("1.25")
    assert status.error is None


async def test_video_status_carries_the_provider_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"id": "job-1", "polling_url": "x", "status": "failed", "error": "moderated"},
        )

    model = VideoModel(_endpoint(), http_client_factory=_client_factory(handler))
    status = await model.status("job-1")

    assert status.status == "failed"
    assert status.error == "moderated"


async def test_a_structured_provider_error_is_kept_as_its_message():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "job-1",
                "polling_url": "x",
                "status": "failed",
                "error": {"code": 400, "message": "prompt rejected", "metadata": {}},
            },
        )

    model = VideoModel(_endpoint(), http_client_factory=_client_factory(handler))
    status = await model.status("job-1")

    assert status.error == "prompt rejected"


async def test_video_content_downloads_with_the_credential():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(200, content=b"mp4-bytes", headers={"content-type": "video/mp4"})

    model = VideoModel(_endpoint(), http_client_factory=_client_factory(handler))
    video = await model.content("job-1")

    assert video.content == b"mp4-bytes"
    assert video.media_type == "video/mp4"
    assert seen["url"] == "https://openrouter.ai/api/v1/videos/job-1/content?index=0"
    assert seen["auth"] == "Bearer sk-or-test"


async def test_a_provider_error_status_is_raised_not_swallowed():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(402, json={"error": {"message": "Insufficient credits"}})

    model = VideoModel(_endpoint(), http_client_factory=_client_factory(handler))

    with pytest.raises(ModelCallError, match="402"):
        await model.submit("waves")


async def test_an_operator_endpoint_is_used_as_the_api_root():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        return httpx.Response(202, json={"id": "j", "polling_url": "p", "status": "pending"})

    model = VideoModel(
        _endpoint(endpoint_url="https://proxy.example/api/v1"),
        http_client_factory=_client_factory(handler),
    )
    await model.submit("waves")

    assert seen["url"] == "https://proxy.example/api/v1/videos"


# -- decision ---------------------------------------------------------------

_QUESTIONS = {
    "route": {
        "type": "choice",
        "instructions": "Which team should handle this ticket?",
        "criteria": {"billing": "Payments and invoices", "support": "Everything else"},
    },
    "urgent": {"type": "noul", "instructions": "Is the customer blocked right now?"},
}


def _decision_handler(seen: dict, *, usage: dict, answers: dict | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "id": "d-1",
                "model": "typesafe/jev",
                "answers": answers
                if answers is not None
                else {
                    "route": {
                        "type": "choice",
                        "choice": "billing",
                        "probabilities": {"billing": 0.9, "support": 0.1},
                        "confidence": 0.9,
                    },
                    "urgent": {"type": "noul", "noul": 0.2},
                },
                "usage": usage,
            },
        )

    return handler


async def test_decision_posts_state_and_questions_and_returns_answers_with_cost():
    seen: dict = {}
    model = DecisionModel(
        _endpoint(model_name="typesafe/jev"),
        http_client_factory=_client_factory(
            _decision_handler(seen, usage={"input_tokens": 100, "output_tokens": 2, "cost": 0.0004})
        ),
    )

    result = await model.evaluate("Customer: my card was charged twice", _QUESTIONS)

    assert seen["url"] == "https://openrouter.ai/api/v1/systemone"
    assert seen["body"] == {
        "model": "typesafe/jev",
        "state": "Customer: my card was charged twice",
        "questions": _QUESTIONS,
    }
    assert result.answers["route"]["choice"] == "billing"
    assert result.answers["urgent"]["noul"] == 0.2
    assert result.cost_usd == Decimal("0.0004")


async def test_decision_cost_falls_to_the_spec_token_prices_when_the_provider_omits_it():
    model = DecisionModel(
        _endpoint(
            input_cost_per_token=Decimal("0.000001"), output_cost_per_token=Decimal("0.00001")
        ),
        http_client_factory=_client_factory(
            _decision_handler({}, usage={"input_tokens": 100, "output_tokens": 2})
        ),
    )

    result = await model.evaluate("state", _QUESTIONS)

    assert result.cost_usd == Decimal("0.000120")


async def test_decision_without_any_price_is_refused():
    model = DecisionModel(
        _endpoint(),
        http_client_factory=_client_factory(
            _decision_handler({}, usage={"input_tokens": 100, "output_tokens": 2})
        ),
    )

    with pytest.raises(ModelCostUnavailableError):
        await model.evaluate("state", _QUESTIONS)


async def test_a_missing_answer_is_an_error():
    model = DecisionModel(
        _endpoint(),
        http_client_factory=_client_factory(
            _decision_handler(
                {},
                usage={"input_tokens": 1, "output_tokens": 1, "cost": 0.1},
                answers={"route": {"type": "choice", "choice": "billing"}},
            )
        ),
    )

    with pytest.raises(ModelCallError, match="urgent"):
        await model.evaluate("state", _QUESTIONS)


@pytest.mark.parametrize(
    "questions, message",
    [
        ({}, "at least one question"),
        ({"q": {"type": "maybe", "instructions": "?"}}, "type"),
        ({"q": {"type": "choice", "instructions": "?"}}, "criteria"),
        ({"q": {"type": "noul"}}, "instructions"),
        ({"q": {"type": "score", "instructions": "?", "criteria": []}}, "criteria"),
    ],
)
async def test_malformed_questions_never_reach_the_provider(questions, message):
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("the provider must not be called")

    model = DecisionModel(_endpoint(), http_client_factory=_client_factory(handler))

    with pytest.raises(ValueError, match=message):
        await model.evaluate("state", questions)


async def test_a_video_larger_than_the_cap_is_refused(monkeypatch):
    from agentarea_llm.infrastructure import model_clients

    monkeypatch.setattr(model_clients, "MAX_VIDEO_BYTES", 8)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"x" * 9, headers={"content-type": "video/mp4"})

    model = VideoModel(_endpoint(), http_client_factory=_client_factory(handler))

    with pytest.raises(ModelCallError, match="8-byte"):
        await model.content("job-1")


async def test_a_video_at_the_cap_is_kept(monkeypatch):
    from agentarea_llm.infrastructure import model_clients

    monkeypatch.setattr(model_clients, "MAX_VIDEO_BYTES", 8)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"x" * 8, headers={"content-type": "video/mp4"})

    model = VideoModel(_endpoint(), http_client_factory=_client_factory(handler))

    assert (await model.content("job-1")).content == b"x" * 8


async def test_an_image_endpoint_at_a_private_address_is_never_called():
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("the private endpoint must not be called")

    model = ImageModel(
        _endpoint(endpoint_url="http://169.254.169.254/v1"),
        litellm_client=_http_handler(handler),
    )

    with pytest.raises(ModelCallError, match="non-public address"):
        await model.generate("a lighthouse")


async def test_an_unknown_provider_video_status_fails_loud():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"id": "job-1", "polling_url": "x", "status": "paused"})

    model = VideoModel(_endpoint(), http_client_factory=_client_factory(handler))

    with pytest.raises(ModelCallError, match="unknown status 'paused'"):
        await model.status("job-1")


async def test_a_video_download_without_a_content_type_fails_loud():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=httpx.ByteStream(b"mp4"))

    model = VideoModel(_endpoint(), http_client_factory=_client_factory(handler))

    with pytest.raises(ModelCallError, match="no content type"):
        await model.content("job-1")


async def test_a_decision_without_token_usage_fails_loud():
    model = DecisionModel(
        _endpoint(),
        http_client_factory=_client_factory(_decision_handler({}, usage={"cost": 0.1})),
    )

    with pytest.raises(ModelCallError, match="input_tokens"):
        await model.evaluate("state", _QUESTIONS)


@pytest.mark.parametrize("status", [408, 429, 500, 502, 503])
async def test_a_provider_that_may_answer_later_is_told_apart(status):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"error": {"message": "busy"}})

    model = DecisionModel(_endpoint(), http_client_factory=_client_factory(handler))

    with pytest.raises(ModelProviderUnavailableError) as raised:
        await model.evaluate("state", _QUESTIONS)
    assert raised.value.status_code == status


@pytest.mark.parametrize("status", [400, 401, 402, 404])
async def test_a_refused_call_is_not_mistaken_for_an_outage(status):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"error": {"message": "no"}})

    model = DecisionModel(_endpoint(), http_client_factory=_client_factory(handler))

    with pytest.raises(ModelCallError) as raised:
        await model.evaluate("state", _QUESTIONS)
    assert not isinstance(raised.value, ModelProviderUnavailableError)
