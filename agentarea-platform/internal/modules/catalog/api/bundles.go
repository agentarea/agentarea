package api

import (
	"context"
	"errors"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
)

// BundleRefusal is a write a bundle deploy asked for that its owner refused
// as invalid input (Python's ValueError, MCPValidationError, PermissionError);
// the text is the reason.
type BundleRefusal struct{ Msg string }

func (e *BundleRefusal) Error() string { return e.Msg }

// ErrBundleEntityGone is an entity a redeploy updates that went away mid-update.
var ErrBundleEntityGone = errors.New("the entity went away mid-update")

// BundleTool names one tool of an agent: a code toolset, or an MCP connection by id.
type BundleTool struct{ Type, Name string }

// BundleFile is one file of a skill package, path relative to its root.
type BundleFile struct{ Path, Text string }

// BundleAgentConfig is what validate_config checks of an agent a deploy writes.
type BundleAgentConfig struct {
	ModelID            string
	Toolsets           []string
	ClientID           *string
	ReasoningEffort    *string
	ReasoningMaxTokens *int32
}

// BundleAgentNew is AgentCreate as a deploy sends it.
type BundleAgentNew struct {
	Name, Description, Instruction, ModelID string
	ClientID                                *string
	Tools                                   []BundleTool
	SkillIDs                                []string
	ReasoningEffort                         *string
	ReasoningMaxTokens                      *int32
}

// BundleAgentUpdate is AgentUpdate as a redeploy sends it. The agent's tools
// and skills keep what the deploy does not manage: Tools and SkillIDs are
// what the folder declares, ManagedTools and ManagedSkillIDs what the last
// install attached.
type BundleAgentUpdate struct {
	Name, Description, Instruction, ModelID string
	Tools, ManagedTools                     []BundleTool
	SkillIDs, ManagedSkillIDs               []string
	SetReasoning                            bool
	ReasoningEffort                         *string
	ReasoningMaxTokens                      *int32
	SetClient                               bool
	ClientID                                *string
}

// BundleSkillNew is a skill a deploy creates: from GitHubURL when set, else
// from Files when set, else from Content.
type BundleSkillNew struct {
	Name      string
	Content   string
	Files     []BundleFile
	GitHubURL string
}

// BundleAgents is what a bundle deploy reads and writes of agents and skills
// (agents module). A refusal of the input is a *BundleRefusal.
type BundleAgents interface {
	// AgentLive reports a workspace agent that is not archived.
	AgentLive(ctx context.Context, c authn.Caller, id string) (bool, error)
	// AgentProblem is why create_agent would refuse the configuration, "" when it would not.
	AgentProblem(ctx context.Context, c authn.Caller, cfg BundleAgentConfig) (string, error)
	CreateAgent(ctx context.Context, c authn.Caller, in BundleAgentNew) (string, error)
	UpdateAgent(ctx context.Context, c authn.Caller, id string, in BundleAgentUpdate) error
	// DeleteAgent removes an agent the deploy created, and what its create wrote beside it.
	DeleteAgent(ctx context.Context, c authn.Caller, id string) error
	SkillLive(ctx context.Context, c authn.Caller, id string) (bool, error)
	// SkillProblem is the error parsing SKILL.md content raises, "" when it parses.
	SkillProblem(content string) string
	// SkillMainFile is the SKILL.md among paths, matched as the skill service matches it.
	SkillMainFile(paths []string) (string, bool)
	CreateSkill(ctx context.Context, c authn.Caller, in BundleSkillNew) (string, error)
	ReplaceSkillFiles(ctx context.Context, c authn.Caller, id string, files []BundleFile) error
	RenameSkill(ctx context.Context, c authn.Caller, id, name string) error
	DeleteSkill(ctx context.Context, c authn.Caller, id string) error
}

// BundleInstance is the instance a deploy connects: its own environment and
// headers, and the context secret of a URL server.
type BundleInstance struct {
	Name          string
	JSONSpec      map[string]any
	ContextSecret *string
}

// BundleMCPCreated is a connected instance and the spec it runs from.
type BundleMCPCreated struct {
	InstanceID string
	SpecID     string
}

// BundleMCPs is what a bundle deploy reads and writes of MCP connections
// (connections module). A refusal of the input is a *BundleRefusal.
type BundleMCPs interface {
	// InstanceName is the name of an instance the workspace sees.
	InstanceName(ctx context.Context, c authn.Caller, id string) (string, bool, error)
	// CreateFromSpec connects specID; a spec outside the workspace is copied into it.
	CreateFromSpec(ctx context.Context, c authn.Caller, specID string, in BundleInstance) (BundleMCPCreated, error)
	// CreateWithSpec creates spec and its instance.
	CreateWithSpec(ctx context.Context, c authn.Caller, spec MCPSpecNew, in BundleInstance) (BundleMCPCreated, error)
	DeleteInstance(ctx context.Context, c authn.Caller, id string) error
	DeleteSpec(ctx context.Context, c authn.Caller, id string) error
	// SecretProblem is the refusal of the caller referencing the workspace secret, "" when it may.
	SecretProblem(ctx context.Context, c authn.Caller, name string) (string, error)
	// CarriesSecretRef reports a secret reference at any depth of v.
	CarriesSecretRef(v any) bool
	// SecretRef is the value an instance's environment or headers reference a workspace secret with.
	SecretRef(name string) any
	// ContextSecretLength is the length a context secret must have.
	ContextSecretLength() (minimum, maximum int)
	// SpecTransport is the transport an instance of spec gets; false when it declares none.
	SpecTransport(spec MCPSpec) (string, bool)
}

// BundleTrigger is a trigger as a deploy matches it.
type BundleTrigger struct {
	ID, Name, AgentID string
	Active            bool
	StreamID          *string
}

// BundleCron is the cron trigger an automation creates.
type BundleCron struct {
	Name, Description, AgentID, Cron, Timezone, Text string
	Enabled                                          bool
}

// BundleChannelNew is a channel: a stream named Name, its webhook source of
// SourceType holding Credentials, and the stream trigger running AgentID.
type BundleChannelNew struct {
	Name, Description, AgentID, Text, SourceType string
	Enabled                                      bool
	Credentials                                  map[string]string
}

// BundleChannelCreated is what CreateChannel made.
type BundleChannelCreated struct{ TriggerID, StreamID string }

// BundleTriggerUpdate is TriggerUpdate as a redeploy sends it; Cron and
// Timezone are set for a cron trigger.
type BundleTriggerUpdate struct {
	Description, AgentID, Text string
	Cron, Timezone             *string
}

// BundleChannelCredentials are the credentials stored for a channel's webhook source.
type BundleChannelCredentials struct {
	SourceType, CredentialKey string
	Stored                    map[string]any
}

// BundleTriggers is what a bundle deploy reads and writes of triggers and
// channel streams (streams module). ctx carries the caller.
type BundleTriggers interface {
	Trigger(ctx context.Context, id string) (BundleTrigger, bool, error)
	Triggers(ctx context.Context) ([]BundleTrigger, error)
	// CronProblem is why validate_configuration refuses the trigger, "" when it does not.
	CronProblem(ctx context.Context, n BundleCron) (string, error)
	CreateCron(ctx context.Context, n BundleCron) (string, error)
	// CreateChannel makes the channel, or nothing of it.
	CreateChannel(ctx context.Context, n BundleChannelNew) (BundleChannelCreated, error)
	DeleteChannel(ctx context.Context, created BundleChannelCreated) error
	DeleteTrigger(ctx context.Context, id string) error
	UpdateTrigger(ctx context.Context, id string, u BundleTriggerUpdate) error
	SetTriggerEnabled(ctx context.Context, id string, enabled bool) error
	// ChannelCredentials are the credentials of the webhook source feeding the trigger's stream.
	ChannelCredentials(ctx context.Context, triggerID string) (BundleChannelCredentials, bool, error)
	SetChannelCredentials(ctx context.Context, creds BundleChannelCredentials) error
}

// BundleRule is a governance rule a bundle policy installs as.
type BundleRule struct {
	Enabled     bool
	Priority    int64
	SubjectType string
	SubjectID   string
	Target      string
	Effect      string
	Params      any
	Condition   *string
}

// BundleRules is what a bundle deploy reads and writes of governance rules
// (governance module).
type BundleRules interface {
	// RuleProblem is why assert_enforceable refuses the rule, "" when it does not.
	RuleProblem(r BundleRule) string
	// MatchingRule is a rule with r's subject, target and effect, params and condition.
	MatchingRule(ctx context.Context, c authn.Caller, r BundleRule) (string, bool, error)
	RuleLive(ctx context.Context, c authn.Caller, id string) (bool, error)
	CreateRule(ctx context.Context, c authn.Caller, r BundleRule) (string, error)
	// UpdateRule writes r's fields; Enabled only when setEnabled.
	UpdateRule(ctx context.Context, c authn.Caller, id string, r BundleRule, setEnabled bool) error
	DeleteRule(ctx context.Context, c authn.Caller, id string) error
}
