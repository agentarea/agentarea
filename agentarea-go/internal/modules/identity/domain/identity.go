package domain

import (
	"errors"
	"time"
)

// Workspace is a workspaces row.
type Workspace struct {
	ID          string
	Slug        string
	Name        string
	OwnerUserID string
	LogoKey     *string
}

// Invitation statuses (workspaces/models.py).
const (
	StatusPending  = "pending"
	StatusAccepted = "accepted"
	StatusRevoked  = "revoked"
)

// Invitation is a workspace_invitations row without its token hash.
// Timestamps are naive, as stored.
type Invitation struct {
	ID                  string
	CreatedAt           time.Time
	WorkspaceID         string
	Email               *string
	InvitedBy           string
	Status              string
	ExpiresAt           time.Time
	AcceptedAt          *time.Time
	AcceptedByUserID    *string
	MembershipGrantedAt *time.Time
}

// APIKey is an api_keys row without its hash. ClientID is set on a runner's
// key, which the keys routes never show.
type APIKey struct {
	ID             string
	Name           string
	TokenPrefix    string
	IsActive       bool
	ExpiresAt      *time.Time
	AccessCount    int
	LastAccessedAt *time.Time
	CreatedAt      time.Time
	AgentID        *string
	CreatedBy      string
	ClientID       *string
}

// EmailDelivery is InvitationEmailDelivery.
type EmailDelivery string

const (
	DeliverySent          EmailDelivery = "sent"
	DeliveryNotRequested  EmailDelivery = "not_requested"
	DeliveryNotConfigured EmailDelivery = "not_configured"
	DeliveryFailed        EmailDelivery = "failed"
)

// InvitationError is one of the invitation service's refusals; Status is
// INVITATION_ERROR_STATUS's and Detail the exception's message.
type InvitationError struct {
	Status int
	Detail string
}

func (e *InvitationError) Error() string { return e.Detail }

// The refusals of accept (workspaces/service.py _redeemable, admit).
var (
	ErrInvitationNotFound  = &InvitationError{Status: 404, Detail: "invalid token"}
	ErrAddressedElsewhere  = &InvitationError{Status: 403, Detail: "invitation addressed to another account"}
	ErrInvitationRevoked   = &InvitationError{Status: 410, Detail: "invitation revoked"}
	ErrInvitationAccepted  = &InvitationError{Status: 409, Detail: "invitation already accepted"}
	ErrInvitationExpired   = &InvitationError{Status: 410, Detail: "invitation expired"}
	ErrAgentNotFound       = errors.New("agent not found")
	ErrSlugsExhausted      = errors.New("could not allocate a unique workspace slug")
	ErrEmptyWorkspaceName  = errors.New("workspace name must not be empty")
	ErrAPIKeyCreateFailed  = errors.New("failed to create API key")
	ErrGraphSeedFailed     = errors.New("workspace authorization graph unavailable")
	ErrMembershipGraphDown = errors.New("workspace membership graph unavailable")
)

// AddressedTo is _is_addressed_to: an open link is for anyone, an emailed
// one only for that address (strip + casefold).
func AddressedTo(inv Invitation, email *string, fold func(string) string) bool {
	if inv.Email == nil {
		return true
	}
	if email == nil {
		return false
	}
	return fold(*inv.Email) == fold(*email)
}
