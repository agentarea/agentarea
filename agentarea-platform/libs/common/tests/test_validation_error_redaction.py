"""A 422 never echoes the submitted body back, so a secret in it never leaks."""

from agentarea_common.exceptions.handlers import validation_exception_handler
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient
from pydantic import BaseModel, model_validator


class _Credentials(BaseModel):
    name: str
    api_key: str | None = None
    api_key_secret_id: str | None = None

    @model_validator(mode="after")
    def _one_key_source(self) -> "_Credentials":
        if self.api_key and self.api_key_secret_id:
            raise ValueError("Provide either api_key or api_key_secret_id, not both")
        return self


def _client() -> TestClient:
    app = FastAPI()
    app.add_exception_handler(RequestValidationError, validation_exception_handler)

    @app.post("/credentials")
    async def create(body: _Credentials) -> dict[str, str]:
        return {"name": body.name}

    return TestClient(app)


def test_a_model_level_error_does_not_echo_the_secret() -> None:
    response = _client().post(
        "/credentials",
        json={
            "name": "c",
            "api_key": "PLAINTEXT-KEY-123",  # pragma: allowlist secret
            "api_key_secret_id": "s",
        },
    )

    assert response.status_code == 422
    assert "PLAINTEXT-KEY-123" not in response.text
    assert response.json()["errors"][0]["msg"].endswith("not both")


def test_a_field_error_keeps_its_location_and_message() -> None:
    response = _client().post("/credentials", json={"api_key": "PLAINTEXT-KEY-123"})

    assert response.status_code == 422
    error = response.json()["errors"][0]
    assert error["loc"] == ["body", "name"]
    assert error["type"] == "missing"
    assert "input" not in error
    assert "PLAINTEXT-KEY-123" not in response.text
