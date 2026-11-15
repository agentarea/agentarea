package handlers

import (
	"errors"
	"net/http"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authz"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/domain"
)

// MapError renders the module's errors as Python raises them: a refused input
// is 400 with its message, a row still in use 409, a missing row 404.
func MapError(err error) (*httpx.Error, bool) {
	var inv *domain.Invalid
	var linked *domain.Linked
	var nf *domain.NotFound
	var fb *domain.Forbidden
	var un *domain.Unavailable
	switch {
	case errors.As(err, &fb):
		return httpx.HTTPError(http.StatusForbidden, fb.Msg), true
	case errors.As(err, &un):
		return httpx.HTTPError(http.StatusServiceUnavailable, un.Msg), true
	case errors.Is(err, authz.ErrDenied):
		return httpx.HTTPError(http.StatusForbidden, "Permission denied"), true
	case errors.As(err, &inv):
		return httpx.BadRequest(inv.Msg), true
	case errors.As(err, &linked):
		return httpx.Conflict(linked.Msg), true
	case errors.As(err, &nf):
		return httpx.NotFound(nf.Msg), true
	}
	return instanceError(err)
}
