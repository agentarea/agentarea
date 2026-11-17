package handlers

import (
	"context"
	"errors"
	"net/http"
	"time"
	"unicode/utf8"

	"github.com/go-chi/chi/v5"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/insights/service"
)

// Signups is the analytics runtime's sign-up hook (service.Analytics).
type Signups interface {
	CheckSignupKey(authorization string) error
	RecordSignup(ctx context.Context, hook service.SignupHook, method string) error
}

// MountSignups mounts POST /internal/analytics/signups, Kratos's after-registration hook
// (api/internal/analytics_signups.py), outside /v1 and the public spec.
func MountSignups(r chi.Router, errs *httpx.Errors, s Signups) {
	r.Method(http.MethodPost, "/internal/analytics/signups", errs.Handler(func(w http.ResponseWriter, r *http.Request) error {
		switch err := s.CheckSignupKey(r.Header.Get("Authorization")); {
		case errors.Is(err, service.ErrSignupHookOff):
			return httpx.HTTPError(http.StatusNotFound, "Not Found")
		case err != nil:
			return httpx.HTTPError(http.StatusUnauthorized, "Unauthorized")
		}
		v, err := readBody(r)
		if err != nil {
			return err
		}
		hook, err := signupBody(v)
		if err != nil {
			return err
		}
		if err := s.RecordSignup(r.Context(), hook, r.URL.Query().Get("method")); err != nil {
			return err
		}
		w.WriteHeader(http.StatusNoContent)
		return nil
	}))
}

// signupBody is SignupHook: identity_id str 1..64, created_at a datetime, request_url str | None.
// A datetime without an offset is UTC.
func signupBody(v any) (service.SignupHook, error) {
	var errs []httpx.FieldError
	var hook service.SignupHook
	o, ok := model(v, []any{"body"}, &errs)
	if !ok {
		return hook, httpx.Validation(errs...)
	}
	switch raw, present := o.Get("identity_id"); id := raw.(type) {
	case string:
		switch n := utf8.RuneCountInString(id); {
		case n < 1:
			errs = append(errs, httpx.StringTooShort(1, "body", "identity_id"))
		case n > 64:
			errs = append(errs, httpx.StringTooLong(64, "body", "identity_id"))
		}
		hook.IdentityID = id
	default:
		if present {
			errs = append(errs, httpx.StringType("body", "identity_id"))
		} else {
			errs = append(errs, httpx.Missing("body", "identity_id"))
		}
	}
	switch raw, present := o.Get("created_at"); at := raw.(type) {
	case string:
		t, err := parseDatetime(at)
		if err != nil {
			errs = append(errs, httpx.ValueError("created_at is not an ISO 8601 datetime", "body", "created_at"))
		}
		hook.CreatedAt = t
	default:
		if present {
			errs = append(errs, httpx.ValueError("created_at is not an ISO 8601 datetime", "body", "created_at"))
		} else {
			errs = append(errs, httpx.Missing("body", "created_at"))
		}
	}
	switch raw, _ := o.Get("request_url"); u := raw.(type) {
	case nil:
	case string:
		hook.RequestURL = &u
	default:
		errs = append(errs, httpx.StringType("body", "request_url"))
	}
	if len(errs) > 0 {
		return hook, httpx.Validation(errs...)
	}
	return hook, nil
}

func parseDatetime(s string) (time.Time, error) {
	if t, err := time.Parse(time.RFC3339Nano, s); err == nil {
		return t.UTC(), nil
	}
	return time.Parse("2006-01-02T15:04:05.999999999", s)
}
