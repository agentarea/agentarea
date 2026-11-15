// Package service of models: provider configurations, model instances,
// discovery, the configuration test and the model caller.
package service

import (
	"context"
	"errors"
	"fmt"
	"time"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/money"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
)

// NotFoundError is NotFoundError (404 not_found) with its detail.
type NotFoundError struct{ Detail string }

func (e *NotFoundError) Error() string { return e.Detail }

// BadRequestError is BadRequestError (400 bad_request).
type BadRequestError struct{ Detail string }

func (e *BadRequestError) Error() string { return e.Detail }

// HTTPError is a bare HTTPException: status and detail.
type HTTPError struct {
	Status int
	Detail string
}

func (e *HTTPError) Error() string { return e.Detail }

// PlatformManagedError is PlatformManagedConfigError (403 platform_managed_config).
type PlatformManagedError struct{ Name, Verb string }

func (e *PlatformManagedError) Error() string {
	return fmt.Sprintf("Provider configuration '%s' is supplied by the platform and cannot be %s.", e.Name, e.Verb)
}

// EndpointNotAllowed is the one answer to an endpoint refused on save.
const EndpointNotAllowed = "endpoint_url must be a public address this deployment may call"

// ErrNoCaller: the request carries no workspace caller.
var ErrNoCaller = errors.New("no workspace caller")

// Service is the models service.
type Service struct {
	d  Deps
	st Store
}

// New builds the service.
func New(d Deps) *Service {
	if d.Now == nil {
		d.Now = time.Now
	}
	return &Service{d: d, st: d.Store}
}

// Currency is the billing currency customer pricing names.
func (s *Service) Currency() money.Currency {
	if s.d.Pricing == nil || s.d.Pricing() == nil {
		return money.USDAtProviderCost{}.Currency()
	}
	return s.d.Pricing().Currency()
}

func caller(ctx context.Context) (scope.Workspace, string, error) {
	c, ok := authn.CallerFrom(ctx)
	if !ok || c.Workspace.IsZero() {
		return scope.Workspace{}, "", ErrNoCaller
	}
	return c.Workspace, c.UserID, nil
}

func (s *Service) admin(ctx context.Context) error {
	if s.d.Admin == nil {
		return nil
	}
	return s.d.Admin(ctx)
}
