package domain

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"regexp"
	"sort"
	"strings"
)

// GenericWebhook is the slug of the entry for a provider the catalog has no entry for.
const GenericWebhook = "generic_webhook"

// GapKind is the kind of the event a source's gap becomes.
const GapKind = "source.gap"

// ErrSourceRefused is a source request the entry cannot take (422).
var ErrSourceRefused = errors.New("source refused")

// Refused is an ErrSourceRefused with Python's message.
func Refused(msg string) error { return Fail(ErrSourceRefused, msg) }

func strict(b []byte, v any) error {
	dec := json.NewDecoder(bytes.NewReader(b))
	dec.DisallowUnknownFields()
	dec.UseNumber()
	if err := dec.Decode(v); err != nil {
		return &ValidationError{Msg: err.Error()}
	}
	return nil
}

func oneOf(field, v string, allowed ...string) error {
	for _, a := range allowed {
		if v == a {
			return nil
		}
	}
	quoted := make([]string, len(allowed))
	for i, a := range allowed {
		quoted[i] = "'" + a + "'"
	}
	list := strings.Join(quoted[:len(quoted)-1], ", ") + " or " + quoted[len(quoted)-1]
	if len(quoted) == 1 {
		list = quoted[0]
	}
	return &ValidationError{Msg: fmt.Sprintf("%s: Input should be %s", field, list)}
}

// SourceField is a credential or setting a member fills in for a source of this type.
type SourceField struct {
	Key         string `json:"key"`
	Label       string `json:"label"`
	Placeholder string `json:"placeholder"`
	Required    bool   `json:"required"`
	// Issued: the platform generates the value when the member leaves it empty.
	Issued bool `json:"issued"`
	// Format is token, or whsec (whsec_<base64>).
	Format string `json:"format"`
}

// UnmarshalJSON applies SourceField's defaults and refuses extra keys.
func (f *SourceField) UnmarshalJSON(b []byte) error {
	type plain SourceField
	p := plain{Required: true, Format: "token"}
	if err := strict(b, &p); err != nil {
		return err
	}
	*f = SourceField(p)
	return oneOf("format", f.Format, "token", "whsec")
}

// Verification is how a webhook request proves it came from the provider.
type Verification struct {
	Scheme          string              `json:"scheme"`
	Secret          *string             `json:"secret"`
	Header          *string             `json:"header"`
	Algorithm       string              `json:"algorithm"`
	Encoding        string              `json:"encoding"`
	Prefix          string              `json:"prefix"`
	TimestampHeader *string             `json:"timestamp_header"`
	IDHeader        *string             `json:"id_header"`
	Payload         string              `json:"payload"`
	SignatureFormat string              `json:"signature_format"`
	TimestampKey    string              `json:"timestamp_key"`
	SignatureKey    string              `json:"signature_key"`
	SecretFormat    string              `json:"secret_format"`
	ToleranceSecs   int                 `json:"tolerance_seconds"`
	Request         map[string]any      `json:"request"`
	CollectionFrom  *string             `json:"collection_from"`
	Collections     map[string]string   `json:"collections"`
	Expect          map[string]string   `json:"expect"`
	Later           map[string][]string `json:"later"`
	Record          map[string]string   `json:"record"`
	Configurable    []string            `json:"configurable"`
	RequiredHeaders []string            `json:"required_headers"`
}

func defaultVerification() Verification {
	return Verification{
		Algorithm: "sha256", Encoding: "hex", Payload: "{body}", SignatureFormat: "plain",
		TimestampKey: "t", SignatureKey: "v1", SecretFormat: "raw", ToleranceSecs: 300,
	}
}

// UnmarshalJSON applies Verification's defaults and refuses extra keys.
func (v *Verification) UnmarshalJSON(b []byte) error {
	type plain Verification
	p := plain(defaultVerification())
	if err := strict(b, &p); err != nil {
		return err
	}
	*v = Verification(p)
	return v.validate()
}

func (v Verification) validate() error {
	checks := []error{
		oneOf("scheme", v.Scheme, "hmac", "hmac_timestamped", "ed25519", "shared_token", "api_lookup", "none"),
		oneOf("algorithm", v.Algorithm, "sha1", "sha256", "sha384", "sha512"),
		oneOf("encoding", v.Encoding, "hex", "base64"),
		oneOf("signature_format", v.SignatureFormat, "plain", "kv", "list"),
		oneOf("secret_format", v.SecretFormat, "raw", "whsec"),
	}
	return errors.Join(checks...)
}

// Handshake is a request the provider sends to check the endpoint, answered without recording it.
type Handshake struct {
	When    string         `json:"when"`
	Equals  string         `json:"equals"`
	Respond map[string]any `json:"respond"`
}

// UnmarshalJSON refuses extra keys.
func (h *Handshake) UnmarshalJSON(b []byte) error {
	type plain Handshake
	var p plain
	if err := strict(b, &p); err != nil {
		return err
	}
	*h = Handshake(p)
	return nil
}

// Request is an HTTP request described by templates.
type Request struct {
	Method  string            `json:"method"`
	URL     string            `json:"url"`
	Headers map[string]string `json:"headers"`
	JSON    any               `json:"json"`
}

// UnmarshalJSON applies Request's defaults and refuses extra keys.
func (r *Request) UnmarshalJSON(b []byte) error {
	type plain Request
	p := plain{Method: "GET"}
	if err := strict(b, &p); err != nil {
		return err
	}
	if p.Headers == nil {
		p.Headers = map[string]string{}
	}
	*r = Request(p)
	return nil
}

// Registration is how the reconciler points the provider at the webhook URL: two templated
// requests, or a transport of its own (mcp_events).
type Registration struct {
	Register   *Request `json:"register"`
	Unregister *Request `json:"unregister"`
	Transport  *string  `json:"transport"`
}

// UnmarshalJSON refuses extra keys and a registration that is not one way.
func (r *Registration) UnmarshalJSON(b []byte) error {
	type plain Registration
	var p plain
	if err := strict(b, &p); err != nil {
		return err
	}
	*r = Registration(p)
	if r.Transport != nil {
		if err := oneOf("transport", *r.Transport, "mcp_events"); err != nil {
			return err
		}
	}
	if (r.Register == nil) == (r.Transport == nil) {
		return &ValidationError{Msg: "a registration has either a register request or a transport"}
	}
	if r.Transport != nil && r.Unregister != nil {
		return &ValidationError{Msg: "a registration transport unregisters by its own protocol"}
	}
	return nil
}

// Signal is a request that reports on the source itself: gap or ended.
type Signal struct {
	When   string `json:"when"`
	Equals string `json:"equals"`
	Signal string `json:"signal"`
	Key    string `json:"key"`
	Reason string `json:"reason"`
}

// UnmarshalJSON refuses extra keys and unknown signals.
func (s *Signal) UnmarshalJSON(b []byte) error {
	type plain Signal
	var p plain
	if err := strict(b, &p); err != nil {
		return err
	}
	*s = Signal(p)
	return oneOf("signal", s.Signal, "gap", "ended")
}

// Poll is how the event poller fetches a poll source's events.
type Poll struct {
	Transport string            `json:"transport"`
	Request   *Request          `json:"request"`
	Items     *string           `json:"items"`
	Cursor    *string           `json:"cursor"`
	Interval  string            `json:"interval"`
	IMAP      map[string]string `json:"imap"`
}

// UnmarshalJSON applies Poll's defaults and refuses extra keys.
func (p *Poll) UnmarshalJSON(b []byte) error {
	type plain Poll
	v := plain{Interval: "60s"}
	if err := strict(b, &v); err != nil {
		return err
	}
	*p = Poll(v)
	return oneOf("transport", p.Transport, "http_json", "feed", "imap", "mcp_events")
}

// Attachments is where an event's files are and how they are got.
type Attachments struct {
	Path  string `json:"path"`
	Fetch string `json:"fetch"`
}

// UnmarshalJSON applies the inline default and refuses extra keys.
func (a *Attachments) UnmarshalJSON(b []byte) error {
	type plain Attachments
	p := plain{Fetch: "inline"}
	if err := strict(b, &p); err != nil {
		return err
	}
	*a = Attachments(p)
	return nil
}

// EventTemplates is how an event of a type is named and keyed.
type EventTemplates struct {
	Kind          Template     `json:"kind"`
	Key           Template     `json:"key"`
	SessionKey    Template     `json:"session_key"`
	Sender        Template     `json:"sender"`
	Summary       Template     `json:"summary"`
	OccurredAt    Template     `json:"occurred_at"`
	Depth         Template     `json:"depth"`
	CorrelationID Template     `json:"correlation_id"`
	CausationID   Template     `json:"causation_id"`
	Attachments   *Attachments `json:"attachments"`
}

// UnmarshalJSON refuses extra keys and an entry with no kind.
func (e *EventTemplates) UnmarshalJSON(b []byte) error {
	type plain EventTemplates
	var p plain
	if err := strict(b, &p); err != nil {
		return err
	}
	if p.Kind == nil {
		return &ValidationError{Msg: "event.kind: Field required"}
	}
	*e = EventTemplates(p)
	return nil
}

// EventOverrides is what one source may set in place of its entry's templates.
type EventOverrides struct {
	Kind       Template `json:"kind,omitempty"`
	Key        Template `json:"key,omitempty"`
	SessionKey Template `json:"session_key,omitempty"`
	Summary    Template `json:"summary,omitempty"`
}

// ParseEventOverrides is EventOverrides.model_validate over a stored or sent object.
func ParseEventOverrides(m map[string]any) (EventOverrides, error) {
	var o EventOverrides
	if m == nil {
		return o, nil
	}
	b, err := json.Marshal(m)
	if err != nil {
		return o, &ValidationError{Msg: err.Error()}
	}
	type plain EventOverrides
	var p plain
	if err := strict(b, &p); err != nil {
		return o, &ValidationError{Msg: "event_templates: " + err.Error()}
	}
	return EventOverrides(p), nil
}

// Dump is model_dump(exclude_none=True).
func (o EventOverrides) Dump() map[string]any {
	out := map[string]any{}
	for k, t := range map[string]Template{"kind": o.Kind, "key": o.Key, "session_key": o.SessionKey, "summary": o.Summary} {
		if t == nil {
			continue
		}
		if len(t) == 1 {
			out[k] = t[0]
			continue
		}
		list := make([]any, len(t))
		for i, s := range t {
			list[i] = s
		}
		out[k] = list
	}
	return out
}

// Admission is who may reach an agent through a source: senders linked to a platform user.
// Username, FirstName and LastName are how the provider names the sender, kept when they link.
type Admission struct {
	Identity     string   `json:"identity"`
	ExternalID   Template `json:"external_id"`
	Chat         Template `json:"chat"`
	Text         Template `json:"text"`
	Private      Template `json:"private"`
	PrivateValue string   `json:"private_value"`
	IsBot        Template `json:"is_bot"`
	Username     Template `json:"username,omitempty"`
	FirstName    Template `json:"first_name,omitempty"`
	LastName     Template `json:"last_name,omitempty"`
}

// UnmarshalJSON applies Admission's defaults and refuses extra keys.
func (a *Admission) UnmarshalJSON(b []byte) error {
	type plain Admission
	p := plain{PrivateValue: "private"}
	if err := strict(b, &p); err != nil {
		return err
	}
	*a = Admission(p)
	return nil
}

// Reply is how a task started by an event of the type answers where the event came from.
type Reply struct {
	Sender          string            `json:"sender"`
	Target          map[string]string `json:"target"`
	Presentation    string            `json:"presentation"`
	Request         *Request          `json:"request"`
	Markup          string            `json:"markup"`
	Limit           *int              `json:"limit"`
	PermanentErrors []string          `json:"permanent_errors"`
}

// UnmarshalJSON applies Reply's defaults and refuses extra keys.
func (r *Reply) UnmarshalJSON(b []byte) error {
	type plain Reply
	p := plain{Presentation: "concise", Markup: "plain", Target: map[string]string{}, PermanentErrors: []string{}}
	if err := strict(b, &p); err != nil {
		return err
	}
	*r = Reply(p)
	return errors.Join(
		oneOf("sender", r.Sender, "http", "telegram_live", "smtp"),
		oneOf("presentation", r.Presentation, "concise", "summary", "silent"),
		oneOf("markup", r.Markup, "slack", "discord", "telegram", "plain"),
	)
}

// SourceTypeEntry is one provider as the catalog describes it.
type SourceTypeEntry struct {
	Slug         string         `json:"slug"`
	Name         string         `json:"name"`
	Description  string         `json:"description"`
	Icon         string         `json:"icon"`
	Delivery     string         `json:"delivery"`
	Credentials  []SourceField  `json:"credentials"`
	Config       []SourceField  `json:"config"`
	Verification *Verification  `json:"verification"`
	Handshake    []Handshake    `json:"handshake"`
	Signals      []Signal       `json:"signals"`
	Registration *Registration  `json:"registration"`
	Poll         *Poll          `json:"poll"`
	Event        EventTemplates `json:"event"`
	Events       []string       `json:"events"`
	Admission    *Admission     `json:"admission"`
	Reply        *Reply         `json:"reply"`
}

var slugRE = regexp.MustCompile(`^[a-z][a-z0-9_]*$`)

// ParseSourceTypeEntry is SourceTypeEntry.model_validate over a catalog spec.
func ParseSourceTypeEntry(raw json.RawMessage) (SourceTypeEntry, error) {
	type plain SourceTypeEntry
	p := plain{Icon: "webhook"}
	var probe map[string]json.RawMessage
	if err := json.Unmarshal(raw, &probe); err != nil {
		return SourceTypeEntry{}, &ValidationError{Msg: err.Error()}
	}
	for _, k := range []string{"slug", "name", "delivery", "event"} {
		if _, ok := probe[k]; !ok {
			return SourceTypeEntry{}, &ValidationError{Msg: k + ": Field required"}
		}
	}
	if err := strict(raw, &p); err != nil {
		return SourceTypeEntry{}, err
	}
	e := SourceTypeEntry(p)
	if !slugRE.MatchString(e.Slug) {
		return e, &ValidationError{Msg: "slug: String should match pattern '^[a-z][a-z0-9_]*$'"}
	}
	if err := oneOf("delivery", e.Delivery, "webhook", "poll", "both", "platform"); err != nil {
		return e, err
	}
	for _, s := range []*[]SourceField{&e.Credentials, &e.Config} {
		if *s == nil {
			*s = []SourceField{}
		}
	}
	if e.Events == nil {
		e.Events = []string{}
	}
	return e, nil
}

// Accepts is whether a source of kind (webhook / poll) can be of this type.
func (e SourceTypeEntry) Accepts(kind string) bool {
	return e.Delivery == "both" || e.Delivery == kind
}

// ContinuesSessions is whether a trigger on the type joins a session's next event by default.
func (e SourceTypeEntry) ContinuesSessions() bool { return e.Event.SessionKey != nil }

// SpeaksMCPEvents is whether the type polls or registers through MCP Events.
func (e SourceTypeEntry) SpeaksMCPEvents() bool {
	return (e.Poll != nil && e.Poll.Transport == "mcp_events") ||
		(e.Registration != nil && e.Registration.Transport != nil && *e.Registration.Transport == "mcp_events")
}

// EntriesByName is list_entries: the first valid entry per slug, sorted by lowercased name.
func EntriesByName(entries []SourceTypeEntry) []SourceTypeEntry {
	seen := map[string]bool{}
	out := make([]SourceTypeEntry, 0, len(entries))
	for _, e := range entries {
		if seen[e.Slug] {
			continue
		}
		seen[e.Slug] = true
		out = append(out, e)
	}
	sort.SliceStable(out, func(i, j int) bool { return strings.ToLower(out[i].Name) < strings.ToLower(out[j].Name) })
	return out
}

// Sender choices.
const (
	SendersOwner   = "owner"
	SendersMembers = "members"
	SendersIDs     = "ids"
)

// ParseSenders is Senders.model_validate: allow owner|members|ids; ids deduplicated and stripped,
// at most 100, numeric, and only with allow ids.
func ParseSenders(v any) (Senders, error) {
	m, ok := v.(map[string]any)
	if !ok {
		return Senders{}, Invalid("senders: Input should be a valid dictionary")
	}
	for k := range m {
		if k != "allow" && k != "ids" {
			return Senders{}, Invalid("senders." + k + ": Extra inputs are not permitted")
		}
	}
	allow, _ := m["allow"].(string)
	if err := oneOf("senders.allow", allow, SendersOwner, SendersMembers, SendersIDs); err != nil {
		return Senders{}, Invalid(err.Error())
	}
	s := Senders{Allow: allow, IDs: []string{}}
	if raw, has := m["ids"]; has && raw != nil {
		list, ok := raw.([]any)
		if !ok {
			if ss, isStrs := raw.([]string); isStrs {
				for _, x := range ss {
					list = append(list, x)
				}
			} else {
				return Senders{}, Invalid("senders.ids: Input should be a valid tuple")
			}
		}
		seen := map[string]bool{}
		for _, item := range list {
			text, ok := Scalar(item)
			if !ok {
				return Senders{}, Invalid("senders.ids: Input should be a valid string")
			}
			text = strings.TrimSpace(text)
			if !seen[text] {
				seen[text] = true
				s.IDs = append(s.IDs, text)
			}
		}
	}
	return s, s.check()
}

func (s Senders) check() error {
	if len(s.IDs) > 100 {
		return Invalid("senders.ids: Tuple should have at most 100 items")
	}
	if s.Allow != SendersIDs {
		if len(s.IDs) > 0 {
			return Invalid(fmt.Sprintf("senders: Value error, ids name senders only when allow is 'ids', not %s", PyRepr(s.Allow)))
		}
		return nil
	}
	if len(s.IDs) == 0 {
		return Invalid("senders: Value error, allow 'ids' needs at least one id")
	}
	var bad []string
	for _, id := range s.IDs {
		if !isDigits(id) {
			bad = append(bad, PyRepr(id))
		}
	}
	if len(bad) > 0 {
		return Invalid(fmt.Sprintf("senders: Value error, ids are numeric account ids, not [%s]", strings.Join(bad, ", ")))
	}
	return nil
}

// SendersRecordOf is a stored senders object read back: the choice and who made it; false when
// nothing is stored or it is not a valid record.
func SendersRecordOf(m map[string]any) (Senders, bool) {
	if len(m) == 0 {
		return Senders{}, false
	}
	by, _ := m["by"].(string)
	if by == "" {
		return Senders{}, false
	}
	choice := map[string]any{"allow": m["allow"], "ids": m["ids"]}
	s, err := ParseSenders(choice)
	if err != nil {
		return Senders{}, false
	}
	s.By = &by
	return s, true
}

// SendersToStore is senders_to_store: on a type that admits senders, the choice (owner when none)
// and who made it; nil otherwise.
func SendersToStore(admits bool, chosen *Senders, by string) map[string]any {
	if !admits {
		return nil
	}
	choice := Senders{Allow: SendersOwner}
	if chosen != nil {
		choice = *chosen
	}
	ids := make([]any, len(choice.IDs))
	for i, id := range choice.IDs {
		ids[i] = id
	}
	return map[string]any{"allow": choice.Allow, "ids": ids, "by": by}
}
