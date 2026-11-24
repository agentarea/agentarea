package api

import (
	"context"
	"errors"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx/wirejson"
)

// BundleRefusal is a write a bundle deploy asked for that its owner refused
// as invalid input (Python's ValueError, MCPValidationError, PermissionError);
// the text is the reason.
type BundleRefusal struct{ Msg string }

func (e *BundleRefusal) Error() string { return e.Msg }

// ErrBundleEntityGone is an entity a redeploy updates that went away mid-update.
var ErrBundleEntityGone = errors.New("the entity went away mid-update")

// BundleTool names one tool of an agent: a code toolset, an MCP connection
// by id, a delegate (Type "agent", Name its key in the bundle, AgentID the
// agent), or an OpenAPI connection (Type "openapi", Name and ConnectionID its id).
type BundleTool struct {
	Type, Name   string
	AgentID      *string
	ConnectionID *string
}

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

// BundleMCPUpdate is a redeploy of an MCP connection the bundle created.
// Spec, set when the bundle declares its own server, replaces that spec's
// transport and env schema; Instance replaces the instance's name, environment
// and headers, where KeepSecret() keeps the secret stored under that name.
// SetContextSecret writes Instance.ContextSecret, nil clearing it.
type BundleMCPUpdate struct {
	Spec             *MCPSpecNew
	Instance         BundleInstance
	SetContextSecret bool
}

// BundleMCPs is what a bundle deploy reads and writes of MCP connections
// (connections module). A refusal of the input is a *BundleRefusal.
type BundleMCPs interface {
	// InstanceName is the name of an instance the workspace sees.
	InstanceName(ctx context.Context, c authn.Caller, id string) (string, bool, error)
	// InstancesNamed are the ids of the instances the workspace sees under name.
	InstancesNamed(ctx context.Context, c authn.Caller, name string) ([]string, error)
	// InstanceSpecID is the spec the instance runs from.
	InstanceSpecID(ctx context.Context, c authn.Caller, id string) (string, bool, error)
	// CreateFromSpec connects specID; a spec outside the workspace is copied into it.
	CreateFromSpec(ctx context.Context, c authn.Caller, specID string, in BundleInstance) (BundleMCPCreated, error)
	// CreateWithSpec creates spec and its instance.
	CreateWithSpec(ctx context.Context, c authn.Caller, spec MCPSpecNew, in BundleInstance) (BundleMCPCreated, error)
	// UpdateMCP applies a redeploy to the instance id and its spec.
	UpdateMCP(ctx context.Context, c authn.Caller, id string, u BundleMCPUpdate) error
	// Rediscover starts a verification of the instance detached from the
	// request; once it finishes the instance stores the tools it serves now.
	Rediscover(ctx context.Context, c authn.Caller, id string) error
	DeleteInstance(ctx context.Context, c authn.Caller, id string) error
	DeleteSpec(ctx context.Context, c authn.Caller, id string) error
	// SecretProblem is the refusal of the caller referencing the workspace secret, "" when it may.
	SecretProblem(ctx context.Context, c authn.Caller, name string) (string, error)
	// CarriesSecretRef reports a secret reference at any depth of v.
	CarriesSecretRef(v any) bool
	// SecretRef is the value an instance's environment or headers reference a workspace secret with.
	SecretRef(name string) any
	// KeepSecret is the value an update sends for a secret it leaves as stored.
	KeepSecret() any
	// SecretsMatch compares values with the secrets the instance stores under
	// those environment or header names, and contextSecret with its context
	// secret; it answers equal or not, never a value.
	SecretsMatch(ctx context.Context, c authn.Caller, id string, values map[string]string, contextSecret *string) (map[string]bool, bool, error)
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

// BundleSchedule is the trigger an automation creates: on Cron in Timezone,
// or, when StreamID is set, on that stream's events matching Filter. It asks
// AgentID Text, or, when TaskDefinitionID is set, runs that saved task with Parameters.
type BundleSchedule struct {
	Name, Description, AgentID, Cron, Timezone, Text string
	StreamID                                         *string
	Filter                                           map[string]any
	TaskDefinitionID                                 *string
	Parameters                                       map[string]any
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
// Timezone are set for a cron trigger, Filter for a stream trigger.
// TaskDefinitionID, written when TaskDefinitionSet, is the saved task it
// runs with Parameters, nil when it asks Text.
type BundleTriggerUpdate struct {
	Description, AgentID, Text string
	Cron, Timezone             *string
	Filter                     map[string]any
	TaskDefinitionSet          bool
	TaskDefinitionID           *string
	Parameters                 map[string]any
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
	// ScheduleProblem is why validate_configuration refuses the trigger, "" when it does not.
	ScheduleProblem(ctx context.Context, n BundleSchedule) (string, error)
	CreateSchedule(ctx context.Context, n BundleSchedule) (string, error)
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

// BundleStreamSource is a source a deploy adds to a stream: Values are
// credentials as given, Secrets the credentials read from the workspace
// secret of that name.
type BundleStreamSource struct {
	Type, Kind      string
	Config          map[string]string
	Values, Secrets map[string]string
}

// BundleStreamWriter is a processor of the stream when Code is set, else a
// forward; Outputs are the ids of the streams it writes into.
type BundleStreamWriter struct {
	Code    *string
	Outputs []string
	Filter  map[string]any
}

// BundleStreamSpec is a stream as a deploy declares it.
type BundleStreamSpec struct {
	Name, Description string
	Sources           []BundleStreamSource
	Writers           []BundleStreamWriter
}

// BundleStreams is what a bundle deploy reads and writes of streams (streams
// module). ctx carries the caller. A refusal of the input is a *BundleRefusal.
type BundleStreams interface {
	StreamName(ctx context.Context, id string) (string, bool, error)
	// StreamNamed is the id of the workspace's stream called name.
	StreamNamed(ctx context.Context, name string) (string, bool, error)
	// StreamProblem is why the stream's sources or writers would be refused,
	// "" when they would not; outputs are not checked.
	StreamProblem(ctx context.Context, spec BundleStreamSpec) (string, error)
	// CreateStream makes the stream with its sources and writers, or nothing of it.
	CreateStream(ctx context.Context, spec BundleStreamSpec) (string, error)
	// UpdateStream gives the stream spec's description, sources and writers: a
	// source of the same type, kind and settings stays, the credentials given
	// written over its own; every other source and writer is replaced.
	// Triggers' subscriptions stay.
	UpdateStream(ctx context.Context, id string, spec BundleStreamSpec) error
	DeleteStream(ctx context.Context, id string) error
}

// BundleOpenAPIParam is a header, query parameter or URL variable of an
// OpenAPI connection: Value, the value of the workspace secret SecretName,
// or, when Keep, the value the connection stores already. Secret marks a
// query parameter stored as a secret.
type BundleOpenAPIParam struct {
	Name, Value  string
	SecretName   *string
	Secret, Keep bool
}

// BundleOpenAPISpec is an OpenAPI connection as a deploy writes it: its spec
// at SpecURL, or Spec inline.
type BundleOpenAPISpec struct {
	Name, BaseURL             string
	Description, SpecURL      *string
	Spec                      any
	Headers, Query, Variables []BundleOpenAPIParam
}

// BundleOpenAPIs is what a bundle deploy reads and writes of OpenAPI
// connections (connections module). A refusal of the input is a *BundleRefusal.
type BundleOpenAPIs interface {
	ConnectionName(ctx context.Context, c authn.Caller, id string) (string, bool, error)
	// ConnectionsNamed are the ids of the connections the workspace sees under name.
	ConnectionsNamed(ctx context.Context, c authn.Caller, name string) ([]string, error)
	// OpenAPIProblem is why creating the connection would be refused, "" when
	// it would not; a spec_url is not fetched.
	OpenAPIProblem(ctx context.Context, c authn.Caller, spec BundleOpenAPISpec) (string, error)
	// CreateOpenAPI creates the connection with the tools its spec declares.
	CreateOpenAPI(ctx context.Context, c authn.Caller, spec BundleOpenAPISpec) (string, error)
	// UpdateOpenAPI writes spec over the connection and discovers its tools again.
	UpdateOpenAPI(ctx context.Context, c authn.Caller, id string, spec BundleOpenAPISpec) error
	DeleteOpenAPI(ctx context.Context, c authn.Caller, id string) error
	// HeaderIsSecret reports a header whose value the connection stores as a secret.
	HeaderIsSecret(name string) bool
}

// BundleTaskSpec is a saved task as a deploy writes it: a run of AgentID
// asked Prompt, with Parameters.
type BundleTaskSpec struct {
	Name, Prompt, AgentID string
	Parameters            map[string]any
}

// BundleTaskRef is a saved task of the workspace and the agent it runs.
type BundleTaskRef struct{ ID, AgentID string }

// BundleTasks is what a bundle deploy reads and writes of saved tasks (agents
// module). A refusal of the input is a *BundleRefusal.
type BundleTasks interface {
	TaskName(ctx context.Context, c authn.Caller, id string) (string, bool, error)
	// TaskNamed are the workspace's saved tasks called name.
	TaskNamed(ctx context.Context, c authn.Caller, name string) ([]BundleTaskRef, error)
	CreateTask(ctx context.Context, c authn.Caller, spec BundleTaskSpec) (string, error)
	// UpdateTask writes spec over the saved task; moving it to another agent is
	// refused while triggers run it.
	UpdateTask(ctx context.Context, c authn.Caller, id string, spec BundleTaskSpec) error
	DeleteTask(ctx context.Context, c authn.Caller, id string) error
}

// BundleProjectSpec is a project as a deploy writes it, with the agents, MCP
// instances and skills it groups by id.
type BundleProjectSpec struct {
	Name                               string
	Description, Instructions          *string
	AgentIDs, MCPInstanceIDs, SkillIDs []string
}

// BundleProjects is what a bundle deploy reads and writes of projects
// (projects module). A refusal of the input is a *BundleRefusal.
type BundleProjects interface {
	ProjectName(ctx context.Context, c authn.Caller, id string) (string, bool, error)
	CreateProject(ctx context.Context, c authn.Caller, spec BundleProjectSpec) (string, error)
	// UpdateProject writes spec's name, description and instructions and links
	// what it lists; a link in managed, what the last deploy linked, that spec
	// drops is removed, and links the deploy never made stay.
	UpdateProject(ctx context.Context, c authn.Caller, id string, spec, managed BundleProjectSpec) error
	DeleteProject(ctx context.Context, c authn.Caller, id string) error
}

// BundleRule is a governance rule a bundle policy installs as.
type BundleRule struct {
	Enabled     bool
	Priority    int64
	SubjectType string
	SubjectID   string
	Target      string
	Effect      string
	Params      wirejson.Object
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
