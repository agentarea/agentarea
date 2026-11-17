package api

import (
	"context"
	"errors"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
)

// EgressExitsUnsupported is EgressExitsNotSupportedError's message.
const EgressExitsUnsupported = "egress exits need the enterprise edition"

// ErrEgressExitsUnsupported is EgressExitsNotSupportedError: the deployment
// has no egress_exits extension.
var ErrEgressExitsUnsupported = errors.New(EgressExitsUnsupported)

// EgressExitNotFoundError is an exit the workspace does not have; ID is as
// the caller named it.
type EgressExitNotFoundError struct{ ID string }

func (e *EgressExitNotFoundError) Error() string { return "Egress exit " + e.ID + " not found" }

// EgressExitBinding is what connections asks before an instance binds an
// exit (EgressExitService.require_bindable). App passes it only where the
// edition enforces exits.
type EgressExitBinding interface {
	// RequireBindable returns *EgressExitNotFoundError for an exit the
	// caller's workspace does not have, and authz.ErrDenied when the caller
	// may not use the workspace's own exit; a platform exit needs no grant.
	RequireBindable(ctx context.Context, c authn.Caller, exitID string) error
}
