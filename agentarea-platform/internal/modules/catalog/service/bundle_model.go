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
	currencyRe         = regexp.MustCompile(`^[A-Z]{3}$`)
	approverRefRe      = regexp.MustCompile(`^(user:[^\s:#]+|[^\s@]+@[^\s@]+\.[^\s@]+)$`)
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
	RenamedFrom   *string
	// Existing names a connection the workspace already has, by Name: the
	// deploy links it and never creates, updates or deletes it.
	Existing bool
}

// BundleOpenAPI is an OpenAPI connection the bundle creates: its spec at
// SpecURL or inline in Spec, and its headers, query parameters and URL
// variables, whose secret values are ${secret.<name>} or ${setup.<key>}.
type BundleOpenAPI struct {
	Key, Name, Description, BaseURL string
	SpecURL                         *string
	Spec                            *wirejson.Object
	Headers, Query, Variables       StrPairs
	RenamedFrom                     *string
	// Existing names a connection the workspace already has, by Name: the
	// deploy links it and never creates, updates or deletes it.
	Existing bool
}

// BundleTask is a saved task the bundle creates: a run of Agent asked Prompt.
type BundleTask struct {
	Key, Name, Agent, Prompt string
	Parameters               wirejson.Object
	RenamedFrom              *string
}

// BundleProject is a project grouping the bundle's agents, MCP servers and
// skills, each by key.
type BundleProject struct {
	Key, Name, Description string
	Instructions           *string
	Agents, MCPs, Skills   []string
	RenamedFrom            *string
}

// BundleSkill is a skill the bundle creates.
type BundleSkill struct {
	Key, Name, SourceType string
	Content               *string
	Files                 *StrPairs
	SourceURL             *string
	RenamedFrom           *string
}

// BundleToolset is a code toolset of an agent, the image and video models it
// generates with and the models it calls, each named as an agent's model is.
type BundleToolset struct {
	Name                   string
	ImageModel, VideoModel *string
	Models                 []BundleToolsetModel
}

// BundleToolsetModel is a model a toolset calls, named as an agent's model
// is, and the reasoning and output budget it calls it with by default.
type BundleToolsetModel struct {
	Name                          string
	ReasoningEffort               *string
	ReasoningMaxTokens, MaxTokens *int64
}

// BundleAgent is an agent the bundle creates.
type BundleAgent struct {
	Key, Name, Description, Instruction string
	Model                               *string
	MCPs, Skills                        []string
	Toolsets                            []BundleToolset
	// Delegates are the keys of the bundle's agents this one may hand work to.
	Delegates []string
	// OpenAPI are the keys of the bundle's OpenAPI connections the agent calls.
	OpenAPI            []string
	ReasoningEffort    *string
	ReasoningMaxTokens *int64
	Client             *string
	// RenamedFrom is the key an earlier install knew this object by.
	RenamedFrom *string
}

// BundleAutomation is a run of one of the bundle's agents: on a cron
// schedule, or on the events of a stream when On is set.
type BundleAutomation struct {
	Key, Type, Cron, Timezone, Agent, Prompt string
	On                                       *BundleTriggerOn
	// Task is the saved task it runs instead of asking Agent Prompt: a task
	// key of the bundle or the name of a workspace's saved task.
	Task        *string
	Parameters  wirejson.Object
	Enabled     bool
	RenamedFrom *string
}

// BundleTriggerOn is the stream an automation runs on: a stream key of the
// bundle or the name of a workspace stream, and the events it takes.
type BundleTriggerOn struct {
	Stream string
	Filter wirejson.Object
}

// BundleStreamSource is a source feeding a bundle stream; its credentials are
// ${secret.<name>} or ${setup.<key>} references, never values.
type BundleStreamSource struct {
	Type, Kind          string
	Config, Credentials StrPairs
}

// BundleStreamWriter is a processor of a bundle stream (Code set) or a
// forward; Outputs are stream keys of the bundle or names of workspace streams.
type BundleStreamWriter struct {
	Code    *string
	Outputs []string
	Filter  wirejson.Object
}

// BundleStream is a stream the bundle creates, with its sources and writers.
type BundleStream struct {
	Key, Name, Description string
	Sources                []BundleStreamSource
	Processors, Forwards   []BundleStreamWriter
	RenamedFrom            *string
}

// BundlePolicy is a governance rule the bundle installs.
type BundlePolicy struct {
	Key, Subject, Target, Effect string
	Params                       wirejson.Object
	Condition                    *string
	Priority                     int64
	Enabled                      bool
	Message                      *string
	// BillingCurrency is the currency Params' amounts are in; the plan blocks
	// when the workspace bills in another.
	BillingCurrency *string
	// Approvers of an approval policy, as written: emails or user:<id>; the
	// deploy resolves them to members of the workspace it writes into.
	Approvers   []string
	RenamedFrom *string
}

// BundleChannel is an inbound channel bound to one of the bundle's agents.
type BundleChannel struct {
	Key, Type, Name, Agent string
	Bindings               StrPairs
	Prompt                 string
	Enabled                bool
	RenamedFrom            *string
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
	Streams       []BundleStream
	OpenAPI       []BundleOpenAPI
	Tasks         []BundleTask
	Projects      []BundleProject
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

// renamedFrom is the renamed_from field: the key an earlier install knew the object by.
func (c *checker) renamedFrom(f fields) *string {
	v, ok := f.get("renamed_from")
	if !ok || v == nil {
		return nil
	}
	s, ok := c.str(v, 1, 0, f.at("renamed_from"))
	if !ok {
		return nil
	}
	if !entityKeyRe.MatchString(s) {
		c.valueError(fmt.Sprintf("renamed_from '%s' must be a key: [a-zA-Z][a-zA-Z0-9_-]*", s), f.at("renamed_from"))
	}
	return &s
}

func withRenamedFrom(o wirejson.Object, from *string) wirejson.Object {
	if from != nil {
		o = append(o, wirejson.Member{Key: "renamed_from", Value: *from})
	}
	return o
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
	out.RenamedFrom = c.renamedFrom(f)
	if v, ok := f.get("existing"); ok {
		out.Existing, _ = c.boolean(v, f.at("existing"))
	}
	c.extra(o, []string{"key", "name", "catalog", "json_spec", "bindings", "context_secret", "renamed_from", "existing"}, loc)
	if c.count() > before {
		return out, false
	}
	if out.Existing {
		if out.Catalog != nil || out.JSONSpec != nil || len(out.Bindings) > 0 || out.ContextSecret != nil { // pragma: allowlist secret
			c.valueError(fmt.Sprintf("mcp '%s' is an existing connection: it takes only its name, not catalog, json_spec, bindings or context_secret", out.Key), loc)
			return out, false
		}
		return out, true
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
	out.RenamedFrom = c.renamedFrom(f)
	c.extra(o, []string{"key", "name", "source_type", "content", "files", "source_url", "renamed_from"}, loc)
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
	return c.tokens(v, "reasoning_max_tokens", loc)
}

// tokens is a positive token budget named key, at most maxReasoningMaxTokens.
func (c *checker) tokens(v any, key string, loc []any) *int64 {
	if v == nil {
		return nil
	}
	n, ok := v.(json.Number)
	if !ok || strings.HasPrefix(string(n), "-") {
		c.valueError(key+" must be a positive integer", loc)
		return nil
	}
	i, err := n.Int64()
	if err != nil || i > maxReasoningMaxTokens {
		c.valueError(fmt.Sprintf("%s must be at most %d", key, maxReasoningMaxTokens), loc)
		return nil
	}
	if i <= 0 {
		c.valueError(key+" must be a positive integer", loc)
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
		MCPs: []string{}, Skills: []string{}, Toolsets: []BundleToolset{}, Delegates: []string{}, OpenAPI: []string{}}
	if out.Key == "workspace" {
		c.valueError("agent key 'workspace' is reserved: a policy subject 'workspace' would mean the whole workspace; name the agent something else",
			f.at("key"))
	}
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
	}{{"mcps", &out.MCPs}, {"skills", &out.Skills}, {"delegates", &out.Delegates}, {"openapi", &out.OpenAPI}} {
		if v, ok := f.get(l.key); ok {
			if got, ok := c.strList(v, f.at(l.key)); ok {
				*l.dst = got
			}
		}
	}
	out.Toolsets = listOf(c, f, "toolsets", bundleToolsetFrom)
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
	out.RenamedFrom = c.renamedFrom(f)
	c.extra(o, []string{"key", "name", "description", "instruction", "model", "mcps", "skills", "toolsets", "delegates", "openapi",
		"reasoning_effort", "reasoning_max_tokens", "client", "renamed_from"}, loc)
	if c.count() > before {
		return out, false
	}
	if out.ReasoningEffort != nil && out.ReasoningMaxTokens != nil {
		c.valueError("set reasoning_effort or reasoning_max_tokens, not both", loc)
		return out, false
	}
	return out, true
}

// bundleToolsetFrom is a toolset's name, or a mapping of its name and settings.
func bundleToolsetFrom(c *checker, v any, loc []any) (BundleToolset, bool) {
	if s, ok := v.(string); ok {
		return BundleToolset{Name: s}, true
	}
	o, ok := v.(wirejson.Object)
	if !ok {
		c.valueError("a toolset is its name, or a mapping of name, image_model, video_model and models", loc)
		return BundleToolset{}, false
	}
	f := fields{o, loc}
	before := c.count()
	out := BundleToolset{Name: c.requiredStr(f, "name", 1, 0)}
	for _, s := range []struct {
		key string
		dst **string
	}{{"image_model", &out.ImageModel}, {"video_model", &out.VideoModel}} {
		if v, ok := f.get(s.key); ok {
			if got, ok := c.optStr(v, 0, f.at(s.key)); ok && got != nil && *got != "" {
				*s.dst = got
			}
		}
	}
	if v, ok := f.get("models"); ok {
		l, isList := v.([]any)
		if !isList {
			c.add(fieldErr("list_type", "Input should be a valid list", f.at("models")))
		} else {
			out.Models = []BundleToolsetModel{}
			for i, x := range l {
				if m, ok := toolsetModelFrom(c, x, f.atList("models", i)); ok {
					out.Models = append(out.Models, m)
				}
			}
		}
	}
	c.extra(o, []string{"name", "image_model", "video_model", "models"}, loc)
	return out, c.count() == before
}

// toolsetModelFrom is a model's name, or a mapping of its name and default budgets.
func toolsetModelFrom(c *checker, v any, loc []any) (BundleToolsetModel, bool) {
	if s, ok := v.(string); ok && s != "" {
		return BundleToolsetModel{Name: s}, true
	}
	o, ok := v.(wirejson.Object)
	if !ok {
		c.valueError("a model is its name, or a mapping of name, reasoning_effort, reasoning_max_tokens and max_tokens", loc)
		return BundleToolsetModel{}, false
	}
	f := fields{o, loc}
	before := c.count()
	out := BundleToolsetModel{Name: c.requiredStr(f, "name", 1, 0)}
	if v, ok := f.get("reasoning_effort"); ok {
		if got, ok := c.optStr(v, 0, f.at("reasoning_effort")); ok && got != nil && *got != "" {
			out.ReasoningEffort = got
		}
	}
	for _, t := range []struct {
		key string
		dst **int64
	}{{"reasoning_max_tokens", &out.ReasoningMaxTokens}, {"max_tokens", &out.MaxTokens}} {
		if v, ok := f.get(t.key); ok {
			*t.dst = c.tokens(v, t.key, f.at(t.key))
		}
	}
	c.extra(o, []string{"name", "reasoning_effort", "reasoning_max_tokens", "max_tokens"}, loc)
	if out.ReasoningEffort != nil && out.ReasoningMaxTokens != nil {
		c.valueError("set reasoning_effort or reasoning_max_tokens, not both", loc)
	}
	return out, c.count() == before
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
	_, hasCron := f.get("cron")
	if hasCron {
		out.Cron = c.requiredStr(f, "cron", 1, 0)
	}
	if v, ok := f.get("timezone"); ok {
		out.Timezone, _ = c.str(v, 0, 0, f.at("timezone"))
	}
	if v, ok := f.get("on"); ok && v != nil {
		out.On = c.triggerOn(v, f.at("on"))
	}
	if v, ok := f.get("task"); ok && v != nil {
		if s, ok := c.str(v, 1, 0, f.at("task")); ok {
			out.Task = &s
		}
	}
	if v, ok := f.get("parameters"); ok && v != nil {
		out.Parameters, _ = c.anyDict(v, f.at("parameters"))
	}
	if out.Task == nil {
		out.Agent = c.requiredStr(f, "agent", 1, 0)
		out.Prompt = c.requiredStr(f, "prompt", 1, 0)
	} else {
		for _, k := range []struct {
			key string
			dst *string
		}{{"agent", &out.Agent}, {"prompt", &out.Prompt}} {
			if v, ok := f.get(k.key); ok && v != nil {
				*k.dst, _ = c.str(v, 0, 0, f.at(k.key))
			}
		}
	}
	if v, ok := f.get("enabled"); ok {
		out.Enabled, _ = c.boolean(v, f.at("enabled"))
	}
	out.RenamedFrom = c.renamedFrom(f)
	c.extra(o, []string{"key", "type", "cron", "timezone", "on", "agent", "prompt", "task", "parameters", "enabled", "renamed_from"}, loc)
	if c.count() > before {
		return out, false
	}
	if out.Task != nil && pyStrip(out.Prompt) != "" {
		c.valueError(fmt.Sprintf("automation '%s' runs task '%s' or is asked prompt, not both", out.Key, *out.Task), loc)
		return out, false
	}
	if out.Task == nil && len(out.Parameters) > 0 {
		c.valueError(fmt.Sprintf("automation '%s': parameters go to a saved task; set task", out.Key), loc)
		return out, false
	}
	if hasCron == (out.On != nil) {
		c.valueError(fmt.Sprintf("automation '%s' needs exactly one of 'cron' or 'on'", out.Key), loc)
		return out, false
	}
	return out, true
}

func (c *checker) triggerOn(v any, loc []any) *BundleTriggerOn {
	o, ok := c.model(v, "BundleTriggerOn", loc)
	if !ok {
		return nil
	}
	f := fields{o, loc}
	out := &BundleTriggerOn{Stream: c.requiredStr(f, "stream", 1, 0), Filter: wirejson.Object{}}
	if v, ok := f.get("filter"); ok && v != nil {
		out.Filter, _ = c.anyDict(v, f.at("filter"))
	}
	c.extra(o, []string{"stream", "filter"}, loc)
	return out
}

func (c *checker) streamWriter(v any, loc []any, processor bool) BundleStreamWriter {
	out := BundleStreamWriter{Outputs: []string{}, Filter: wirejson.Object{}}
	class, known := "BundleStreamForward", []string{"outputs", "filter"}
	if processor {
		class, known = "BundleStreamProcessor", []string{"code", "outputs", "filter"}
	}
	o, ok := c.model(v, class, loc)
	if !ok {
		return out
	}
	f := fields{o, loc}
	if processor {
		code := c.requiredStr(f, "code", 1, 0)
		out.Code = &code
	}
	if v, ok := f.get("outputs"); !ok {
		c.missing(f.at("outputs"))
	} else if l, ok := c.strList(v, f.at("outputs")); ok {
		out.Outputs = l
	}
	if v, ok := f.get("filter"); ok && v != nil {
		out.Filter, _ = c.anyDict(v, f.at("filter"))
	}
	c.extra(o, known, loc)
	return out
}

func (c *checker) streamSource(v any, loc []any) BundleStreamSource {
	out := BundleStreamSource{Kind: "webhook", Config: StrPairs{}, Credentials: StrPairs{}}
	o, ok := c.model(v, "BundleStreamSource", loc)
	if !ok {
		return out
	}
	f := fields{o, loc}
	out.Type = c.requiredStr(f, "type", 1, 0)
	if v, ok := f.get("kind"); ok {
		out.Kind, _ = c.literal(v, "literal_error", []string{"webhook", "poll"}, f.at("kind"))
	}
	for _, d := range []struct {
		key string
		dst *StrPairs
	}{{"config", &out.Config}, {"credentials", &out.Credentials}} {
		if v, ok := f.get(d.key); ok && v != nil {
			if got, ok := c.strDict(v, f.at(d.key)); ok {
				*d.dst = got
			}
		}
	}
	c.extra(o, []string{"type", "kind", "config", "credentials"}, loc)
	return out
}

func bundleOpenAPIFrom(c *checker, v any, loc []any) (BundleOpenAPI, bool) {
	o, ok := c.model(v, "BundleOpenAPI", loc)
	if !ok {
		return BundleOpenAPI{}, false
	}
	f := fields{o, loc}
	before := c.count()
	out := BundleOpenAPI{Key: c.entityKey(f, "openapi"), Name: c.requiredStr(f, "name", 1, BundleMaxNameLength),
		Headers: StrPairs{}, Query: StrPairs{}, Variables: StrPairs{}}
	if v, ok := f.get("description"); ok && v != nil {
		out.Description, _ = c.str(v, 0, 0, f.at("description"))
	}
	if v, ok := f.get("existing"); ok {
		out.Existing, _ = c.boolean(v, f.at("existing"))
	}
	if out.Existing {
		out.RenamedFrom = c.renamedFrom(f)
		c.extra(o, []string{"key", "name", "description", "renamed_from", "existing"}, loc)
		return out, c.count() == before
	}
	out.BaseURL = c.requiredStr(f, "base_url", 1, 0)
	if v, ok := f.get("spec_url"); ok {
		out.SpecURL, _ = c.optStr(v, 0, f.at("spec_url"))
	}
	if v, ok := f.get("spec"); ok && v != nil {
		if d, ok := c.anyDict(v, f.at("spec")); ok {
			out.Spec = &d
		}
	}
	for _, d := range []struct {
		key string
		dst *StrPairs
	}{{"headers", &out.Headers}, {"query", &out.Query}, {"variables", &out.Variables}} {
		if v, ok := f.get(d.key); ok && v != nil {
			if got, ok := c.strDict(v, f.at(d.key)); ok {
				*d.dst = got
			}
		}
	}
	out.RenamedFrom = c.renamedFrom(f)
	c.extra(o, []string{"key", "name", "description", "base_url", "spec_url", "spec", "headers", "query", "variables", "renamed_from", "existing"}, loc)
	if c.count() > before {
		return out, false
	}
	if (out.SpecURL == nil) == (out.Spec == nil) {
		c.valueError(fmt.Sprintf("openapi '%s' needs exactly one of 'spec_url' or 'spec'", out.Key), loc)
		return out, false
	}
	return out, true
}

func bundleTaskFrom(c *checker, v any, loc []any) (BundleTask, bool) {
	o, ok := c.model(v, "BundleTask", loc)
	if !ok {
		return BundleTask{}, false
	}
	f := fields{o, loc}
	before := c.count()
	out := BundleTask{Key: c.entityKey(f, "task"), Name: c.requiredStr(f, "name", 1, BundleMaxNameLength), Parameters: wirejson.Object{}}
	out.Agent = c.requiredStr(f, "agent", 1, 0)
	out.Prompt = c.requiredStr(f, "prompt", 1, 0)
	if v, ok := f.get("parameters"); ok && v != nil {
		out.Parameters, _ = c.anyDict(v, f.at("parameters"))
	}
	out.RenamedFrom = c.renamedFrom(f)
	c.extra(o, []string{"key", "name", "agent", "prompt", "parameters", "renamed_from"}, loc)
	return out, c.count() == before
}

func bundleProjectFrom(c *checker, v any, loc []any) (BundleProject, bool) {
	o, ok := c.model(v, "BundleProject", loc)
	if !ok {
		return BundleProject{}, false
	}
	f := fields{o, loc}
	before := c.count()
	out := BundleProject{Key: c.entityKey(f, "project"), Name: c.requiredStr(f, "name", 1, BundleMaxNameLength),
		Agents: []string{}, MCPs: []string{}, Skills: []string{}}
	if v, ok := f.get("description"); ok && v != nil {
		out.Description, _ = c.str(v, 0, 0, f.at("description"))
	}
	if v, ok := f.get("instructions"); ok {
		out.Instructions, _ = c.optStr(v, 0, f.at("instructions"))
	}
	for _, l := range []struct {
		key string
		dst *[]string
	}{{"agents", &out.Agents}, {"mcp", &out.MCPs}, {"skills", &out.Skills}} {
		if v, ok := f.get(l.key); ok && v != nil {
			if got, ok := c.strList(v, f.at(l.key)); ok {
				*l.dst = got
			}
		}
	}
	out.RenamedFrom = c.renamedFrom(f)
	c.extra(o, []string{"key", "name", "description", "instructions", "agents", "mcp", "skills", "renamed_from"}, loc)
	return out, c.count() == before
}

func bundleStreamFrom(c *checker, v any, loc []any) (BundleStream, bool) {
	o, ok := c.model(v, "BundleStream", loc)
	if !ok {
		return BundleStream{}, false
	}
	f := fields{o, loc}
	before := c.count()
	out := BundleStream{Key: c.entityKey(f, "stream"), Name: c.requiredStr(f, "name", 1, BundleMaxNameLength),
		Sources: []BundleStreamSource{}, Processors: []BundleStreamWriter{}, Forwards: []BundleStreamWriter{}}
	if v, ok := f.get("description"); ok && v != nil {
		out.Description, _ = c.str(v, 0, 0, f.at("description"))
	}
	items := func(key string, each func(any, []any)) {
		v, ok := f.get(key)
		if !ok || v == nil {
			return
		}
		l, ok := v.([]any)
		if !ok {
			c.add(fieldErr("list_type", "Input should be a valid list", f.at(key)))
			return
		}
		for i, x := range l {
			each(x, f.atList(key, i))
		}
	}
	items("sources", func(x any, at []any) { out.Sources = append(out.Sources, c.streamSource(x, at)) })
	items("processors", func(x any, at []any) { out.Processors = append(out.Processors, c.streamWriter(x, at, true)) })
	items("forwards", func(x any, at []any) { out.Forwards = append(out.Forwards, c.streamWriter(x, at, false)) })
	out.RenamedFrom = c.renamedFrom(f)
	c.extra(o, []string{"key", "name", "description", "sources", "processors", "forwards", "renamed_from"}, loc)
	return out, c.count() == before
}

func bundlePolicyFrom(c *checker, v any, loc []any) (BundlePolicy, bool) {
	o, ok := c.model(v, "BundlePolicy", loc)
	if !ok {
		return BundlePolicy{}, false
	}
	f := fields{o, loc}
	before := c.count()
	out := BundlePolicy{Key: c.entityKey(f, "policy"), Params: wirejson.Object{}, Enabled: true}
	out.Subject = c.requiredStr(f, "subject", 1, 0)
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
	if v, ok := f.get("billing_currency"); ok && v != nil {
		if s, ok := c.str(v, 0, 0, f.at("billing_currency")); ok {
			if !currencyRe.MatchString(s) {
				c.valueError("billing_currency must be a three-letter currency code such as RUB", f.at("billing_currency"))
			}
			out.BillingCurrency = &s
		}
	}
	if v, ok := f.get("approvers"); ok && v != nil {
		out.Approvers, _ = c.strList(v, f.at("approvers"))
		for _, a := range out.Approvers {
			if !approverRefRe.MatchString(a) {
				c.valueError(fmt.Sprintf("approver '%s' must be an email or user:<id>", a), f.at("approvers"))
			}
		}
	}
	out.RenamedFrom = c.renamedFrom(f)
	c.extra(o, []string{"key", "subject", "target", "effect", "params", "condition", "priority", "enabled", "message", "billing_currency",
		"approvers", "renamed_from"}, loc)
	if c.count() > before {
		return out, false
	}
	if v, set := out.Params.Get("approvers"); set {
		if l, ok := v.([]any); ok {
			for _, x := range l {
				if s, ok := x.(string); ok && !approverRefRe.MatchString(s) {
					c.valueError(fmt.Sprintf("approver '%s' must be an email or user:<id>", s), join(f.at("params"), "approvers"))
					return out, false
				}
			}
		}
	}
	if len(out.Approvers) > 0 {
		if out.Effect != "approval" {
			c.valueError(fmt.Sprintf("policy '%s': approvers apply only to an approval policy", out.Key), f.at("approvers"))
			return out, false
		}
		if _, set := out.Params.Get("approvers"); set {
			c.valueError(fmt.Sprintf("policy '%s': set approvers or params.approvers, not both", out.Key), f.at("approvers"))
			return out, false
		}
	}
	return out, true
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
	out.RenamedFrom = c.renamedFrom(f)
	c.extra(o, []string{"key", "type", "name", "agent", "bindings", "prompt", "enabled", "renamed_from"}, loc)
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
	out.Policies = policiesOf(c, f, out.Agents)
	out.Streams = listOf(c, f, "streams", bundleStreamFrom)
	out.OpenAPI = listOf(c, f, "openapi", bundleOpenAPIFrom)
	out.Tasks = listOf(c, f, "tasks", bundleTaskFrom)
	out.Projects = listOf(c, f, "projects", bundleProjectFrom)
	c.extra(o, []string{"schema_version", "name", "display_name", "description", "metadata", "setup", "mcps", "skills",
		"agents", "channels", "automations", "policies", "streams", "openapi", "tasks", "projects"}, loc)
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
	out := withRenamedFrom(wirejson.Object{{Key: "key", Value: m.Key}, {Key: "name", Value: m.Name}, {Key: "catalog", Value: optStrValue(m.Catalog)},
		{Key: "json_spec", Value: spec}, {Key: "bindings", Value: m.Bindings.object()},
		{Key: "context_secret", Value: optStrValue(m.ContextSecret)}}, m.RenamedFrom)
	if m.Existing {
		out = append(out, wirejson.Member{Key: "existing", Value: true})
	}
	return out
}

func (s BundleSkill) dump() wirejson.Object {
	var files any
	if s.Files != nil {
		files = s.Files.object()
	}
	return withRenamedFrom(wirejson.Object{{Key: "key", Value: s.Key}, {Key: "name", Value: s.Name}, {Key: "source_type", Value: s.SourceType},
		{Key: "content", Value: optStrValue(s.Content)}, {Key: "files", Value: files}, {Key: "source_url", Value: optStrValue(s.SourceURL)}}, s.RenamedFrom)
}

func (a BundleAgent) dump() wirejson.Object {
	var tokens any
	if a.ReasoningMaxTokens != nil {
		tokens = json.Number(fmt.Sprint(*a.ReasoningMaxTokens))
	}
	out := wirejson.Object{{Key: "key", Value: a.Key}, {Key: "name", Value: a.Name}, {Key: "description", Value: a.Description},
		{Key: "instruction", Value: a.Instruction}, {Key: "model", Value: optStrValue(a.Model)}, {Key: "mcps", Value: strList(a.MCPs)},
		{Key: "skills", Value: strList(a.Skills)}, {Key: "toolsets", Value: toolsetList(a.Toolsets)},
		{Key: "reasoning_effort", Value: optStrValue(a.ReasoningEffort)}, {Key: "reasoning_max_tokens", Value: tokens},
		{Key: "client", Value: optStrValue(a.Client)}}
	if len(a.Delegates) > 0 {
		out = append(out, wirejson.Member{Key: "delegates", Value: strList(a.Delegates)})
	}
	if len(a.OpenAPI) > 0 {
		out = append(out, wirejson.Member{Key: "openapi", Value: strList(a.OpenAPI)})
	}
	return withRenamedFrom(out, a.RenamedFrom)
}

// toolsetList dumps a toolset without settings as its name, and a model
// without budgets as its name, so the fingerprint of an agent that sets
// none stays what it was.
func toolsetList(l []BundleToolset) []any {
	out := make([]any, len(l))
	for i, t := range l {
		if t.ImageModel == nil && t.VideoModel == nil && t.Models == nil {
			out[i] = t.Name
			continue
		}
		o := wirejson.Object{{Key: "name", Value: t.Name}}
		if t.ImageModel != nil {
			o = append(o, wirejson.Member{Key: "image_model", Value: *t.ImageModel})
		}
		if t.VideoModel != nil {
			o = append(o, wirejson.Member{Key: "video_model", Value: *t.VideoModel})
		}
		if t.Models != nil {
			models := make([]any, len(t.Models))
			for j, m := range t.Models {
				models[j] = m.dump()
			}
			o = append(o, wirejson.Member{Key: "models", Value: models})
		}
		out[i] = o
	}
	return out
}

func (m BundleToolsetModel) dump() any {
	if m.ReasoningEffort == nil && m.ReasoningMaxTokens == nil && m.MaxTokens == nil {
		return m.Name
	}
	o := wirejson.Object{{Key: "name", Value: m.Name}}
	if m.ReasoningEffort != nil {
		o = append(o, wirejson.Member{Key: "reasoning_effort", Value: *m.ReasoningEffort})
	}
	for _, t := range []struct {
		key string
		n   *int64
	}{{"reasoning_max_tokens", m.ReasoningMaxTokens}, {"max_tokens", m.MaxTokens}} {
		if t.n != nil {
			o = append(o, wirejson.Member{Key: t.key, Value: json.Number(fmt.Sprint(*t.n))})
		}
	}
	return o
}

func (a BundleAutomation) dump() wirejson.Object {
	out := wirejson.Object{{Key: "key", Value: a.Key}, {Key: "type", Value: a.Type}, {Key: "cron", Value: a.Cron},
		{Key: "timezone", Value: a.Timezone}, {Key: "agent", Value: a.Agent}, {Key: "prompt", Value: a.Prompt}, {Key: "enabled", Value: a.Enabled}}
	if a.On != nil {
		out = append(omit(out, "cron"), wirejson.Member{Key: "on", Value: wirejson.Object{{Key: "stream", Value: a.On.Stream},
			{Key: "filter", Value: nonNilObject(a.On.Filter)}}})
	}
	if a.Task != nil {
		out = append(out, wirejson.Member{Key: "task", Value: *a.Task}, wirejson.Member{Key: "parameters", Value: nonNilObject(a.Parameters)})
	}
	return withRenamedFrom(out, a.RenamedFrom)
}

func (o BundleOpenAPI) dump() wirejson.Object {
	var spec any
	if o.Spec != nil {
		spec = *o.Spec
	}
	out := withRenamedFrom(wirejson.Object{{Key: "key", Value: o.Key}, {Key: "name", Value: o.Name}, {Key: "description", Value: o.Description},
		{Key: "base_url", Value: o.BaseURL}, {Key: "spec_url", Value: optStrValue(o.SpecURL)}, {Key: "spec", Value: spec},
		{Key: "headers", Value: o.Headers.object()}, {Key: "query", Value: o.Query.object()}, {Key: "variables", Value: o.Variables.object()}}, o.RenamedFrom)
	if o.Existing {
		return wirejson.Object{{Key: "key", Value: o.Key}, {Key: "name", Value: o.Name}, {Key: "description", Value: o.Description},
			{Key: "existing", Value: true}}
	}
	return out
}

func (t BundleTask) dump() wirejson.Object {
	return withRenamedFrom(wirejson.Object{{Key: "key", Value: t.Key}, {Key: "name", Value: t.Name}, {Key: "agent", Value: t.Agent},
		{Key: "prompt", Value: t.Prompt}, {Key: "parameters", Value: nonNilObject(t.Parameters)}}, t.RenamedFrom)
}

func (p BundleProject) dump() wirejson.Object {
	return withRenamedFrom(wirejson.Object{{Key: "key", Value: p.Key}, {Key: "name", Value: p.Name}, {Key: "description", Value: p.Description},
		{Key: "instructions", Value: optStrValue(p.Instructions)}, {Key: "agents", Value: strList(p.Agents)}, {Key: "mcp", Value: strList(p.MCPs)},
		{Key: "skills", Value: strList(p.Skills)}}, p.RenamedFrom)
}

func (w BundleStreamWriter) dump() wirejson.Object {
	out := wirejson.Object{{Key: "outputs", Value: strList(w.Outputs)}, {Key: "filter", Value: nonNilObject(w.Filter)}}
	if w.Code != nil {
		out = append(wirejson.Object{{Key: "code", Value: *w.Code}}, out...)
	}
	return out
}

func (s BundleStreamSource) dump() wirejson.Object {
	return wirejson.Object{{Key: "type", Value: s.Type}, {Key: "kind", Value: s.Kind}, {Key: "config", Value: s.Config.object()},
		{Key: "credentials", Value: s.Credentials.object()}}
}

func (s BundleStream) dump() wirejson.Object {
	return withRenamedFrom(wirejson.Object{{Key: "key", Value: s.Key}, {Key: "name", Value: s.Name}, {Key: "description", Value: s.Description},
		{Key: "sources", Value: dumpAll(s.Sources)}, {Key: "processors", Value: dumpAll(s.Processors)},
		{Key: "forwards", Value: dumpAll(s.Forwards)}}, s.RenamedFrom)
}

func (p BundlePolicy) dump() wirejson.Object {
	out := wirejson.Object{{Key: "key", Value: p.Key}, {Key: "subject", Value: p.Subject}, {Key: "target", Value: p.Target},
		{Key: "effect", Value: p.Effect}, {Key: "params", Value: nonNilObject(p.Params)}, {Key: "condition", Value: optStrValue(p.Condition)},
		{Key: "priority", Value: json.Number(fmt.Sprint(p.Priority))}, {Key: "enabled", Value: p.Enabled}, {Key: "message", Value: optStrValue(p.Message)}}
	if p.BillingCurrency != nil {
		out = append(out, wirejson.Member{Key: "billing_currency", Value: *p.BillingCurrency})
	}
	if len(p.Approvers) > 0 {
		out = append(out, wirejson.Member{Key: "approvers", Value: strList(p.Approvers)})
	}
	return withRenamedFrom(out, p.RenamedFrom)
}

func (ch BundleChannel) dump() wirejson.Object {
	return withRenamedFrom(wirejson.Object{{Key: "key", Value: ch.Key}, {Key: "type", Value: ch.Type}, {Key: "name", Value: ch.Name},
		{Key: "agent", Value: ch.Agent}, {Key: "bindings", Value: ch.Bindings.object()}, {Key: "prompt", Value: ch.Prompt}, {Key: "enabled", Value: ch.Enabled}}, ch.RenamedFrom)
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

// Dump is model_dump(mode="json"); a kind the bundle does not use is left
// out, so a bundle without one dumps as before the kind existed.
func (b *Bundle) Dump() wirejson.Object {
	out := wirejson.Object{{Key: "schema_version", Value: b.SchemaVersion}, {Key: "name", Value: b.Name},
		{Key: "display_name", Value: optStrValue(b.DisplayName)}, {Key: "description", Value: b.Description},
		{Key: "metadata", Value: b.Metadata.dump()}, {Key: "setup", Value: dumpAll(b.Setup)}, {Key: "mcps", Value: dumpAll(b.MCPs)},
		{Key: "skills", Value: dumpAll(b.Skills)}, {Key: "agents", Value: dumpAll(b.Agents)}, {Key: "channels", Value: dumpAll(b.Channels)},
		{Key: "automations", Value: dumpAll(b.Automations)}, {Key: "policies", Value: dumpAll(b.Policies)}}
	if len(b.Streams) > 0 {
		out = append(out, wirejson.Member{Key: "streams", Value: dumpAll(b.Streams)})
	}
	if len(b.OpenAPI) > 0 {
		out = append(out, wirejson.Member{Key: "openapi", Value: dumpAll(b.OpenAPI)})
	}
	if len(b.Tasks) > 0 {
		out = append(out, wirejson.Member{Key: "tasks", Value: dumpAll(b.Tasks)})
	}
	if len(b.Projects) > 0 {
		out = append(out, wirejson.Member{Key: "projects", Value: dumpAll(b.Projects)})
	}
	return out
}
