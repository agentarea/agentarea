"""Tests for the unified RFC 9457 (problem+json) error framework."""

import pytest
from agentarea_common.exceptions import (
    AppError,
    ConflictError,
    problem_dict,
    register_error_handlers,
)
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError


class _FakeUniqueViolationError(Exception):
    """Stand-in for an asyncpg/psycopg unique-violation ``orig``."""

    sqlstate = "23505"


class _FakeNotNullViolationError(Exception):
    sqlstate = "23502"


@pytest.fixture
def client():
    app = FastAPI()
    register_error_handlers(app)

    @app.get("/boom")
    async def boom():
        raise ValueError("internal detail that must not leak")

    @app.get("/conflict")
    async def conflict():
        raise ConflictError("Skill already installed", code="skill_already_installed")

    @app.get("/app-error-default")
    async def app_error_default():
        raise AppError()  # bare base -> 500, generic

    @app.get("/integrity-unique")
    async def integrity_unique():
        raise IntegrityError("INSERT ...", {}, _FakeUniqueViolationError("dup key"))

    @app.get("/integrity-notnull")
    async def integrity_notnull():
        raise IntegrityError("INSERT ...", {}, _FakeNotNullViolationError("null col"))

    @app.get("/http-error")
    async def http_error():
        raise HTTPException(status_code=403, detail="nope")

    @app.get("/validate")
    async def validate(n: int):  # missing/invalid ?n -> RequestValidationError
        return {"n": n}

    # raise_server_exceptions=False so the catch-all 500 is returned, not re-raised
    return TestClient(app, raise_server_exceptions=False)


def _assert_problem(response, status_code: int):
    assert response.status_code == status_code
    assert response.headers["content-type"].startswith("application/problem+json")
    body = response.json()
    assert body["status"] == status_code
    assert "code" in body
    assert "detail" in body
    assert "title" in body
    return body


def test_unhandled_exception_returns_problem_json_not_plaintext(client):
    """The catch-all turns any exception into JSON 500 — no plain-text body."""
    response = client.get("/boom")
    body = _assert_problem(response, 500)
    assert body["code"] == "internal_error"
    # Internal exception message must not leak to the client.
    assert "must not leak" not in response.text


def test_app_error_subclass_renders_declared_status_and_code(client):
    response = client.get("/conflict")
    body = _assert_problem(response, 409)
    assert body["code"] == "skill_already_installed"
    assert body["detail"] == "Skill already installed"


def test_bare_app_error_defaults_to_500(client):
    response = client.get("/app-error-default")
    body = _assert_problem(response, 500)
    assert body["code"] == "internal_error"


def test_integrity_unique_violation_maps_to_409(client):
    response = client.get("/integrity-unique")
    body = _assert_problem(response, 409)
    assert body["code"] == "conflict"


def test_integrity_non_conflict_maps_to_500(client):
    """A not-null violation is a bug, not a conflict — it must be a 500."""
    response = client.get("/integrity-notnull")
    _assert_problem(response, 500)


def test_http_exception_rendered_as_problem(client):
    response = client.get("/http-error")
    body = _assert_problem(response, 403)
    assert body["detail"] == "nope"


def test_request_validation_error_maps_to_422_with_errors(client):
    response = client.get("/validate?n=notanint")
    body = _assert_problem(response, 422)
    assert body["code"] == "validation_error"
    assert isinstance(body["errors"], list)


def test_problem_dict_defaults_title_to_status_phrase():
    body = problem_dict(status_code=404, code="not_found", detail="x")
    assert body["title"] == "Not Found"
    assert body["type"] == "about:blank"
    assert body["status"] == 404


def test_problem_dict_extra_does_not_overwrite_standard_members():
    body = problem_dict(
        status_code=402,
        code="budget_cap_exceeded",
        detail="over",
        extra={"cap_usd": 10, "status": 999},  # 'status' must not be overwritten
    )
    assert body["status"] == 402
    assert body["cap_usd"] == 10
