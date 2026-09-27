from fastapi import Query
from pydantic import BaseModel


class PaginatedResponse[T](BaseModel):
    items: list[T]
    total: int
    page: int
    page_size: int
    has_next: bool


# The highest page any list accepts, so the OFFSET it becomes always fits the
# database's integer. Routes that declare their own ``page`` use it too.
MAX_PAGE = 1_000_000
# The same bound for routes that page by ``offset``: past int64 the database
# rejects the query and the route answered 500 instead of 422.
MAX_OFFSET = 1_000_000_000


class PaginationParams:
    def __init__(
        self,
        page: int = Query(1, ge=1, le=MAX_PAGE),
        page_size: int = Query(50, ge=1, le=100),
        search: str | None = Query(None),
    ):
        self.page = page
        self.page_size = page_size
        self.search = search

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size

    @property
    def limit(self) -> int:
        return self.page_size
