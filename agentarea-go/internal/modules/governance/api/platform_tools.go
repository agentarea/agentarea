package api

import (
	"context"
	"encoding/json"
	"errors"
	"time"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
)

// ErrPolicyRuleNotFound: the workspace has no such rule (RULE_NOT_FOUND).
var ErrPolicyRuleNotFound = errors.New("Policy rule not found") //nolint:staticcheck // Python's message

// ErrRunPolicyNotFound: the run has no stored effective policy.
var ErrRunPolicyNotFound = errors.New("Run policy snapshot not found") //nolint:staticcheck // Python's message

// ErrNoSuchSecret: the workspace has no secret by that name.
var ErrNoSuchSecret = errors.New("No such secret") //nolint:staticcheck // Python's message

// PolicyRuleFilter narrows policies_list; nil leaves a field unfiltered.
type PolicyRuleFilter struct {
	SubjectType, SubjectID, Effect, Target *string
	Enabled                                *bool
}

// PlatformPolicies is what the platform policies toolset calls
// (tools/policies_toolset.py). Rules render as PolicyRuleResponse, policies
// as EffectivePolicy. The rule methods refuse a caller who does not
// administer the workspace (authz.ErrNotWorkspaceAdmin); invalid documents
// are errors whose text is the tool's answer.
type PlatformPolicies interface {
	ListRules(ctx context.Context, c authn.Caller, f PolicyRuleFilter) ([]any, error)
	GetRule(ctx context.Context, c authn.Caller, ruleID string) (any, error)
	// CreateRule takes a PolicyRuleCreateRequest document.
	CreateRule(ctx context.Context, c authn.Caller, rule json.RawMessage) (any, error)
	// UpdateRule takes a PolicyRuleUpdateRequest document of the fields to write.
	UpdateRule(ctx context.Context, c authn.Caller, ruleID string, patch json.RawMessage) (any, error)
	DeleteRule(ctx context.Context, c authn.Caller, ruleID string) error
	// PreviewEffective is the ceiling a run of agentID ("" for none) would get.
	PreviewEffective(ctx context.Context, c authn.Caller, agentID string) (any, error)
	// RunPolicy is the effective policy a run was dispatched under.
	RunPolicy(ctx context.Context, c authn.Caller, runID string) (any, error)
}

// PlatformSecret is a user secret as the secrets toolset lists it.
type PlatformSecret struct {
	ID          string
	Name        string
	Description *string
}

// PlatformSecrets is what the platform secrets toolset calls
// (tools/secrets_toolset.py): the caller's own secrets through the catalog.
// Create and DeleteByName refuse a caller who does not administer the workspace.
type PlatformSecrets interface {
	ListOwn(ctx context.Context, c authn.Caller) ([]PlatformSecret, error)
	Create(ctx context.Context, c authn.Caller, name, value string, description *string) (PlatformSecret, error)
	// DeleteByName answers ErrNoSuchSecret for a name the workspace lacks.
	DeleteByName(ctx context.Context, c authn.Caller, name string) error
}

// PlatformAuditQuery is one audit_list page; empty strings and nil times do not filter.
type PlatformAuditQuery struct {
	Action, ActorID, ResourceType, ResourceID string
	Since, Until                              *time.Time
	Cursor                                    string
	Limit                                     int
}

// PlatformAuditEvent is one audit row as audit_list shows it.
type PlatformAuditEvent struct {
	ID, ActorID, ActorType, Action, ResourceType string
	CreatedAt                                    time.Time
	ResourceID, RequestID                        *string
}

// PlatformAudit is what the platform audit toolset calls (tools/audit_toolset.py);
// it refuses a caller who does not administer the workspace.
type PlatformAudit interface {
	List(ctx context.Context, c authn.Caller, q PlatformAuditQuery) ([]PlatformAuditEvent, error)
}
