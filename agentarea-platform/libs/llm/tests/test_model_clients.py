"""Typed clients for image, video and decision models, against recorded wire shapes.

The request and response shapes are OpenRouter's published API
(https://openrouter.ai/openapi.json): ``/videos``, ``/videos/{id}``,
``/videos/{id}/content`` and ``/systemone``, plus the OpenAI-compatible
``/images/generations``.
"""

import base64
import json
from decimal import Decimal

import httpx
import pytest
from agentarea_agents_sdk.models.provider_profiles import DEFAULT_PROFILE, ProviderProfile
from agentarea_llm.infrastructure.model_clients import (
    DecisionModel,
    ImageModel,
    ModelCallError,
    ModelEndpoint,
    ModelProviderUnavailableError,
    VideoModel,
)

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
OPENROUTER = ProviderProfile(base_url="https://openrouter.ai/api/v1")


def _endpoint(**overrides) -> ModelEndpoint:
    base = {
        "instance_id": "11111111-1111-1111-1111-111111111111",
        "provider_type": "openrouter",
        "provider": OPENROUTER,
        "model_name": "vendor/model",
        "api_key": "sk-or-test",  # pragma: allowlist secret
        "endpoint_url": None,
        "managed_by": None,
        "input_cost_per_token": None,
        "output_cost_per_token": None,
    }
    return ModelEndpoint(**{**base, **overrides})


def _member_endpoint(**overrides) -> ModelEndpoint:
    """An address a workspace member set: called through the vetted, pinned client."""
    return _endpoint(**{"endpoint_url": "https://proxy.example/api/v1", **overrides})


def _client_factory(handler):
    return lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler))


# -- image ------------------------------------------------------------------


def _image_handler(seen: dict, *, usage: dict | None, data: list[dict] | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = json.loads(request.content)
        body: dict = {
            "created": 1,
            "data": data if data is not None else [{"b64_json": base64.b64encode(PNG).decode()}],
        }
        if usage is not None:
            body["usage"] = usage
        return httpx.Response(200, json=body)

    return handler


def _no_member_client(policy):
    raise AssertionError("a provider's address does not go through the pinned client")


def _image_model(endpoint: ModelEndpoint, handler) -> ImageModel:
    return ImageModel(
        endpoint, http_client_factory=_client_factory(handler), member_client=_no_member_client
    )


async def test_image_generation_returns_bytes_type_and_provider_cost():
    seen: dict = {}
    usage = {"prompt_tokens": 6, "completion_tokens": 1290, "total_tokens": 1296, "cost": 0.0387}
    model = _image_model(
        _endpoint(output_cost_per_image=Decimal("0.5")), _image_handler(seen, usage=usage)
    )

    image = await model.generate("a lighthouse at dusk", size="1024x1536")

    assert image.content == PNG
    assert image.media_type == "image/png"
    assert image.cost_usd == Decimal("0.0387")
    assert seen["url"] == "https://openrouter.ai/api/v1/images/generations"
    assert seen["auth"] == "Bearer sk-or-test"
    assert seen["body"] == {
        "model": "vendor/model",
        "prompt": "a lighthouse at dusk",
        "n": 1,
        "response_format": "b64_json",
        "size": "1024x1536",
    }


async def test_an_image_without_a_provider_cost_is_priced_from_the_spec():
    usage = {"prompt_tokens": 6, "completion_tokens": 1290, "total_tokens": 1296}
    model = _image_model(
        _endpoint(output_cost_per_image=Decimal("0.04")), _image_handler({}, usage=usage)
    )

    image = await model.generate("a lighthouse")

    assert image.content == PNG
    assert image.cost_usd == Decimal("0.04")


async def test_an_image_without_any_price_is_kept_with_its_cost_unknown():
    model = _image_model(_endpoint(), _image_handler({}, usage=None))

    image = await model.generate("a lighthouse")

    assert image.content == PNG
    assert image.cost_usd is None


async def test_image_generation_that_returns_no_image_is_an_error():
    usage = {"cost": 0.001}
    model = _image_model(_endpoint(), _image_handler({}, usage=usage, data=[]))

    with pytest.raises(ModelCallError, match="no image"):
        await model.generate("a lighthouse")


async def test_image_generation_with_malformed_base64_is_an_error():
    model = _image_model(_endpoint(), _image_handler({}, usage=None, data=[{"b64_json": "%%%"}]))

    with pytest.raises(ModelCallError, match="malformed base64"):
        await model.generate("a lighthouse")


@pytest.mark.parametrize("status", [429, 500, 503])
async def test_an_image_provider_that_may_answer_later_is_told_apart(status):
    model = _image_model(
        _endpoint(), lambda request: httpx.Response(status, json={"error": {"message": "busy"}})
    )

    with pytest.raises(ModelProviderUnavailableError) as raised:
        await model.generate("a lighthouse")
    assert raised.value.status_code == status


async def test_a_refused_image_call_does_not_echo_the_providers_body():
    model = _image_model(
        _endpoint(),
        lambda request: httpx.Response(402, text="internal-host.svc.cluster.local said no"),
    )

    with pytest.raises(ModelCallError, match="HTTP 402") as failed:
        await model.generate("a lighthouse")
    assert not isinstance(failed.value, ModelProviderUnavailableError)
    assert "cluster.local" not in str(failed.value)


async def test_an_image_provider_that_times_out_may_answer_later():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    model = _image_model(_endpoint(), handler)

    with pytest.raises(ModelProviderUnavailableError) as raised:
        await model.generate("a lighthouse")
    assert raised.value.status_code == 408


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
        _member_endpoint(model_name="typesafe/jev"),
        http_client_factory=_client_factory(
            _decision_handler(seen, usage={"input_tokens": 100, "output_tokens": 2, "cost": 0.0004})
        ),
    )

    result = await model.evaluate("Customer: my card was charged twice", _QUESTIONS)

    assert seen["url"] == "https://proxy.example/api/v1/systemone"
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
        _member_endpoint(
            input_cost_per_token=Decimal("0.000001"), output_cost_per_token=Decimal("0.00001")
        ),
        http_client_factory=_client_factory(
            _decision_handler({}, usage={"input_tokens": 100, "output_tokens": 2})
        ),
    )

    result = await model.evaluate("state", _QUESTIONS)

    assert result.cost_usd == Decimal("0.000120")


async def test_a_decision_without_any_price_is_kept_with_its_cost_unknown():
    model = DecisionModel(
        _member_endpoint(),
        http_client_factory=_client_factory(
            _decision_handler({}, usage={"input_tokens": 100, "output_tokens": 2})
        ),
    )

    result = await model.evaluate("state", _QUESTIONS)

    assert result.answers
    assert result.cost_usd is None
    assert (result.input_tokens, result.output_tokens) == (100, 2)


async def test_a_missing_answer_is_an_error():
    model = DecisionModel(
        _member_endpoint(),
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
    ("questions", "message"),
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

    model = DecisionModel(_member_endpoint(), http_client_factory=_client_factory(handler))

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
        http_client_factory=_client_factory(handler),
    )

    with pytest.raises(ModelCallError, match="does not call") as refused:
        await model.generate("a lighthouse")
    assert "169.254" not in str(refused.value)


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
        _member_endpoint(),
        http_client_factory=_client_factory(_decision_handler({}, usage={"cost": 0.1})),
    )

    with pytest.raises(ModelCallError, match="input_tokens"):
        await model.evaluate("state", _QUESTIONS)


@pytest.mark.parametrize("status", [408, 429, 500, 502, 503])
async def test_a_provider_that_may_answer_later_is_told_apart(status):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"error": {"message": "busy"}})

    model = DecisionModel(_member_endpoint(), http_client_factory=_client_factory(handler))

    with pytest.raises(ModelProviderUnavailableError) as raised:
        await model.evaluate("state", _QUESTIONS)
    assert raised.value.status_code == status


@pytest.mark.parametrize("status", [400, 401, 402, 404])
async def test_a_refused_call_is_not_mistaken_for_an_outage(status):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"error": {"message": "no"}})

    model = DecisionModel(_member_endpoint(), http_client_factory=_client_factory(handler))

    with pytest.raises(ModelCallError) as raised:
        await model.evaluate("state", _QUESTIONS)
    assert not isinstance(raised.value, ModelProviderUnavailableError)


def _never_vendor(request: httpx.Request) -> httpx.Response:
    raise AssertionError("a member endpoint must go through the pinned client")


async def test_a_member_image_endpoint_is_called_through_the_pinned_client():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = json.loads(request.content)
        body = {"data": [{"b64_json": base64.b64encode(PNG).decode()}], "usage": {"cost": 0.04}}
        return httpx.Response(200, json=body)

    policies: list = []

    def member_client(policy):
        policies.append(policy)
        return httpx.AsyncClient(transport=httpx.MockTransport(handler))

    model = ImageModel(
        _endpoint(provider_type="openai", endpoint_url="https://images.example/v1"),
        http_client_factory=_client_factory(_never_vendor),
        member_client=member_client,
    )

    image = await model.generate("a lighthouse", size="1024x1024")

    assert (image.content, image.media_type, image.cost_usd) == (PNG, "image/png", Decimal("0.04"))
    assert seen["url"] == "https://images.example/v1/images/generations"
    assert seen["auth"] == "Bearer sk-or-test"
    assert seen["body"] == {
        "model": "vendor/model",
        "prompt": "a lighthouse",
        "n": 1,
        "response_format": "b64_json",
        "size": "1024x1024",
    }
    assert len(policies) == 1
    assert policies[0] is not None


async def test_a_member_image_endpoint_error_does_not_echo_the_providers_body():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, text="internal-host.svc.cluster.local said no")

    model = ImageModel(
        _endpoint(endpoint_url="https://images.example/v1"),
        http_client_factory=_client_factory(_never_vendor),
        member_client=lambda policy: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )

    with pytest.raises(ModelCallError, match="HTTP 400") as failed:
        await model.generate("a lighthouse")
    assert "cluster.local" not in str(failed.value)


async def test_a_platform_image_endpoint_is_called_at_its_address_through_the_vendor_client():
    seen: dict = {}
    model = _image_model(
        _endpoint(endpoint_url="https://gateway.internal.example/api/v1", managed_by="platform"),
        _image_handler(seen, usage={"cost": 0.01}),
    )

    image = await model.generate("a lighthouse")

    assert image.cost_usd == Decimal("0.01")
    assert seen["url"] == "https://gateway.internal.example/api/v1/images/generations"


async def test_a_providers_decision_model_is_called_at_its_public_address():
    seen: dict = {}
    model = DecisionModel(
        _endpoint(model_name="typesafe/jev"),
        http_client_factory=_client_factory(
            _decision_handler(seen, usage={"input_tokens": 40, "output_tokens": 2, "cost": 0.0003})
        ),
    )

    result = await model.evaluate("card charged twice", _QUESTIONS)

    assert seen["url"] == "https://openrouter.ai/api/v1/systemone"
    assert seen["body"] == {
        "model": "typesafe/jev",
        "state": "card charged twice",
        "questions": _QUESTIONS,
    }
    assert result.answers["route"]["choice"] == "billing"
    assert result.answers["urgent"]["noul"] == 0.2
    assert result.cost_usd == Decimal("0.0003")
    assert (result.input_tokens, result.output_tokens) == (40, 2)


async def test_a_platform_gateway_decision_is_called_at_its_address():
    seen: dict = {}
    model = DecisionModel(
        _endpoint(
            provider_type="typesafe",
            provider=DEFAULT_PROFILE,
            model_name="jev",
            endpoint_url="https://gateway.internal.example",
            managed_by="platform",
        ),
        http_client_factory=_client_factory(
            _decision_handler(seen, usage={"input_tokens": 4, "output_tokens": 1, "cost": 0.0001})
        ),
    )

    await model.evaluate("state", _QUESTIONS)

    assert seen["url"] == "https://gateway.internal.example/v1/systemone"


async def test_a_decision_provider_without_an_address_fails_loud():
    model = DecisionModel(
        _endpoint(provider_type="typesafe", provider=DEFAULT_PROFILE, model_name="jev"),
        http_client_factory=_client_factory(_never_vendor),
    )

    with pytest.raises(ModelCallError, match="no endpoint_url configured"):
        await model.evaluate("state", _QUESTIONS)


async def test_a_providers_decision_failure_does_not_echo_its_body():
    model = DecisionModel(
        _endpoint(),
        http_client_factory=_client_factory(
            lambda request: httpx.Response(400, text="internal-host.svc.cluster.local said no")
        ),
    )

    with pytest.raises(ModelCallError) as failed:
        await model.evaluate("state", _QUESTIONS)
    assert "cluster.local" not in str(failed.value)


async def test_a_providers_decision_without_a_cost_is_priced_from_the_spec():
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


async def test_a_decision_endpoint_that_cannot_be_reached_fails_as_a_call_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    model = DecisionModel(_endpoint(), http_client_factory=_client_factory(handler))

    with pytest.raises(ModelCallError, match="no answer") as failed:
        await model.evaluate("state", _QUESTIONS)
    assert not isinstance(failed.value, ModelProviderUnavailableError)


async def test_a_decision_body_that_is_not_json_fails_loud():
    model = DecisionModel(
        _endpoint(),
        http_client_factory=_client_factory(lambda request: httpx.Response(200, text="<html>")),
    )

    with pytest.raises(ModelCallError, match="not JSON"):
        await model.evaluate("state", _QUESTIONS)
