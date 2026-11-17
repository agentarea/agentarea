package httpx

import (
	"net/url"
)

// Pagination is PaginationParams: page (1..MaxPage, default 1), page_size
// (1..MaxPageSize, default DefaultPageSize) and an optional search.
type Pagination struct {
	Page     int
	PageSize int
	Search   *string
}

// Offset is the rows to skip.
func (p Pagination) Offset() int { return (p.Page - 1) * p.PageSize }

// Limit is the rows to return.
func (p Pagination) Limit() int { return p.PageSize }

// ParsePagination reads page, page_size and search from the query as
// FastAPI does, every failing parameter reported at ("query", name). The
// last value of a repeated parameter wins, as in Starlette's QueryParams.
func ParsePagination(q url.Values) (Pagination, error) {
	p := Pagination{Page: 1, PageSize: DefaultPageSize}
	var errs []FieldError
	if v, ok := last(q, "page"); ok {
		n, fe := ValidateInt(v, IntBounds{Ge: 1, HasGe: true, Le: MaxPage, HasLe: true}, "query", "page")
		if fe != nil {
			errs = append(errs, *fe)
		} else {
			p.Page = int(n)
		}
	}
	if v, ok := last(q, "page_size"); ok {
		n, fe := ValidateInt(v, IntBounds{Ge: 1, HasGe: true, Le: MaxPageSize, HasLe: true}, "query", "page_size")
		if fe != nil {
			errs = append(errs, *fe)
		} else {
			p.PageSize = int(n)
		}
	}
	if v, ok := last(q, "search"); ok {
		p.Search = &v
	}
	return p, Validation(errs...)
}

func last(q url.Values, key string) (string, bool) {
	vs := q[key]
	if len(vs) == 0 {
		return "", false
	}
	return vs[len(vs)-1], true
}

// NewPage is the PaginatedResponse a route builds: has_next while rows
// remain past this page.
func NewPage[T any](items []T, total int, p Pagination) Page[T] {
	if items == nil {
		items = []T{}
	}
	return Page[T]{Items: items, Total: total, Page: p.Page, PageSize: p.PageSize, HasNext: p.Offset()+p.PageSize < total}
}
