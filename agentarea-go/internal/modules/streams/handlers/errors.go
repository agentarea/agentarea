package handlers

import (
	"errors"
	"net/http"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authz"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/streams/domain"
)

// MapError renders the module's errors as the Python routes answer them.
func MapError(err error) (*httpx.Error, bool) {
	var inv *domain.ValidationError
	var se *domain.StreamError
	switch {
	case errors.Is(err, domain.ErrNoSubscription):
		return httpx.Conflict(err.Error()), true
	case errors.Is(err, authz.ErrDenied):
		return httpx.HTTPError(http.StatusForbidden, "Permission denied"), true
	case errors.As(err, &inv):
		return httpx.BadRequest(inv.Error()), true
	case errors.As(err, &se):
		if st := streamStatus(se.Kind); st != http.StatusBadRequest {
			return httpx.HTTPError(st, se.Msg), true
		}
		return httpx.BadRequest(se.Msg), true
	}
	return nil, false
}

func streamStatus(kind error) int {
	is := func(targets ...error) bool {
		for _, t := range targets {
			if errors.Is(kind, t) {
				return true
			}
		}
		return false
	}
	switch {
	case is(domain.ErrStreamNotFound, domain.ErrSourceNotFound, domain.ErrSubscriptionNotFound, domain.ErrEventNotFound):
		return http.StatusNotFound
	case is(domain.ErrNameTaken, domain.ErrManagedByPlatform, domain.ErrInUse, domain.ErrNotAForward, domain.ErrNotAProcessor):
		return http.StatusConflict
	case is(domain.ErrQuotaExceeded):
		return http.StatusTooManyRequests
	}
	return http.StatusBadRequest
}
