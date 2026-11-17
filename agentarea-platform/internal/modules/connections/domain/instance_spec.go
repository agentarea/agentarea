package domain

import (
	"encoding/json"
	"fmt"
	"math"
	"reflect"
	"regexp"
	"slices"
	"sort"
	"strconv"
	"strings"
)

// Spec keys an instance's json_spec carries besides its configuration.
const (
	ContextSigningFlag     = "context_signing"
	ContextSpecKey         = "context"
	ContextSecretMinLength = 32
	ContextSecretMaxLength = 512
	EgressExitSpecKey      = "egress_exit"
	EgressSpecKey          = "egress"
	ToolTimeoutKey         = "tool_timeout_seconds"
	MaxToolTimeoutSeconds  = 1800
)

// EgressExitsUnsupported is EgressExitsNotSupportedError: this edition has no exits.
const EgressExitsUnsupported = "egress exits need the enterprise edition"

// SpecInvalid is MCPValidationError: 422 with every refusal listed.
type SpecInvalid struct{ Errors []string }

func (e *SpecInvalid) Error() string { return "Validation failed: " + strings.Join(e.Errors, "; ") }

// Refused is a SpecInvalid with one message.
func Refused(msg string) *SpecInvalid { return &SpecInvalid{Errors: []string{msg}} }

// InstanceTransportFields are the keys of a submitted spec the server spec owns.
func InstanceTransportFields() []string {
	return []string{"type", "endpoint_url", "image", "command", "args"}
}

// InstanceSystemFields are the keys an update keeps from the stored spec.
func InstanceSystemFields() []string {
	return append(InstanceTransportFields(), "port", "package", "source")
}

// dtoTransportFields is the DTO's INSTANCE_TRANSPORT_FIELDS, sorted.
func dtoTransportFields() []string {
	return []string{"args", "command", "endpoint_url", "image", "package", "port", "source", "type"}
}

func convertedTransportKeys() []string {
	return []string{"type", "endpoint_url", "url", "external_url", "internal_url", "image", "command",
		"args", "cmd", "port", "remote_url"}
}

func copyMap(m map[string]any) map[string]any {
	out := make(map[string]any, len(m))
	for k, v := range m {
		out[k] = v
	}
	return out
}

// NormalizeURLKeys is _normalize_url_keys: a URL spec's endpoint is endpoint_url.
func NormalizeURLKeys(spec map[string]any) map[string]any {
	if spec == nil {
		spec = map[string]any{}
	}
	if spec["type"] != TransportURL || Truthy(spec["endpoint_url"]) {
		return spec
	}
	for _, legacy := range []string{"url", "external_url"} {
		if s, ok := spec[legacy].(string); ok && strings.TrimSpace(s) != "" {
			out := copyMap(spec)
			out["endpoint_url"] = s
			delete(out, legacy)
			return out
		}
	}
	return spec
}

// ServerTransportSpec is server_transport_spec: the transport a server row declares.
func ServerTransportSpec(jsonSpec map[string]any, remoteURL *string, cmd []any, image *string) map[string]any {
	spec := copyMap(jsonSpec)
	setDefault := func(k string, v any) {
		if _, ok := spec[k]; !ok {
			spec[k] = v
		}
	}
	switch {
	case remoteURL != nil && *remoteURL != "":
		setDefault("type", TransportURL)
		setDefault("endpoint_url", *remoteURL)
	case len(cmd) > 0:
		setDefault("type", TransportCommand)
		setDefault("command", cmd[0])
		if len(cmd) > 1 {
			setDefault("args", slices.Clone(cmd[1:]))
		}
	case image != nil && *image != "":
		setDefault("type", TransportDocker)
		setDefault("image", *image)
	}
	return NormalizeURLKeys(spec)
}

// MergeTransportSpec is merge_transport_spec: the server's defaults under the
// instance's config; a package-converted docker instance keeps none of the
// server's transport keys.
func MergeTransportSpec(server, instance map[string]any, transport string) map[string]any {
	img, _ := instance["image"].(string)
	merged := map[string]any{}
	if transport == TransportDocker && strings.TrimSpace(img) != "" {
		for k, v := range server {
			if !slices.Contains(convertedTransportKeys(), k) {
				merged[k] = v
			}
		}
	} else {
		for k, v := range server {
			merged[k] = v
		}
	}
	for k, v := range instance {
		merged[k] = v
	}
	merged["type"] = transport
	return NormalizeURLKeys(merged)
}

func imageName(ref string) string {
	ref, _, _ = strings.Cut(ref, "@")
	if c := strings.LastIndex(ref, ":"); c > strings.LastIndex(ref, "/") {
		ref = ref[:c]
	}
	return ref
}

// ImageServesStdio is image_serves_stdio: a docker spec whose image's OCI
// package declares stdio, and no port.
func ImageServesStdio(spec map[string]any) bool {
	if spec["port"] != nil {
		return false
	}
	var name *string
	if s, ok := spec["image"].(string); ok {
		n := imageName(s)
		name = &n
	}
	var images []map[string]any
	if l, ok := spec["packages"].([]any); ok {
		for _, p := range l {
			if m, ok := p.(map[string]any); ok && m["registryType"] == "oci" {
				images = append(images, m)
			}
		}
	}
	var chosen map[string]any
	if len(images) == 1 {
		chosen = images[0]
	}
	for _, p := range images {
		if id, ok := p["identifier"].(string); ok && id != "" && name != nil && imageName(id) == *name {
			chosen = p
			break
		}
	}
	t, ok := chosen["transport"].(map[string]any)
	return ok && t["type"] == "stdio"
}

// EgressRequired is egress_required.
func EgressRequired(spec map[string]any) bool {
	e, ok := spec[EgressSpecKey].(map[string]any)
	return ok && e["required"] == true
}

// number reads a JSON number: its value and whether it is written as an int.
func number(v any) (f float64, isInt bool, ok bool) {
	switch t := v.(type) {
	case json.Number:
		if i, err := t.Int64(); err == nil {
			return float64(i), true, true
		}
		f, err := t.Float64()
		return f, false, err == nil
	case float64:
		return t, false, true
	case int:
		return float64(t), true, true
	case int64:
		return float64(t), true, true
	}
	return numberOther(v)
}

// numberOther reads a named float type, such as the wire decoder's.
func numberOther(v any) (float64, bool, bool) {
	if rv := reflect.ValueOf(v); rv.Kind() == reflect.Float64 {
		return rv.Float(), false, true
	}
	return 0, false, false
}

// ToolTimeoutError is tool_timeout_error; "" when the spec's timeout is fine.
func ToolTimeoutError(spec map[string]any) string {
	v, ok := spec[ToolTimeoutKey]
	if !ok {
		return ""
	}
	f, _, isNum := number(v)
	if !isNum {
		return "Field '" + ToolTimeoutKey + "' must be a number of seconds"
	}
	if f < 1 || f > MaxToolTimeoutSeconds {
		return fmt.Sprintf("Field '%s' must be between 1 and %d", ToolTimeoutKey, MaxToolTimeoutSeconds)
	}
	return ""
}

func nonEmptyString(v any) bool {
	s, ok := v.(string)
	return ok && strings.TrimSpace(s) != ""
}

func sortedKeys(m map[string]any) []string {
	keys := make([]string, 0, len(m))
	for k := range m {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	return keys
}

// ValidateJSONSpec is MCPConfigurationValidator.validate_json_spec over a
// transport spec.
func ValidateJSONSpec(spec map[string]any) []string {
	var errs []string
	switch t := spec["type"]; t {
	case TransportCommand:
		if _, has := spec["command"]; !has {
			errs = append(errs, "Required field 'command' is missing for type 'command'")
		} else if !nonEmptyString(spec["command"]) {
			errs = append(errs, "Field 'command' must be a non-empty string")
		}
		if args, has := spec["args"]; has {
			if l, ok := args.([]any); !ok {
				errs = append(errs, "Field 'args' must be a list of strings")
			} else {
				for i, a := range l {
					if _, ok := a.(string); !ok {
						errs = append(errs, fmt.Sprintf("Arg at index %d must be a string", i))
					}
				}
			}
		}
	case TransportURL:
		field := "endpoint_url"
		if _, has := spec["url"]; has {
			field = "url"
		}
		if v, has := spec[field]; !has {
			errs = append(errs, "Required field 'url' is missing for type 'url'")
		} else if !nonEmptyString(v) {
			errs = append(errs, "Field 'url' must be a non-empty string")
		} else if s := v.(string); !strings.HasPrefix(s, "http://") && !strings.HasPrefix(s, "https://") {
			errs = append(errs, "Field 'endpoint_url' must start with http:// or https://")
		}
		if h, has := spec["headers"]; has {
			if m, ok := h.(map[string]any); !ok {
				errs = append(errs, "Field 'headers' must be a dictionary")
			} else {
				for _, k := range sortedKeys(m) {
					if strings.TrimSpace(k) == "" {
						errs = append(errs, "Header key '"+k+"' must be a non-empty string")
					}
					if _, ok := m[k].(string); !ok {
						errs = append(errs, "Header '"+k+"' value must be a string")
					}
				}
			}
		}
	case TransportBundle:
		errs = append(errs, "bundle is not a valid MCP server instance type")
	case TransportDocker:
		if _, has := spec["image"]; !has {
			errs = append(errs, "Required field 'image' is missing")
		} else if !nonEmptyString(spec["image"]) {
			errs = append(errs, "Field 'image' must be a non-empty string")
		}
		if p, has := spec["port"]; has {
			f, isInt, ok := number(p)
			if !ok || !isInt || f < 1 || f > 65535 {
				errs = append(errs, "Field 'port' must be an integer between 1 and 65535")
			}
		}
	case nil:
		errs = append(errs, "Required field 'type' is missing (url, docker or command)")
	default:
		errs = append(errs, "Unknown transport type '"+fmt.Sprint(t)+"' (url, docker or command)")
	}
	if env, has := spec["environment"]; has {
		if m, ok := env.(map[string]any); !ok {
			errs = append(errs, "Field 'environment' must be a dictionary")
		} else {
			for _, k := range sortedKeys(m) {
				if strings.TrimSpace(k) == "" {
					errs = append(errs, "Environment variable key '"+k+"' must be a non-empty string")
				}
				if _, ok := m[k].(string); !ok {
					errs = append(errs, "Environment variable '"+k+"' value must be a string")
				}
			}
		}
	}
	if e := ToolTimeoutError(spec); e != "" {
		errs = append(errs, e)
	}
	if cmd, has := spec["cmd"]; has && cmd != nil {
		if l, ok := cmd.([]any); !ok {
			errs = append(errs, "Field 'cmd' must be a list of strings")
		} else {
			for i, c := range l {
				if _, ok := c.(string); !ok {
					errs = append(errs, fmt.Sprintf("Command item at index %d must be a string", i))
				}
			}
		}
	}
	return errs
}

var imageReference = regexp.MustCompile(`^(?:(?:[a-zA-Z0-9]|[a-zA-Z0-9][a-zA-Z0-9-]*[a-zA-Z0-9])(?:\.(?:[a-zA-Z0-9]|[a-zA-Z0-9][a-zA-Z0-9-]*[a-zA-Z0-9]))*(?::[0-9]+)?/)?` +
	`[a-z0-9]+(?:(?:[._]|__|[-]+)[a-z0-9]+)*(?:/[a-z0-9]+(?:(?:[._]|__|[-]+)[a-z0-9]+)*)*` +
	`(?::[A-Za-z0-9_][A-Za-z0-9_.-]{0,127})?` +
	`(?:@[A-Za-z][A-Za-z0-9]*(?:[-_+.][A-Za-z][A-Za-z0-9]*)*:[0-9a-fA-F]{32,})?$`)

// ImageReferenceError is validate_image_reference; "" for a plain reference.
func ImageReferenceError(image string) string {
	if len(image) > 255 || !imageReference.MatchString(image) {
		return PyRepr(image) + " is not a valid container image reference"
	}
	return ""
}

// PGTextProblem is pg_text_problem: the first string Postgres cannot store as
// text. Go's decoder already replaced unpaired surrogates, so only NUL is left.
func PGTextProblem(v any, path string) string {
	switch t := v.(type) {
	case string:
		if strings.ContainsRune(t, 0) {
			return path + " contains a NUL character"
		}
	case map[string]any:
		for _, k := range sortedKeys(t) {
			if strings.ContainsRune(k, 0) {
				return "a key in " + path + " contains a NUL character"
			}
			if p := PGTextProblem(t[k], path+"."+k); p != "" {
				return p
			}
		}
	case []any:
		for i, x := range t {
			if p := PGTextProblem(x, path+"["+strconv.Itoa(i)+"]"); p != "" {
				return p
			}
		}
	}
	return ""
}

func exactlyEnabled(v any) bool {
	m, ok := v.(map[string]any)
	return ok && len(m) == 1 && m["enabled"] == true
}

// SpecKind says which DTO's json_spec validators apply.
type SpecKind int

const (
	// InstanceCreateSpec is MCPServerInstanceCreate.json_spec.
	InstanceCreateSpec SpecKind = iota
	// InstanceUpdateSpec is MCPServerInstanceUpdate.json_spec.
	InstanceUpdateSpec
	// ServerSpec is MCPServerCreate.json_spec.
	ServerSpec
)

// JSONSpecError is the DTO's json_spec validator chain: the first refusal, "" when none.
func JSONSpecError(spec map[string]any, kind SpecKind) string {
	if p := PGTextProblem(spec, "$"); p != "" {
		return p
	}
	if s, has := spec["storage"]; has && s != nil && !exactlyEnabled(s) {
		return `json_spec.storage must be exactly {"enabled": true}`
	}
	if c, has := spec[ContextSpecKey]; has && c != nil && !exactlyEnabled(c) {
		return `json_spec.context must be exactly {"enabled": true}`
	}
	if e, has := spec[EgressExitSpecKey]; has && e != nil {
		s, ok := e.(string)
		if !ok || !isUUIDText(s) {
			return "json_spec.egress_exit must be an egress exit id"
		}
	}
	if kind != InstanceUpdateSpec {
		if img, has := spec["image"]; has && img != nil {
			s, ok := img.(string)
			if !ok {
				return "json_spec.image must be a string"
			}
			if e := ImageReferenceError(s); e != "" {
				return e
			}
		}
	}
	switch kind {
	case ServerSpec:
		if CarriesSecretRef(spec) {
			return "a server spec may not reference a workspace secret"
		}
		if _, has := spec[EgressExitSpecKey]; has {
			return "json_spec.egress_exit is set on an instance, not a server spec"
		}
		if e, has := spec[EgressSpecKey]; has {
			m, ok := e.(map[string]any)
			_, isBool := m["required"].(bool)
			if !ok || len(m) != 1 || !isBool {
				return `json_spec.egress must be exactly {"required": <bool>}`
			}
		}
	case InstanceCreateSpec, InstanceUpdateSpec:
		if _, has := spec[EgressSpecKey]; has {
			return "json_spec.egress is set on a server spec, not an instance"
		}
	}
	if kind == InstanceUpdateSpec {
		var hit []string
		for _, f := range dtoTransportFields() {
			if _, has := spec[f]; has {
				hit = append(hit, f)
			}
		}
		if len(hit) > 0 {
			return "Instance json_spec cannot update transport fields: " + strings.Join(hit, ", ")
		}
	}
	return ""
}

var uuidText = regexp.MustCompile(`^(?i)(urn:uuid:)?\{?[0-9a-f]{8}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{12}\}?$`)

// isUUIDText is what uuid.UUID(value) accepts, near enough: hyphens optional, braces, urn.
func isUUIDText(s string) bool { return uuidText.MatchString(strings.TrimSpace(s)) }

// PyRepr is repr() of a decoded JSON value.
func PyRepr(v any) string {
	switch t := v.(type) {
	case nil:
		return "None"
	case bool:
		if t {
			return "True"
		}
		return "False"
	case string:
		q := "'"
		if strings.Contains(t, "'") && !strings.Contains(t, `"`) {
			q = `"`
		}
		var b strings.Builder
		b.WriteString(q)
		for _, r := range t {
			switch {
			case r == '\\':
				b.WriteString(`\\`)
			case string(r) == q:
				b.WriteString(`\` + q)
			case r == '\n':
				b.WriteString(`\n`)
			case r == '\r':
				b.WriteString(`\r`)
			case r == '\t':
				b.WriteString(`\t`)
			case r < 0x20 || r == 0x7f:
				fmt.Fprintf(&b, `\x%02x`, r)
			default:
				b.WriteRune(r)
			}
		}
		b.WriteString(q)
		return b.String()
	case json.Number:
		return t.String()
	case float64:
		if t == math.Trunc(t) && math.Abs(t) < 1e16 {
			return strconv.FormatFloat(t, 'f', 1, 64)
		}
		return strconv.FormatFloat(t, 'g', -1, 64)
	case []any:
		parts := make([]string, len(t))
		for i, x := range t {
			parts[i] = PyRepr(x)
		}
		return "[" + strings.Join(parts, ", ") + "]"
	case map[string]any:
		keys := sortedKeys(t)
		parts := make([]string, len(keys))
		for i, k := range keys {
			parts[i] = PyRepr(k) + ": " + PyRepr(t[k])
		}
		return "{" + strings.Join(parts, ", ") + "}"
	}
	if f, _, ok := numberOther(v); ok {
		return PyRepr(f)
	}
	return fmt.Sprint(v)
}

// pyStr is str() of a decoded JSON value, as a secret value is stored.
func pyStr(v any) string {
	if s, ok := v.(string); ok {
		return s
	}
	return PyRepr(v)
}
