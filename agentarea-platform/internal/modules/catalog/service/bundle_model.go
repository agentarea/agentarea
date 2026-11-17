package service

import (
	"encoding/json"
	"fmt"
	"regexp"
	"strconv"
	"strings"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx/wirejson"
)

// BundleSchemaVersion is the canonical bundle format a deploy reads.
const BundleSchemaVersion = "0.1.0"

// BundleMaxNameLength is the String(255) the created entities' names land in.
const BundleMaxNameLength = 255

const maxReasoningMaxTokens = 1<<31 - 1

var (
	setupPlaceholderRe = regexp.MustCompile(`\$\{setup\.([a-zA-Z0-9_]+)\}`)
	secretRefRe        = regexp.MustCompile(`^\$\{secret\.([a-zA-Z0-9_-]+)\}$`)
	setupKeyRe         = regexp.MustCompile(`^[a-zA-Z][a-zA-Z0-9_]*$`)
	entityKeyRe        = regexp.MustCompile(`^[a-zA-Z][a-zA-Z0-9_-]*$`)
	effortShapeRe      = regexp.MustCompile(`^[a-z][a-z_-]{0,15}$`)
)

// Setup field types (SetupFieldType).
const (
	SetupSecret  = "secret"
	SetupString  = "string"
	SetupNumber  = "number"
	SetupBoolean = "boolean"
	SetupSelect  = "select"
)

// StrPair is one entry of a dict[str, str], kept in the order it was written.
type StrPair struct{ Key, Value string }

// StrPairs is a dict[str, str] in insertion order.
type StrPairs []StrPair

// Get is the value under key.
func (p StrPairs) Get(key string) (string, bool) {
	for _, e := range p {
		if e.Key == key {
			return e.Value, true
		}
	}
	return "", false
}

func (p StrPairs) object() wirejson.Object {
	out := make(wirejson.Object, 0, len(p))
	for _, e := range p {
		out = append(out, wirejson.Member{Key: e.Key, Value: e.Value})
	}
	return out
}

// SetupField is a value the user provides before the bundle runs.
type SetupField struct {
	Key, Label, Type string
	Required         bool
	Help             *string
	Default          any
	Options          *[]string
	Min, Max         *float64
}

// BundleMCP is an MCP server the bundle connects: a catalog server, or its own spec.
type BundleMCP struct {
	Key, Name     string
	Catalog       *string
	JSONSpec      *wirejson.Object
	Bindings      StrPairs
	ContextSecret *string
}

// BundleSkill is a skill the bundle creates.
type BundleSkill struct {
	Key, Name, SourceType string
	Content               *string
	Files                 *StrPairs
	SourceURL             *string
}

// BundleAgent is an agent the bundle creates.
type BundleAgent struct {
	Key, Name, Description, Instruction string
	Model                               *string
	MCPs, Skills, Toolsets              []string
	ReasoningEffort                     *string
	ReasoningMaxTokens                  *int64
	Client                              *string
}

// BundleAutomation is a scheduled run of one of the bundle's agents.
type BundleAutomation struct {
	Key, Type, Cron, Timezone, Agent, Prompt string
	Enabled                                  bool
}

// BundlePolicy is a governance rule the bundle installs.
type BundlePolicy struct {
	Key, Subject, Target, Effect string
	Params                       wirejson.Object
	Condition                    *string
	Priority                     int64
	Enabled                      bool
	Message                      *string
}

// BundleChannel is an inbound channel bound to one of the bundle's agents.
type BundleChannel struct {
	Key, Type, Name, Agent string
	Bindings               StrPairs
	Prompt                 string
	Enabled                bool
}

// BundleMetadata is marketplace presentation metadata.
type BundleMetadata struct {
	Developer, Category                 *string
	Capabilities                        []string
	Icon, Website, PrivacyURL, TermsURL *string
}

// Bundle is the canonical, fully inlined bundle (schema 0.1.0).
type Bundle struct {
	SchemaVersion string
	Name          string
	DisplayName   *string
	Description   string
	Metadata      BundleMetadata
	Setup         []SetupField
	MCPs          []BundleMCP
	Skills        []BundleSkill
	Agents        []BundleAgent
	Channels      []BundleChannel
	Automations   []BundleAutomation
	Policies      []BundlePolicy
}

// SetupField is the field declared under key.
func (b *Bundle) SetupField(key string) (SetupField, bool) {
	for _, f := range b.Setup {
		if f.Key == key {
			return f, true
		}
	}
	return SetupField{}, false
}

// setupRefs is setup_refs: the setup keys a string references, in order.
func setupRefs(v *string) []string {
	if v == nil {
		return nil
	}
	return setupRefsOf(*v)
}

func setupRefsOf(s string) []string {
	var out []string
	for _, m := range setupPlaceholderRe.FindAllStringSubmatch(s, -1) {
		out = append(out, m[1])
	}
	return out
}

// secretBinding is secret_binding: the secret a whole ${secret.<name>} value names.
func secretBinding(v string) (string, bool) {
	m := secretRefRe.FindStringSubmatch(pyStrip(v))
	if m == nil {
		return "", false
	}
	return m[1], true
}

func mentionsSecret(v string) bool { return strings.Contains(v, "${secret.") }

// resolvePlaceholders substitutes ${setup.<key>} with the values set; the rest stay.
func resolvePlaceholders(s string, values wirejson.Object) string {
	return setupPlaceholderRe.ReplaceAllStringFunc(s, func(m string) string {
		key := setupPlaceholderRe.FindStringSubmatch(m)[1]
		if v, ok := values.Get(key); ok && v != nil {
			return pyStr(v)
		}
		return m
	})
}

// pyStrip is str.strip() over ASCII and Unicode whitespace.
func pyStrip(s string) string { return strings.TrimSpace(s) }

// --- validation -------------------------------------------------------------

func fieldErr(typ, msg string, loc []any) httpx.FieldError {
	return httpx.FieldError{Type: typ, Msg: msg, Loc: loc}
}

// checker collects pydantic's errors for one model tree.
type checker struct{ errs []httpx.FieldError }

func (c *checker) add(e httpx.FieldError) { c.errs = append(c.errs, e) }

func (c *checker) count() int { return len(c.errs) }

func join(loc []any, more ...any) []any {
	out := make([]any, 0, len(loc)+len(more))
	return append(append(out, loc...), more...)
}

func (c *checker) missing(loc []any) {
	c.add(fieldErr("missing", "Field required", loc))
}

func (c *checker) valueError(msg string, loc []any) {
	c.add(httpx.FieldError{Type: "value_error", Msg: "Value error, " + msg, Loc: loc, Ctx: wirejson.Object{{Key: "error", Value: wirejson.Object{}}}})
}

// model is a nested model's input: a mapping, else model_type.
func (c *checker) model(v any, class string, loc []any) (wirejson.Object, bool) {
	if o, ok := v.(wirejson.Object); ok {
		return o, true
	}
	c.add(httpx.FieldError{Type: "model_type", Msg: "Input should be a valid dictionary or instance of " + class, Loc: loc,
		Ctx: wirejson.Object{{Key: "class_name", Value: class}}})
	return nil, false
}

func (c *checker) extra(o wirejson.Object, known []string, loc []any) {
	for _, m := range o {
		found := false
		for _, k := range known {
			if k == m.Key {
				found = true
				break
			}
		}
		if !found {
			c.add(fieldErr("extra_forbidden", "Extra inputs are not permitted", join(loc, m.Key)))
		}
	}
}

func plural(n int) string {
	if n == 1 {
		return ""
	}
	return "s"
}

// str is a str field with length bounds (0 is none).
func (c *checker) str(v any, minLen, maxLen int, loc []any) (string, bool) {
	s, ok := v.(string)
	if !ok {
		c.add(fieldErr("string_type", "Input should be a valid string", loc))
		return "", false
	}
	n := len([]rune(s))
	if minLen > 0 && n < minLen {
		c.add(httpx.FieldError{Type: "string_too_short", Msg: fmt.Sprintf("String should have at least %d character%s", minLen, plural(minLen)),
			Loc: loc, Ctx: wirejson.Object{{Key: "min_length", Value: minLen}}})
		return "", false
	}
	if maxLen > 0 && n > maxLen {
		c.add(httpx.FieldError{Type: "string_too_long", Msg: fmt.Sprintf("String should have at most %d character%s", maxLen, plural(maxLen)),
			Loc: loc, Ctx: wirejson.Object{{Key: "max_length", Value: maxLen}}})
		return "", false
	}
	return s, true
}

func (c *checker) optStr(v any, maxLen int, loc []any) (*string, bool) {
	if v == nil {
		return nil, true
	}
	s, ok := c.str(v, 0, maxLen, loc)
	if !ok {
		return nil, false
	}
	return &s, true
}

func boolWord(s string) (value, ok bool) {
	value, ok = map[string]bool{"0": false, "off": false, "f": false, "false": false, "n": false, "no": false,
		"1": true, "on": true, "t": true, "true": true, "y": true, "yes": true}[s]
	return value, ok
}

// boolean is a bool field in pydantic's lax mode.
func (c *checker) boolean(v any, loc []any) (bool, bool) {
	switch x := v.(type) {
	case bool:
		return x, true
	case json.Number:
		switch string(x) {
		case "0":
			return false, true
		case "1":
			return true, true
		}
		c.add(fieldErr("bool_parsing", "Input should be a valid boolean, unable to interpret input", loc))
		return false, false
	case wirejson.Float:
		switch float64(x) {
		case 0:
			return false, true
		case 1:
			return true, true
		}
		c.add(fieldErr("bool_parsing", "Input should be a valid boolean, unable to interpret input", loc))
		return false, false
	case string:
		if b, ok := boolWord(strings.ToLower(x)); ok {
			return b, true
		}
		c.add(fieldErr("bool_parsing", "Input should be a valid boolean, unable to interpret input", loc))
		return false, false
	}
	c.add(fieldErr("bool_type", "Input should be a valid boolean", loc))
	return false, false
}

// integer is an int field in pydantic's lax mode, with bounds.
func (c *checker) integer(v any, ge, le int64, loc []any) (int64, bool) {
	var n int64
	switch x := v.(type) {
	case bool:
		if x {
			n = 1
		}
	case json.Number:
		i, err := x.Int64()
		if err != nil {
			c.add(fieldErr("int_parsing", "Input should be a valid integer, unable to parse string as an integer", loc))
			return 0, false
		}
		n = i
	case wirejson.Float:
		f := float64(x)
		if f != float64(int64(f)) {
			c.add(fieldErr("int_from_float", "Input should be a valid integer, got a number with a fractional part", loc))
			return 0, false
		}
		n = int64(f)
	case string:
		i, err := strconv.ParseInt(strings.ReplaceAll(strings.TrimSpace(x), "_", ""), 10, 64)
		if err != nil {
			c.add(fieldErr("int_parsing", "Input should be a valid integer, unable to parse string as an integer", loc))
			return 0, false
		}
		n = i
	default:
		c.add(fieldErr("int_type", "Input should be a valid integer", loc))
		return 0, false
	}
	if n < ge {
		c.add(httpx.FieldError{Type: "greater_than_equal", Msg: fmt.Sprintf("Input should be greater than or equal to %d", ge), Loc: loc,
			Ctx: wirejson.Object{{Key: "ge", Value: ge}}})
		return 0, false
	}
	if n > le {
		c.add(httpx.FieldError{Type: "less_than_equal", Msg: fmt.Sprintf("Input should be less than or equal to %d", le), Loc: loc,
			Ctx: wirejson.Object{{Key: "le", Value: le}}})
		return 0, false
	}
	return n, true
}

// optFloat is a float | None field in pydantic's lax mode.
func (c *checker) optFloat(v any, loc []any) (*float64, bool) {
	var f float64
	switch x := v.(type) {
	case nil:
		return nil, true
	case bool:
		if x {
			f = 1
		}
	case json.Number:
		g, err := x.Float64()
		if err != nil {
			c.add(fieldErr("float_parsing", "Input should be a valid number, unable to parse string as a number", loc))
			return nil, false
		}
		f = g
	case wirejson.Float:
		f = float64(x)
	case string:
		g, err := strconv.ParseFloat(strings.TrimSpace(x), 64)
		if err != nil {
			c.add(fieldErr("float_parsing", "Input should be a valid number, unable to parse string as a number", loc))
			return nil, false
		}
		f = g
	default:
		c.add(fieldErr("float_type", "Input should be a valid number", loc))
		return nil, false
	}
	return &f, true
}

func (c *checker) strList(v any, loc []any) ([]string, bool) {
	l, ok := v.([]any)
	if !ok {
		c.add(fieldErr("list_type", "Input should be a valid list", loc))
		return nil, false
	}
	out := make([]string, 0, len(l))
	valid := true
	for i, item := range l {
		s, ok := c.str(item, 0, 0, join(loc, i))
		valid = valid && ok
		out = append(out, s)
	}
	return out, valid
}

func (c *checker) strDict(v any, loc []any) (StrPairs, bool) {
	o, ok := v.(wirejson.Object)
	if !ok {
		c.add(fieldErr("dict_type", "Input should be a valid dictionary", loc))
		return nil, false
	}
	out := make(StrPairs, 0, len(o))
	valid := true
	for _, m := range o {
		s, ok := c.str(m.Value, 0, 0, join(loc, m.Key))
		valid = valid && ok
		out = append(out, StrPair{Key: m.Key, Value: s})
	}
	return out, valid
}

func (c *checker) anyDict(v any, loc []any) (wirejson.Object, bool) {
	o, ok := v.(wirejson.Object)
	if !ok {
		c.add(fieldErr("dict_type", "Input should be a valid dictionary", loc))
		return nil, false
	}
	return o, true
}

func expectedChoices(choices []string) string {
	q := make([]string, len(choices))
	for i, c := range choices {
		q[i] = "'" + c + "'"
	}
	if len(q) == 1 {
		return q[0]
	}
	return strings.Join(q[:len(q)-1], ", ") + " or " + q[len(q)-1]
}

func (c *checker) literal(v any, typ string, choices []string, loc []any) (string, bool) {
	if s, ok := v.(string); ok {
		for _, ch := range choices {
			if s == ch {
				return s, true
			}
		}
	}
	e := expectedChoices(choices)
	c.add(httpx.FieldError{Type: typ, Msg: "Input should be " + e, Loc: loc, Ctx: wirejson.Object{{Key: "expected", Value: e}}})
	return "", false
}

// fields reads a model's fields in declaration order.
type fields struct {
	o   wirejson.Object
	loc []any
}

func (f fields) get(key string) (any, bool) { return f.o.Get(key) }

func (f fields) at(key string) []any { return join(f.loc, key) }

func setupFieldFrom(c *checker, v any, loc []any) (SetupField, bool) {
	o, ok := c.model(v, "SetupField", loc)
	if !ok {
		return SetupField{}, false
	}
	f := fields{o, loc}
	before := c.count()
	out := SetupField{Type: SetupString}
	if v, ok := f.get("key"); !ok {
		c.missing(f.at("key"))
	} else if s, ok := c.str(v, 1, 0, f.at("key")); ok {
		if !setupKeyRe.MatchString(s) {
			c.valueError(fmt.Sprintf("setup key '%s' must match [a-zA-Z][a-zA-Z0-9_]*", s), f.at("key"))
		}
		out.Key = s
	}
	if v, ok := f.get("label"); !ok {
		c.missing(f.at("label"))
	} else {
		out.Label, _ = c.str(v, 1, 0, f.at("label"))
	}
	if v, ok := f.get("type"); ok {
		out.Type, _ = c.literal(v, "enum", []string{SetupSecret, SetupString, SetupNumber, SetupBoolean, SetupSelect}, f.at("type"))
	}
	if v, ok := f.get("required"); ok {
		out.Required, _ = c.boolean(v, f.at("required"))
	}
	if v, ok := f.get("help"); ok {
		out.Help, _ = c.optStr(v, 0, f.at("help"))
	}
	if v, ok := f.get("default"); ok {
		out.Default = v
	}
	if v, ok := f.get("options"); ok && v != nil {
		if l, ok := c.strList(v, f.at("options")); ok {
			out.Options = &l
		}
	}
	if v, ok := f.get("min"); ok {
		out.Min, _ = c.optFloat(v, f.at("min"))
	}
	if v, ok := f.get("max"); ok {
		out.Max, _ = c.optFloat(v, f.at("max"))
	}
	c.extra(o, []string{"key", "label", "type", "required", "help", "default", "options", "min", "max"}, loc)
	if c.count() > before {
		return out, false
	}
	if out.Type == SetupSelect && (out.Options == nil || len(*out.Options) == 0) {
		c.valueError(fmt.Sprintf("setup field '%s' is a select but has no options", out.Key), loc)
		return out, false
	}
	return out, true
}

func (c *checker) entityKey(f fields, label string) string {
	v, ok := f.get("key")
	if !ok {
		c.missing(f.at("key"))
		return ""
	}
	s, ok := c.str(v, 1, 0, f.at("key"))
	if ok && !entityKeyRe.MatchString(s) {
		c.valueError(fmt.Sprintf("%s key '%s' must match [a-zA-Z][a-zA-Z0-9_-]*", label, s), f.at("key"))
	}
	return s
}

func (c *checker) requiredStr(f fields, key string, minLen, maxLen int) string {
	v, ok := f.get(key)
	if !ok {
		c.missing(f.at(key))
		return ""
	}
	s, _ := c.str(v, minLen, maxLen, f.at(key))
	return s
}

func bundleMCPFrom(c *checker, v any, loc []any) (BundleMCP, bool) {
	o, ok := c.model(v, "BundleMcp", loc)
	if !ok {
		return BundleMCP{}, false
	}
	f := fields{o, loc}
	before := c.count()
	out := BundleMCP{Key: c.entityKey(f, "mcp"), Name: c.requiredStr(f, "name", 1, BundleMaxNameLength)}
	if v, ok := f.get("catalog"); ok {
		out.Catalog, _ = c.optStr(v, BundleMaxNameLength, f.at("catalog"))
	}
	if v, ok := f.get("json_spec"); ok && v != nil {
		if d, ok := c.anyDict(v, f.at("json_spec")); ok {
			out.JSONSpec = &d
		}
	}
	if v, ok := f.get("bindings"); ok {
		out.Bindings, _ = c.strDict(v, f.at("bindings"))
	}
	if v, ok := f.get("context_secret"); ok {
		if s, ok := c.optStr(v, 0, f.at("context_secret")); ok && s != nil {
			stripped := pyStrip(*s)
			if loc := setupPlaceholderRe.FindStringIndex(stripped); loc == nil || loc[0] != 0 || loc[1] != len(stripped) {
				c.valueError("context_secret must be a single ${setup.<key>} reference to a secret setup field, never the secret itself", f.at("context_secret"))
			}
			out.ContextSecret = &stripped
		}
	}
	c.extra(o, []string{"key", "name", "catalog", "json_spec", "bindings", "context_secret"}, loc)
	if c.count() > before {
		return out, false
	}
	if (out.Catalog == nil) == (out.JSONSpec == nil) {
		c.valueError(fmt.Sprintf("mcp '%s' needs exactly one of 'catalog' or 'json_spec'", out.Key), loc)
		return out, false
	}
	return out, true
}

func bundleSkillFrom(c *checker, v any, loc []any) (BundleSkill, bool) {
	o, ok := c.model(v, "BundleSkill", loc)
	if !ok {
		return BundleSkill{}, false
	}
	f := fields{o, loc}
	before := c.count()
	out := BundleSkill{Key: c.entityKey(f, "skill"), Name: c.requiredStr(f, "name", 1, BundleMaxNameLength), SourceType: "content"}
	if v, ok := f.get("source_type"); ok {
		out.SourceType, _ = c.literal(v, "literal_error", []string{"content", "files", "github"}, f.at("source_type"))
	}
	if v, ok := f.get("content"); ok {
		out.Content, _ = c.optStr(v, 0, f.at("content"))
	}
	if v, ok := f.get("files"); ok && v != nil {
		if d, ok := c.strDict(v, f.at("files")); ok {
			out.Files = &d
		}
	}
	if v, ok := f.get("source_url"); ok {
		out.SourceURL, _ = c.optStr(v, 0, f.at("source_url"))
	}
	c.extra(o, []string{"key", "name", "source_type", "content", "files", "source_url"}, loc)
	if c.count() > before {
		return out, false
	}
	switch {
	case out.SourceType == "content" && (out.Content == nil || *out.Content == ""):
		c.valueError(fmt.Sprintf("skill '%s' is source_type=content but has no content", out.Key), loc)
	case out.SourceType == "files" && (out.Files == nil || len(*out.Files) == 0):
		c.valueError(fmt.Sprintf("skill '%s' is source_type=files but has no files", out.Key), loc)
	case out.SourceType == "github" && (out.SourceURL == nil || *out.SourceURL == ""):
		c.valueError(fmt.Sprintf("skill '%s' is source_type=github but has no source_url", out.Key), loc)
	default:
		return out, true
	}
	return out, false
}

// reasoningEffort is checked_reasoning_effort, a before-validator.
func (c *checker) reasoningEffort(v any, loc []any) *string {
	if v == nil || v == "" {
		return nil
	}
	s, ok := v.(string)
	if !ok || !effortShapeRe.MatchString(s) {
		c.valueError("reasoning_effort must be a level name such as low or high", loc)
		return nil
	}
	return &s
}

// reasoningMaxTokens is checked_reasoning_max_tokens, a before-validator.
func (c *checker) reasoningMaxTokens(v any, loc []any) *int64 {
	if v == nil {
		return nil
	}
	n, ok := v.(json.Number)
	if !ok || strings.HasPrefix(string(n), "-") {
		c.valueError("reasoning_max_tokens must be a positive integer", loc)
		return nil
	}
	i, err := n.Int64()
	if err != nil || i > maxReasoningMaxTokens {
		c.valueError(fmt.Sprintf("reasoning_max_tokens must be at most %d", maxReasoningMaxTokens), loc)
		return nil
	}
	if i <= 0 {
		c.valueError("reasoning_max_tokens must be a positive integer", loc)
		return nil
	}
	return &i
}

func bundleAgentFrom(c *checker, v any, loc []any) (BundleAgent, bool) {
	o, ok := c.model(v, "BundleAgent", loc)
	if !ok {
		return BundleAgent{}, false
	}
	f := fields{o, loc}
	before := c.count()
	out := BundleAgent{Key: c.entityKey(f, "agent"), Name: c.requiredStr(f, "name", 1, BundleMaxNameLength),
		MCPs: []string{}, Skills: []string{}, Toolsets: []string{}}
	if v, ok := f.get("description"); ok {
		out.Description, _ = c.str(v, 0, 1000, f.at("description"))
	}
	if v, ok := f.get("instruction"); ok {
		out.Instruction, _ = c.str(v, 0, 20000, f.at("instruction"))
	}
	if v, ok := f.get("model"); ok {
		out.Model, _ = c.optStr(v, 0, f.at("model"))
	}
	for _, l := range []struct {
		key string
		dst *[]string
	}{{"mcps", &out.MCPs}, {"skills", &out.Skills}, {"toolsets", &out.Toolsets}} {
		if v, ok := f.get(l.key); ok {
			if got, ok := c.strList(v, f.at(l.key)); ok {
				*l.dst = got
			}
		}
	}
	if v, ok := f.get("reasoning_effort"); ok {
		out.ReasoningEffort = c.reasoningEffort(v, f.at("reasoning_effort"))
	}
	if v, ok := f.get("reasoning_max_tokens"); ok {
		out.ReasoningMaxTokens = c.reasoningMaxTokens(v, f.at("reasoning_max_tokens"))
	}
	if v, ok := f.get("client"); ok {
		if s, ok := c.optStr(v, 0, f.at("client")); ok && s != nil {
			if len(setupRefsOf(*s)) > 0 {
				out.Client = s
			} else if u, err := uuid.Parse(*s); err == nil {
				id := u.String()
				out.Client = &id
			} else {
				c.valueError("client must be the id of a Codex or Claude Code client, or a ${setup.x} reference to one", f.at("client"))
			}
		}
	}
	c.extra(o, []string{"key", "name", "description", "instruction", "model", "mcps", "skills", "toolsets",
		"reasoning_effort", "reasoning_max_tokens", "client"}, loc)
	if c.count() > before {
		return out, false
	}
	if out.ReasoningEffort != nil && out.ReasoningMaxTokens != nil {
		c.valueError("set reasoning_effort or reasoning_max_tokens, not both", loc)
		return out, false
	}
	return out, true
}

func bundleAutomationFrom(c *checker, v any, loc []any) (BundleAutomation, bool) {
	o, ok := c.model(v, "BundleAutomation", loc)
	if !ok {
		return BundleAutomation{}, false
	}
	f := fields{o, loc}
	before := c.count()
	out := BundleAutomation{Key: c.entityKey(f, "automation"), Type: "cron", Timezone: "UTC"}
	if v, ok := f.get("type"); ok {
		out.Type, _ = c.literal(v, "literal_error", []string{"cron"}, f.at("type"))
	}
	out.Cron = c.requiredStr(f, "cron", 1, 0)
	if v, ok := f.get("timezone"); ok {
		out.Timezone, _ = c.str(v, 0, 0, f.at("timezone"))
	}
	out.Agent = c.requiredStr(f, "agent", 1, 0)
	out.Prompt = c.requiredStr(f, "prompt", 1, 0)
	if v, ok := f.get("enabled"); ok {
		out.Enabled, _ = c.boolean(v, f.at("enabled"))
	}
	c.extra(o, []string{"key", "type", "cron", "timezone", "agent", "prompt", "enabled"}, loc)
	return out, c.count() == before
}

func bundlePolicyFrom(c *checker, v any, loc []any) (BundlePolicy, bool) {
	o, ok := c.model(v, "BundlePolicy", loc)
	if !ok {
		return BundlePolicy{}, false
	}
	f := fields{o, loc}
	before := c.count()
	out := BundlePolicy{Key: c.entityKey(f, "policy"), Subject: "workspace", Params: wirejson.Object{}, Enabled: true}
	if v, ok := f.get("subject"); ok {
		out.Subject, _ = c.str(v, 0, 0, f.at("subject"))
	}
	out.Target = c.requiredStr(f, "target", 1, 0)
	if v, ok := f.get("effect"); !ok {
		c.missing(f.at("effect"))
	} else {
		out.Effect, _ = c.literal(v, "literal_error", []string{"allow", "deny", "cap", "approval", "safety"}, f.at("effect"))
	}
	if v, ok := f.get("params"); ok {
		if d, ok := c.anyDict(v, f.at("params")); ok {
			out.Params = d
		}
	}
	if v, ok := f.get("condition"); ok {
		out.Condition, _ = c.optStr(v, 0, f.at("condition"))
	}
	if v, ok := f.get("priority"); ok {
		out.Priority, _ = c.integer(v, -(1 << 31), 1<<31-1, f.at("priority"))
	}
	if v, ok := f.get("enabled"); ok {
		out.Enabled, _ = c.boolean(v, f.at("enabled"))
	}
	if v, ok := f.get("message"); ok {
		out.Message, _ = c.optStr(v, 0, f.at("message"))
	}
	c.extra(o, []string{"key", "subject", "target", "effect", "params", "condition", "priority", "enabled", "message"}, loc)
	return out, c.count() == before
}

const defaultChannelPrompt = "Handle the incoming message: {{ message_text }}"

func bundleChannelFrom(c *checker, v any, loc []any) (BundleChannel, bool) {
	o, ok := c.model(v, "BundleChannel", loc)
	if !ok {
		return BundleChannel{}, false
	}
	f := fields{o, loc}
	before := c.count()
	out := BundleChannel{Key: c.entityKey(f, "channel"), Type: "telegram", Bindings: StrPairs{}, Prompt: defaultChannelPrompt}
	if v, ok := f.get("type"); ok {
		out.Type, _ = c.literal(v, "literal_error", []string{"telegram", "generic"}, f.at("type"))
	}
	out.Name = c.requiredStr(f, "name", 1, 0)
	out.Agent = c.requiredStr(f, "agent", 1, 0)
	if v, ok := f.get("bindings"); ok {
		out.Bindings, _ = c.strDict(v, f.at("bindings"))
	}
	if v, ok := f.get("prompt"); ok {
		out.Prompt, _ = c.str(v, 1, 0, f.at("prompt"))
	}
	if v, ok := f.get("enabled"); ok {
		out.Enabled, _ = c.boolean(v, f.at("enabled"))
	}
	c.extra(o, []string{"key", "type", "name", "agent", "bindings", "prompt", "enabled"}, loc)
	return out, c.count() == before
}

func bundleMetadataFrom(c *checker, v any, loc []any) BundleMetadata {
	out := BundleMetadata{Capabilities: []string{}}
	o, ok := c.model(v, "BundleMetadata", loc)
	if !ok {
		return out
	}
	f := fields{o, loc}
	for _, s := range []struct {
		key string
		dst **string
	}{{"developer", &out.Developer}, {"category", &out.Category}} {
		if v, ok := f.get(s.key); ok {
			*s.dst, _ = c.optStr(v, 0, f.at(s.key))
		}
	}
	if v, ok := f.get("capabilities"); ok {
		if l, ok := c.strList(v, f.at("capabilities")); ok {
			out.Capabilities = l
		}
	}
	for _, s := range []struct {
		key string
		dst **string
	}{{"icon", &out.Icon}, {"website", &out.Website}, {"privacy_url", &out.PrivacyURL}, {"terms_url", &out.TermsURL}} {
		if v, ok := f.get(s.key); ok {
			*s.dst, _ = c.optStr(v, 0, f.at(s.key))
		}
	}
	c.extra(o, []string{"developer", "category", "capabilities", "icon", "website", "privacy_url", "terms_url"}, loc)
	return out
}

func listOf[T any](c *checker, f fields, key string, item func(*checker, any, []any) (T, bool)) []T {
	out := []T{}
	v, ok := f.get(key)
	if !ok {
		return out
	}
	l, ok := v.([]any)
	if !ok {
		c.add(fieldErr("list_type", "Input should be a valid list", f.at(key)))
		return out
	}
	for i, x := range l {
		got, _ := item(c, x, f.atList(key, i))
		out = append(out, got)
	}
	return out
}

func (f fields) atList(key string, i int) []any { return join(f.loc, key, i) }

// bundleFrom validates v as a Bundle at loc.
func bundleFrom(c *checker, v any, loc []any) (Bundle, bool) {
	o, ok := c.model(v, "Bundle", loc)
	if !ok {
		return Bundle{}, false
	}
	f := fields{o, loc}
	before := c.count()
	out := Bundle{SchemaVersion: BundleSchemaVersion}
	if v, ok := f.get("schema_version"); ok {
		if s, ok := c.str(v, 0, 0, f.at("schema_version")); ok {
			if s != BundleSchemaVersion {
				c.valueError(fmt.Sprintf("unsupported schema_version '%s'; expected '%s'", s, BundleSchemaVersion), f.at("schema_version"))
			}
			out.SchemaVersion = s
		}
	}
	out.Name = c.requiredStr(f, "name", 1, BundleMaxNameLength)
	if v, ok := f.get("display_name"); ok {
		out.DisplayName, _ = c.optStr(v, BundleMaxNameLength, f.at("display_name"))
	}
	if v, ok := f.get("description"); ok {
		out.Description, _ = c.str(v, 0, 0, f.at("description"))
	}
	out.Metadata = BundleMetadata{Capabilities: []string{}}
	if v, ok := f.get("metadata"); ok {
		out.Metadata = bundleMetadataFrom(c, v, f.at("metadata"))
	}
	out.Setup = listOf(c, f, "setup", setupFieldFrom)
	out.MCPs = listOf(c, f, "mcps", bundleMCPFrom)
	out.Skills = listOf(c, f, "skills", bundleSkillFrom)
	out.Agents = listOf(c, f, "agents", bundleAgentFrom)
	out.Channels = listOf(c, f, "channels", bundleChannelFrom)
	out.Automations = listOf(c, f, "automations", bundleAutomationFrom)
	out.Policies = listOf(c, f, "policies", bundlePolicyFrom)
	c.extra(o, []string{"schema_version", "name", "display_name", "description", "metadata", "setup", "mcps", "skills",
		"agents", "channels", "automations", "policies"}, loc)
	return out, c.count() == before
}

// --- dumps (model_dump(mode="json")) ----------------------------------------

func optStrValue(s *string) any {
	if s == nil {
		return nil
	}
	return *s
}

func optFloatValue(f *float64) any {
	if f == nil {
		return nil
	}
	return wirejson.Float(*f)
}

func strList(l []string) []any {
	out := make([]any, len(l))
	for i, s := range l {
		out[i] = s
	}
	return out
}

func (f SetupField) dump() wirejson.Object {
	var options any
	if f.Options != nil {
		options = strList(*f.Options)
	}
	return wirejson.Object{{Key: "key", Value: f.Key}, {Key: "label", Value: f.Label}, {Key: "type", Value: f.Type},
		{Key: "required", Value: f.Required}, {Key: "help", Value: optStrValue(f.Help)}, {Key: "default", Value: f.Default},
		{Key: "options", Value: options}, {Key: "min", Value: optFloatValue(f.Min)}, {Key: "max", Value: optFloatValue(f.Max)}}
}

func (m BundleMCP) dump() wirejson.Object {
	var spec any
	if m.JSONSpec != nil {
		spec = *m.JSONSpec
	}
	return wirejson.Object{{Key: "key", Value: m.Key}, {Key: "name", Value: m.Name}, {Key: "catalog", Value: optStrValue(m.Catalog)},
		{Key: "json_spec", Value: spec}, {Key: "bindings", Value: m.Bindings.object()},
		{Key: "context_secret", Value: optStrValue(m.ContextSecret)}}
}

func (s BundleSkill) dump() wirejson.Object {
	var files any
	if s.Files != nil {
		files = s.Files.object()
	}
	return wirejson.Object{{Key: "key", Value: s.Key}, {Key: "name", Value: s.Name}, {Key: "source_type", Value: s.SourceType},
		{Key: "content", Value: optStrValue(s.Content)}, {Key: "files", Value: files}, {Key: "source_url", Value: optStrValue(s.SourceURL)}}
}

func (a BundleAgent) dump() wirejson.Object {
	var tokens any
	if a.ReasoningMaxTokens != nil {
		tokens = json.Number(fmt.Sprint(*a.ReasoningMaxTokens))
	}
	return wirejson.Object{{Key: "key", Value: a.Key}, {Key: "name", Value: a.Name}, {Key: "description", Value: a.Description},
		{Key: "instruction", Value: a.Instruction}, {Key: "model", Value: optStrValue(a.Model)}, {Key: "mcps", Value: strList(a.MCPs)},
		{Key: "skills", Value: strList(a.Skills)}, {Key: "toolsets", Value: strList(a.Toolsets)},
		{Key: "reasoning_effort", Value: optStrValue(a.ReasoningEffort)}, {Key: "reasoning_max_tokens", Value: tokens},
		{Key: "client", Value: optStrValue(a.Client)}}
}

func (a BundleAutomation) dump() wirejson.Object {
	return wirejson.Object{{Key: "key", Value: a.Key}, {Key: "type", Value: a.Type}, {Key: "cron", Value: a.Cron},
		{Key: "timezone", Value: a.Timezone}, {Key: "agent", Value: a.Agent}, {Key: "prompt", Value: a.Prompt}, {Key: "enabled", Value: a.Enabled}}
}

func (p BundlePolicy) dump() wirejson.Object {
	return wirejson.Object{{Key: "key", Value: p.Key}, {Key: "subject", Value: p.Subject}, {Key: "target", Value: p.Target},
		{Key: "effect", Value: p.Effect}, {Key: "params", Value: nonNilObject(p.Params)}, {Key: "condition", Value: optStrValue(p.Condition)},
		{Key: "priority", Value: json.Number(fmt.Sprint(p.Priority))}, {Key: "enabled", Value: p.Enabled}, {Key: "message", Value: optStrValue(p.Message)}}
}

func (ch BundleChannel) dump() wirejson.Object {
	return wirejson.Object{{Key: "key", Value: ch.Key}, {Key: "type", Value: ch.Type}, {Key: "name", Value: ch.Name},
		{Key: "agent", Value: ch.Agent}, {Key: "bindings", Value: ch.Bindings.object()}, {Key: "prompt", Value: ch.Prompt}, {Key: "enabled", Value: ch.Enabled}}
}

func (m BundleMetadata) dump() wirejson.Object {
	caps := m.Capabilities
	if caps == nil {
		caps = []string{}
	}
	return wirejson.Object{{Key: "developer", Value: optStrValue(m.Developer)}, {Key: "category", Value: optStrValue(m.Category)},
		{Key: "capabilities", Value: strList(caps)}, {Key: "icon", Value: optStrValue(m.Icon)}, {Key: "website", Value: optStrValue(m.Website)},
		{Key: "privacy_url", Value: optStrValue(m.PrivacyURL)}, {Key: "terms_url", Value: optStrValue(m.TermsURL)}}
}

func nonNilObject(o wirejson.Object) wirejson.Object {
	if o == nil {
		return wirejson.Object{}
	}
	return o
}

func dumpAll[T interface{ dump() wirejson.Object }](items []T) []any {
	out := make([]any, len(items))
	for i, x := range items {
		out[i] = x.dump()
	}
	return out
}

// Dump is model_dump(mode="json").
func (b *Bundle) Dump() wirejson.Object {
	return wirejson.Object{{Key: "schema_version", Value: b.SchemaVersion}, {Key: "name", Value: b.Name},
		{Key: "display_name", Value: optStrValue(b.DisplayName)}, {Key: "description", Value: b.Description},
		{Key: "metadata", Value: b.Metadata.dump()}, {Key: "setup", Value: dumpAll(b.Setup)}, {Key: "mcps", Value: dumpAll(b.MCPs)},
		{Key: "skills", Value: dumpAll(b.Skills)}, {Key: "agents", Value: dumpAll(b.Agents)}, {Key: "channels", Value: dumpAll(b.Channels)},
		{Key: "automations", Value: dumpAll(b.Automations)}, {Key: "policies", Value: dumpAll(b.Policies)}}
}
