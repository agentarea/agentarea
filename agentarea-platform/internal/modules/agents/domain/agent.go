package domain

import (
	"errors"
	"fmt"
	"regexp"
	"strings"
	"unicode"
)

// Status values of an agent.
const (
	StatusActive   = "active"
	StatusArchived = "archived"
)

// Agent is the agents row; ids are canonical UUID strings.
type Agent struct {
	ID                 string
	WorkspaceID        string
	CreatedBy          string
	Name               string
	Slug               string
	Status             string
	Description        *string
	Instruction        *string
	ModelID            *string
	ClientID           *string
	HarnessClientID    *string
	Tools              []byte
	Planning           *bool
	A2UIEnabled        *bool
	ReasoningEffort    *string
	ReasoningMaxTokens *int32
	AnswerCheck        []byte
	AgentType          string
	RegistryItemID     *string
	Skills             []SkillRef
	// UpdateAvailable and IsCatalog are the read-time markers of a fork and of a catalog projection.
	UpdateAvailable bool
	IsCatalog       bool
}

// SkillRef is a skill attached to an agent.
type SkillRef struct {
	ID             string
	Name           string
	Description    *string
	SourceType     string
	Package        *string
	RegistryItemID *string
}

// ErrAgentNotFound is "Agent not found".
var ErrAgentNotFound = errors.New("agent not found")

// ErrAgentArchived is AgentArchivedError: an archived agent takes no edit.
type ErrAgentArchivedError struct{ ID string }

func (e *ErrAgentArchivedError) Error() string {
	return fmt.Sprintf("Agent %s is archived. Restore it before using or editing it.", e.ID)
}

// ErrReasoningConflict is ReasoningConflictError.
var ErrReasoningConflict = errors.New("set reasoning_effort or reasoning_max_tokens, not both")

// InvalidError is one of the domain errors Python's main.py maps to 400.
type InvalidError struct {
	Code   string
	Detail string
}

func (e *InvalidError) Error() string { return e.Detail }

// Codes of InvalidError.
const (
	CodeInvalidModelID   = "invalid_model_id"
	CodeInvalidClientID  = "invalid_client_id"
	CodeInvalidDelegate  = "invalid_delegate"
	CodeInvalidMCPTool   = "invalid_mcp_tool"
	CodeInvalidCodeTools = "bad_request"
)

// NotNullError is a patch that sets a non-nullable field to null.
type NotNullError struct{ Field string }

func (e *NotNullError) Error() string { return e.Field + " may be omitted, but not set to null" }

var (
	nonAlnum = regexp.MustCompile(`[^a-z0-9]+`)
	nonWord  = regexp.MustCompile(`[^a-zA-Z0-9_]`)
	repeated = regexp.MustCompile(`_+`)
)

const maxSlugLength = 100

// Slug is generate_slug: ASCII-folded, lowercase, hyphenated, at most 100
// characters, "item" when nothing is left.
func Slug(name string) string {
	var b strings.Builder
	for _, r := range foldASCII(name) {
		b.WriteRune(r)
	}
	slug := strings.Trim(nonAlnum.ReplaceAllString(strings.ToLower(b.String()), "-"), "-")
	if len(slug) > maxSlugLength {
		slug = strings.TrimRight(slug[:maxSlugLength], "-")
	}
	if slug == "" {
		return "item"
	}
	return slug
}

// foldASCII is NFKD then ascii/ignore for the Latin accents the names carry;
// every other non-ASCII rune is dropped, as Python does.
func foldASCII(s string) string {
	var b strings.Builder
	for _, r := range s {
		if r < unicode.MaxASCII {
			b.WriteRune(r)
			continue
		}
		if base, ok := latinBase()[r]; ok {
			b.WriteString(base)
		}
	}
	return b.String()
}

// DelegateToolName is delegate_tool_name.
func DelegateToolName(agentName string) string {
	s := repeated.ReplaceAllString(nonWord.ReplaceAllString(agentName, "_"), "_")
	s = strings.Trim(s, "_")
	if s == "" || (s[0] >= '0' && s[0] <= '9') {
		s = "agent_" + s
	}
	return "delegate_to_" + s
}

// AgentAddress is agent_address: the card URL and the origin name one agent.
func AgentAddress(url string) string {
	url = strings.TrimSpace(url)
	url = strings.TrimSuffix(url, "/.well-known/agent-card.json")
	return strings.TrimRight(url, "/")
}

// MaxSlugSuffix is the last collision suffix tried.
const MaxSlugSuffix = 999

// NotFoundError is NotFoundError(message): a 404.
type NotFoundError struct{ Message string }

func (e *NotFoundError) Error() string { return e.Message }

// RunnerKind reports whether kind is one a runner drives.
func RunnerKind(kind string) bool {
	switch kind {
	case "codex", "claude", "opencode", "gemini", "qwen", "goose", "cursor", "acp":
		return true
	}
	return false
}
