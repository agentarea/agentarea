"""Typed clients for the model kinds that are not chat: image, video and decision.

Each is built from a resolved ``ModelEndpoint`` (see ``ModelService``) and returns
what it produced together with its cost in USD, as the provider reported it.
Image generation goes through LiteLLM; video and decision models have no LiteLLM
call, so they speak the provider's HTTP API (OpenRouter's ``/videos`` and
``/systemone``) directly.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, cast

import httpx
from agentarea_common.money import to_money
from agentarea_common.utils.url_safety import OutboundPolicy, UnsafeUrlError, validate_outbound_url

from agentarea_llm.domain.media import DecisionQuestionType, VideoJobStatus
from agentarea_llm.domain.provider_profiles import profile_for

logger = logging.getLogger(__name__)

HttpClientFactory = Callable[[], httpx.AsyncClient]

# LiteLLM moves the provider's ``usage.cost`` into this hidden header on an image
# response; its own ``response_cost`` is a price-table estimate, not the charge.
_LITELLM_PROVIDER_COST_HEADER = "llm_provider-x-litellm-response-cost"

_IMAGE_SIGNATURES: tuple[tuple[bytes, str], ...] = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
)

# A generated video is buffered before it is written to the workspace; anything
# larger is refused rather than held in the worker's memory.
MAX_VIDEO_BYTES = 512 * 1024 * 1024


class ModelCallError(RuntimeError):
    """The provider refused the call or answered with something unusable."""


class ModelProviderUnavailableError(ModelCallError):
    """The provider timed out, rate-limited or failed on its side; the same call may pass later."""

    def __init__(self, message: str, *, status_code: int):
        super().__init__(message)
        self.status_code = status_code


_RETRYABLE_STATUSES = frozenset({408, 429})


class ModelCostUnavailableError(RuntimeError):
    """Neither the provider nor the model spec says what a call cost."""


@dataclass(frozen=True)
class ModelEndpoint:
    """Everything a call needs about one model instance, credential resolved."""

    instance_id: str
    provider_type: str
    model_name: str
    api_key: str | None
    endpoint_url: str | None
    managed_by: str | None
    input_cost_per_token: Decimal | None
    output_cost_per_token: Decimal | None

    def api_url(self, path: str) -> str:
        url = profile_for(self.provider_type).resolve_api_url(self.endpoint_url, path)
        if url is None:
            raise ModelCallError(
                f"model instance {self.instance_id} uses provider {self.provider_type!r}, "
                "which has no public address, and has no endpoint_url configured"
            )
        return url

    def headers(self) -> dict[str, str]:
        return profile_for(self.provider_type).build_headers(self.api_key)


@dataclass(frozen=True)
class GeneratedMedia:
    content: bytes
    media_type: str
    cost_usd: Decimal | None


@dataclass(frozen=True)
class SubmittedVideo:
    provider_job_id: str
    status: VideoJobStatus


@dataclass(frozen=True)
class VideoStatus:
    status: VideoJobStatus
    cost_usd: Decimal | None
    error: str | None


@dataclass(frozen=True)
class DecisionResult:
    answers: dict[str, dict[str, Any]]
    cost_usd: Decimal
    input_tokens: int
    output_tokens: int


def _image_media_type(content: bytes) -> str:
    for signature, media_type in _IMAGE_SIGNATURES:
        if content.startswith(signature):
            return media_type
    if content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return "image/webp"
    raise ModelCallError("image model returned bytes that are not a PNG, JPEG, GIF or WebP image")


def _job_status(payload: Mapping[str, Any]) -> VideoJobStatus:
    raw = payload.get("status")
    try:
        return VideoJobStatus(raw)
    except ValueError as error:
        raise ModelCallError(f"video job has unknown status {raw!r}") from error


def _usage(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    """The response's ``usage`` object; absent means the provider reported none."""
    usage = payload.get("usage")
    if usage is None:
        return {}
    if not isinstance(usage, Mapping):
        raise ModelCallError(f"response usage is not an object: {usage!r}")
    return usage


def _provider_cost(value: Any) -> Decimal | None:
    return to_money(value) if value is not None else None


def _error_text(error: Any) -> str | None:
    """OpenRouter documents a job's ``error`` both as a string and as ``{code, message}``."""
    if error is None or isinstance(error, str):
        return error
    if isinstance(error, dict) and error.get("message"):
        return str(error["message"])
    return str(error)


def _raise_for_status(response: httpx.Response, what: str) -> None:
    if response.is_success:
        return
    message = f"{what} failed with HTTP {response.status_code}: {response.text[:500]}"
    if response.status_code in _RETRYABLE_STATUSES or response.status_code >= 500:
        raise ModelProviderUnavailableError(message, status_code=response.status_code)
    raise ModelCallError(message)


class ImageModel:
    """Generates one image per call through ``litellm.aimage_generation``."""

    def __init__(self, endpoint: ModelEndpoint, *, litellm_client: Any = None) -> None:
        self._endpoint = endpoint
        # LiteLLM 1.100 runs the OpenRouter image call on its sync handler even
        # from aimage_generation, so an injected client must be a sync HTTPHandler.
        self._litellm_client = litellm_client

    @property
    def endpoint(self) -> ModelEndpoint:
        return self._endpoint

    async def generate(self, prompt: str, *, size: str | None = None) -> GeneratedMedia:
        import litellm

        endpoint = self._endpoint
        kwargs: dict[str, Any] = {
            "model": f"{endpoint.provider_type}/{endpoint.model_name}",
            "prompt": prompt,
            "api_key": endpoint.api_key,
        }
        if endpoint.endpoint_url:
            api_base = endpoint.api_url("")
            # LiteLLM makes this request with its own client, so the member-set
            # address is checked here, as the SSRF-guarded client would.
            try:
                await asyncio.to_thread(
                    validate_outbound_url, api_base, policy=OutboundPolicy.from_env()
                )
            except UnsafeUrlError as error:
                raise ModelCallError(f"image model endpoint refused: {error}") from error
            kwargs["api_base"] = api_base
        if size:
            kwargs["size"] = size
        if self._litellm_client is not None:
            kwargs["client"] = self._litellm_client
        try:
            response = await litellm.aimage_generation(**kwargs)
        except Exception as error:
            raise ModelCallError(f"image generation failed: {error}") from error

        if response.data is None:
            raise ModelCallError("image model returned no image data")
        images = [item for item in response.data if getattr(item, "b64_json", None)]
        if not images:
            raise ModelCallError("image model returned no image bytes")
        try:
            content = base64.b64decode(cast(str, images[0].b64_json), validate=True)
        except (binascii.Error, ValueError) as error:
            raise ModelCallError("image model returned malformed base64") from error

        cost = _provider_cost(_litellm_provider_cost(response))
        if cost is None:
            raise ModelCostUnavailableError(
                f"image model {endpoint.model_name} reported no cost, so the call cannot be billed"
            )
        return GeneratedMedia(content=content, media_type=_image_media_type(content), cost_usd=cost)


def _litellm_provider_cost(response: Any) -> Any:
    """The provider-reported cost LiteLLM carried on an image response, or None."""
    hidden = getattr(response, "_hidden_params", None)
    if not isinstance(hidden, Mapping):
        raise ModelCallError("image response carries no LiteLLM metadata to read a cost from")
    headers = hidden.get("additional_headers")
    if headers is None:
        return None
    if not isinstance(headers, Mapping):
        raise ModelCallError("image response metadata has malformed additional_headers")
    return headers.get(_LITELLM_PROVIDER_COST_HEADER)


class VideoModel:
    """Submits, polls and downloads asynchronous video generations."""

    def __init__(self, endpoint: ModelEndpoint, *, http_client_factory: HttpClientFactory) -> None:
        self._endpoint = endpoint
        self._client = http_client_factory

    @property
    def endpoint(self) -> ModelEndpoint:
        return self._endpoint

    async def submit(
        self,
        prompt: str,
        *,
        duration: int | None = None,
        resolution: str | None = None,
        aspect_ratio: str | None = None,
    ) -> SubmittedVideo:
        body: dict[str, Any] = {"model": self._endpoint.model_name, "prompt": prompt}
        for name, value in (
            ("duration", duration),
            ("resolution", resolution),
            ("aspect_ratio", aspect_ratio),
        ):
            if value is not None:
                body[name] = value
        async with self._client() as client:
            response = await client.post(
                self._endpoint.api_url("/videos"), json=body, headers=self._endpoint.headers()
            )
        _raise_for_status(response, "video submission")
        payload = response.json()
        job_id = payload.get("id")
        if not isinstance(job_id, str) or not job_id:
            raise ModelCallError("video submission returned no job id")
        return SubmittedVideo(provider_job_id=job_id, status=_job_status(payload))

    async def status(self, provider_job_id: str) -> VideoStatus:
        async with self._client() as client:
            response = await client.get(
                self._endpoint.api_url(f"/videos/{provider_job_id}"),
                headers=self._endpoint.headers(),
            )
        _raise_for_status(response, "video status")
        payload = response.json()
        return VideoStatus(
            status=_job_status(payload),
            cost_usd=_provider_cost(_usage(payload).get("cost")),
            error=_error_text(payload.get("error")),
        )

    async def content(self, provider_job_id: str, index: int = 0) -> GeneratedMedia:
        async with (
            self._client() as client,
            client.stream(
                "GET",
                self._endpoint.api_url(f"/videos/{provider_job_id}/content"),
                params={"index": index},
                headers=self._endpoint.headers(),
            ) as response,
        ):
            if not response.is_success:
                await response.aread()
            _raise_for_status(response, "video download")
            content_type = response.headers.get("content-type")
            if content_type is None:
                raise ModelCallError("video download returned no content type")
            media_type = content_type.split(";", 1)[0].strip()
            if not media_type.startswith("video/"):
                raise ModelCallError(f"video download returned {media_type}")
            chunks: list[bytes] = []
            size = 0
            async for chunk in response.aiter_bytes():
                size += len(chunk)
                if size > MAX_VIDEO_BYTES:
                    raise ModelCallError(
                        f"video is larger than the {MAX_VIDEO_BYTES}-byte limit; refusing it"
                    )
                chunks.append(chunk)
        return GeneratedMedia(content=b"".join(chunks), media_type=media_type, cost_usd=None)


def _validate_questions(questions: Mapping[str, Any]) -> None:
    if not questions:
        raise ValueError("a decision needs at least one question")
    for key, question in questions.items():
        if not isinstance(question, Mapping):
            raise ValueError(f"question {key!r} must be an object")
        raw_type = question.get("type")
        try:
            kind = DecisionQuestionType(raw_type)
        except ValueError as error:
            raise ValueError(
                f"question {key!r} has type {raw_type!r}; expected one of "
                f"{', '.join(DecisionQuestionType)}"
            ) from error
        if not question.get("instructions"):
            raise ValueError(f"question {key!r} needs instructions")
        criteria = question.get("criteria")
        if kind is DecisionQuestionType.CHOICE and not (isinstance(criteria, Mapping) and criteria):
            raise ValueError(f"choice question {key!r} needs criteria naming each option")
        if kind is DecisionQuestionType.SCORE and not (isinstance(criteria, list) and criteria):
            raise ValueError(f"score question {key!r} needs a non-empty criteria list")


class DecisionModel:
    """Answers structured questions about a state through ``POST /systemone``."""

    def __init__(self, endpoint: ModelEndpoint, *, http_client_factory: HttpClientFactory) -> None:
        self._endpoint = endpoint
        self._client = http_client_factory

    @property
    def endpoint(self) -> ModelEndpoint:
        return self._endpoint

    async def evaluate(
        self, state: str | Mapping[str, Any] | list[Any], questions: Mapping[str, Any]
    ) -> DecisionResult:
        _validate_questions(questions)
        body = {"model": self._endpoint.model_name, "state": state, "questions": dict(questions)}
        async with self._client() as client:
            response = await client.post(
                self._endpoint.api_url("/systemone"), json=body, headers=self._endpoint.headers()
            )
        _raise_for_status(response, "decision")
        payload = response.json()

        raw_answers = payload.get("answers")
        if not isinstance(raw_answers, dict):
            raise ModelCallError("decision returned no answers")
        answers: dict[str, dict[str, Any]] = {}
        for key, question in questions.items():
            answer = raw_answers.get(key)
            expected = DecisionQuestionType(question["type"])
            if not isinstance(answer, dict) or answer.get("type") != expected:
                raise ModelCallError(f"decision returned no {expected} answer for question {key!r}")
            if answer.get(expected.value) is None:
                raise ModelCallError(f"decision answer for {key!r} has no {expected} value")
            answers[key] = answer

        usage = _usage(payload)
        input_tokens, output_tokens = usage.get("input_tokens"), usage.get("output_tokens")
        if not isinstance(input_tokens, int) or not isinstance(output_tokens, int):
            raise ModelCallError("decision response has no input_tokens/output_tokens usage")
        return DecisionResult(
            answers=answers,
            cost_usd=self._cost(usage, input_tokens, output_tokens),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )

    def _cost(self, usage: Mapping[str, Any], input_tokens: int, output_tokens: int) -> Decimal:
        reported = _provider_cost(usage.get("cost"))
        if reported is not None:
            return reported
        endpoint = self._endpoint
        if endpoint.input_cost_per_token is None or endpoint.output_cost_per_token is None:
            raise ModelCostUnavailableError(
                f"decision model {endpoint.model_name} reported no cost and its spec has no "
                "per-token prices, so the call cannot be billed"
            )
        return to_money(
            Decimal(input_tokens) * endpoint.input_cost_per_token
            + Decimal(output_tokens) * endpoint.output_cost_per_token
        )
