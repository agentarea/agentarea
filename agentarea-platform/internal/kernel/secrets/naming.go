package secrets

import (
	"errors"
	"fmt"
	"regexp"
	"strings"
)

// ReservedPrefixes are the prefixes a platform producer mints names under
// (agentarea_secrets/naming.py RESERVED_PREFIXES). A user may not type one:
// (workspace_id, secret_name) is unique, so a colliding name would overwrite
// someone else's live credential.
func ReservedPrefixes() []string {
	return []string{
		"provider_config_",
		"mcp_instance_",
		"mcp_auth_cred:",
		"channel_cred:",
		"wallet_creds_",
		"openapi:",
		"task-input/",
		"a2a_push_token:",
		"task_webhook:",
	}
}

var (
	userNameRE = regexp.MustCompile(`^[a-z0-9][a-z0-9_-]{0,62}[a-z0-9]$`)
	uuidRE     = regexp.MustCompile(`^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$`)
)

const uuidLen = 36

// ErrInvalidName is a user secret name the catalog will not accept.
var ErrInvalidName = errors.New("invalid secret name")

// ErrReservedName is a name in the space platform producers mint into; it
// wraps ErrInvalidName.
var ErrReservedName = fmt.Errorf("%w: reserved", ErrInvalidName)

// NameError carries Python's message for a refused name.
type NameError struct {
	Message  string
	Reserved bool
}

func (e *NameError) Error() string { return e.Message }

// Is lets errors.Is match ErrInvalidName, and ErrReservedName for a reserved one.
func (e *NameError) Is(target error) bool {
	return target == ErrInvalidName || (e.Reserved && target == ErrReservedName)
}

// OwnerRef is the entity a platform-minted name was built from.
type OwnerRef struct {
	Type string
	ID   string
}

func isUUID(s string) bool { return uuidRE.MatchString(s) }

func uuidAtStart(rest string) (string, bool) {
	if len(rest) < uuidLen {
		return "", false
	}
	c := rest[:uuidLen]
	return c, isUUID(c)
}

func parseWholeUUID(typ string) func(string) (OwnerRef, bool) {
	return func(rest string) (OwnerRef, bool) {
		if isUUID(rest) {
			return OwnerRef{typ, rest}, true
		}
		return OwnerRef{}, false
	}
}

func openapiSlots() []string { return []string{":header:", ":url_var:"} }

type parser struct {
	prefix string
	parse  func(rest string) (OwnerRef, bool)
}

func parsers() []parser {
	return []parser{
		{"provider_config_", parseWholeUUID("provider_config")},
		{"mcp_instance_", func(rest string) (OwnerRef, bool) {
			// mcp_instance_{uuid}_{env_name}: env names hold underscores too,
			// so the uuid's fixed width is the only separator.
			id, ok := uuidAtStart(rest)
			if !ok || !strings.HasPrefix(rest[uuidLen:], "_") {
				return OwnerRef{}, false
			}
			return OwnerRef{"mcp_instance", id}, true
		}},
		{"mcp_auth_cred:", parseWholeUUID("mcp_auth_config")},
		{"channel_cred:", func(rest string) (OwnerRef, bool) {
			i := strings.LastIndex(rest, ":")
			if i < 0 || !isUUID(rest[i+1:]) {
				return OwnerRef{}, false
			}
			return OwnerRef{"trigger", rest[i+1:]}, true
		}},
		{"wallet_creds_", parseWholeUUID("agent")},
		{"openapi:", func(rest string) (OwnerRef, bool) {
			id, ok := uuidAtStart(rest)
			if !ok || !hasAnyPrefix(rest[uuidLen:], openapiSlots()) {
				return OwnerRef{}, false
			}
			return OwnerRef{"openapi_connection", id}, true
		}},
		{"task-input/", func(rest string) (OwnerRef, bool) {
			task, _, found := strings.Cut(rest, "/")
			if !found || !isUUID(task) {
				return OwnerRef{}, false
			}
			return OwnerRef{"task", task}, true
		}},
		{"a2a_push_token:", func(rest string) (OwnerRef, bool) {
			// Only the task id is ours; the config id comes from the client.
			task, cfg, found := strings.Cut(rest, ":")
			if !found || cfg == "" || !isUUID(task) {
				return OwnerRef{}, false
			}
			return OwnerRef{"task", task}, true
		}},
		{"task_webhook:", parseWholeUUID("task")},
	}
}

func hasAnyPrefix(s string, prefixes []string) bool {
	for _, p := range prefixes {
		if strings.HasPrefix(s, p) {
			return true
		}
	}
	return false
}

// ParseManagedName reads a platform-minted name back into its owner; false
// when no producer matches. Callers decide what that means.
func ParseManagedName(name string) (OwnerRef, bool) {
	for _, p := range parsers() {
		if strings.HasPrefix(name, p.prefix) {
			return p.parse(name[len(p.prefix):])
		}
	}
	return OwnerRef{}, false
}

// ManagedField is the slot on the owner a name fills: the env var of an MCP
// instance, the header of an OpenAPI connection, the channel type, the task
// input field. Empty when the name carries none.
func ManagedField(name string) string {
	switch {
	case strings.HasPrefix(name, "mcp_instance_"):
		rest := name[len("mcp_instance_"):]
		if _, ok := uuidAtStart(rest); ok && strings.HasPrefix(rest[uuidLen:], "_") {
			return rest[uuidLen+1:]
		}
	case strings.HasPrefix(name, "openapi:"):
		rest := name[len("openapi:"):]
		if _, ok := uuidAtStart(rest); ok {
			for _, slot := range openapiSlots() {
				if strings.HasPrefix(rest[uuidLen:], slot) {
					return rest[uuidLen+len(slot):]
				}
			}
		}
	case strings.HasPrefix(name, "channel_cred:"):
		if t, _, found := strings.Cut(name[len("channel_cred:"):], ":"); found {
			return t
		}
	case strings.HasPrefix(name, "task-input/"):
		if _, field, found := strings.Cut(name[len("task-input/"):], "/"); found {
			return field
		}
	}
	return ""
}

// ReservedPrefix is the reserved prefix a name starts with, or "".
func ReservedPrefix(name string) string {
	for _, p := range ReservedPrefixes() {
		if strings.HasPrefix(name, p) {
			return p
		}
	}
	return ""
}

// ValidateUserName returns nil for a name a user may claim. A reserved prefix
// is checked first: it also fails the slug pattern, and calling it malformed
// would send the user off to fix punctuation on a name they may never have.
func ValidateUserName(name string) error {
	if p := ReservedPrefix(name); p != "" {
		return &NameError{
			Message:  fmt.Sprintf("Secret name may not start with '%s': that prefix is reserved for secrets the platform manages on behalf of a connection.", p),
			Reserved: true,
		}
	}
	if !userNameRE.MatchString(name) {
		return &NameError{Message: fmt.Sprintf("Invalid secret name '%s'. Use 2-64 characters: lowercase letters, digits, '-' and '_', starting and ending with a letter or digit.", name)}
	}
	return nil
}
