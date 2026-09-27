"""A page number that would push OFFSET past a Postgres bigint is refused.

Unbounded, ``?page=4141865216742638144`` reached SQL as an OFFSET asyncpg could
not encode and answered 500 (found by the live-stack OpenAPI fuzz on /skills).
"""

from agentarea_common.base.pagination import PaginationParams
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

app = FastAPI()


@app.get("/items")
def items(pagination: PaginationParams = Depends()) -> dict[str, int]:
    return {"offset": pagination.offset}


def test_an_absurd_page_is_a_client_error():
    response = TestClient(app).get("/items", params={"page": 4141865216742638144, "page_size": 58})

    assert response.status_code == 422


def test_a_deep_page_is_still_served():
    response = TestClient(app).get("/items", params={"page": 10_000, "page_size": 100})

    assert response.json() == {"offset": 999_900}
