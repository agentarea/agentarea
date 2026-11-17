package service

import (
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx/wirejson"
)

// EntityKind is a kind of workspace entity a bundle declares.
type EntityKind string

const (
	KindMCP        EntityKind = "mcp"
	KindSkill      EntityKind = "skill"
	KindAgent      EntityKind = "agent"
	KindChannel    EntityKind = "channel"
	KindAutomation EntityKind = "automation"
	KindPolicy     EntityKind = "policy"
)

func entityKinds() []EntityKind {
	return []EntityKind{KindMCP, KindSkill, KindAgent, KindChannel, KindAutomation, KindPolicy}
}

// EntityStatus is what a deploy plan does with one entity.
type EntityStatus string

const (
	StatusWillCreate        EntityStatus = "will_create"
	StatusWillUpdate        EntityStatus = "will_update"
	StatusUnchanged         EntityStatus = "unchanged"
	StatusOrphaned          EntityStatus = "orphaned"
	StatusChangesNotApplied EntityStatus = "changes_not_applied"
	StatusAlreadyExists     EntityStatus = "already_exists"
	StatusUnsupported       EntityStatus = "unsupported"
)

// Severity is how a preview issue bears on the install.
type Severity string

const (
	SeverityBlock Severity = "block"
	SeverityWarn  Severity = "warn"
)

// InstallAction is what an install did with one entity.
type InstallAction string

const (
	ActionCreated   InstallAction = "created"
	ActionUpdated   InstallAction = "updated"
	ActionUnchanged InstallAction = "unchanged"
	ActionOrphaned  InstallAction = "orphaned"
	ActionReused    InstallAction = "reused"
	ActionSkipped   InstallAction = "skipped"
)

// PreviewEntity is one thing the package will, or will not, create.
type PreviewEntity struct {
	Kind   EntityKind
	Key    string
	Name   string
	Status EntityStatus
	Detail *string
}

// PreviewIssue is a problem found analyzing the package.
type PreviewIssue struct {
	Severity  Severity
	Message   string
	EntityKey *string
}

// ImportPreview is what the deploy wizard renders before the install.
type ImportPreview struct {
	Bundle      Bundle
	Setup       []SetupField
	Entities    []PreviewEntity
	Issues      []PreviewIssue
	Installable bool
	PlanDigest  *string
}

// Blocks are the issues that stop the install.
func (p ImportPreview) Blocks() []PreviewIssue { return blocks(p.Issues) }

func blocks(issues []PreviewIssue) []PreviewIssue {
	var out []PreviewIssue
	for _, i := range issues {
		if i.Severity == SeverityBlock {
			out = append(out, i)
		}
	}
	return out
}

// InstalledEntity is one entity an install created, changed, linked or skipped.
type InstalledEntity struct {
	Kind        EntityKind
	Key         string
	Name        string
	Action      InstallAction
	ID          *string
	Detail      *string
	Fingerprint *string
}

// InstallResult is what an install did.
type InstallResult struct {
	BundleName        string
	InstalledBundleID *string
	Entities          []InstalledEntity
	SetupValues       wirejson.Object
}

func blockIssue(key, msg string) PreviewIssue {
	return PreviewIssue{Severity: SeverityBlock, Message: msg, EntityKey: strp(key)}
}

func warnIssue(key, msg string) PreviewIssue {
	return PreviewIssue{Severity: SeverityWarn, Message: msg, EntityKey: strp(key)}
}

// Dump is model_dump(mode="json").
func (e PreviewEntity) Dump() wirejson.Object {
	return wirejson.Object{{Key: "kind", Value: string(e.Kind)}, {Key: "key", Value: e.Key}, {Key: "name", Value: e.Name},
		{Key: "status", Value: string(e.Status)}, {Key: "detail", Value: optStrValue(e.Detail)}}
}

// Dump is model_dump(mode="json").
func (i PreviewIssue) Dump() wirejson.Object {
	return wirejson.Object{{Key: "severity", Value: string(i.Severity)}, {Key: "message", Value: i.Message},
		{Key: "entity_key", Value: optStrValue(i.EntityKey)}}
}

// Dump is model_dump(mode="json").
func (p ImportPreview) Dump() wirejson.Object {
	entities := make([]any, len(p.Entities))
	for i, e := range p.Entities {
		entities[i] = e.Dump()
	}
	return wirejson.Object{{Key: "bundle", Value: p.Bundle.Dump()}, {Key: "setup", Value: dumpAll(p.Setup)},
		{Key: "entities", Value: entities}, {Key: "issues", Value: IssueDumps(p.Issues)},
		{Key: "installable", Value: p.Installable}, {Key: "plan_digest", Value: optStrValue(p.PlanDigest)}}
}

// IssueDumps is the issues as the API returns them.
func IssueDumps(issues []PreviewIssue) []any {
	out := make([]any, len(issues))
	for i, x := range issues {
		out[i] = x.Dump()
	}
	return out
}

// Dump is model_dump(mode="json").
func (e InstalledEntity) Dump() wirejson.Object {
	return wirejson.Object{{Key: "kind", Value: string(e.Kind)}, {Key: "key", Value: e.Key}, {Key: "name", Value: e.Name},
		{Key: "action", Value: string(e.Action)}, {Key: "id", Value: optStrValue(e.ID)}, {Key: "detail", Value: optStrValue(e.Detail)},
		{Key: "fingerprint", Value: optStrValue(e.Fingerprint)}}
}

// Dump is model_dump(mode="json").
func (r InstallResult) Dump() wirejson.Object {
	entities := make([]any, len(r.Entities))
	for i, e := range r.Entities {
		entities[i] = e.Dump()
	}
	return wirejson.Object{{Key: "bundle_name", Value: r.BundleName}, {Key: "installed_bundle_id", Value: optStrValue(r.InstalledBundleID)},
		{Key: "entities", Value: entities}, {Key: "setup_values", Value: nonNilObject(r.SetupValues)}}
}

func installedEntityFrom(c *checker, v any, loc []any) (InstalledEntity, bool) {
	o, ok := c.model(v, "InstalledEntity", loc)
	if !ok {
		return InstalledEntity{}, false
	}
	f := fields{o, loc}
	before := c.count()
	var out InstalledEntity
	if v, ok := f.get("kind"); !ok {
		c.missing(f.at("kind"))
	} else {
		k, _ := c.literal(v, "enum", []string{"mcp", "skill", "agent", "channel", "automation", "policy"}, f.at("kind"))
		out.Kind = EntityKind(k)
	}
	out.Key = c.requiredStr(f, "key", 0, 0)
	out.Name = c.requiredStr(f, "name", 0, 0)
	if v, ok := f.get("action"); !ok {
		c.missing(f.at("action"))
	} else {
		a, _ := c.literal(v, "enum", []string{"created", "updated", "unchanged", "orphaned", "reused", "skipped"}, f.at("action"))
		out.Action = InstallAction(a)
	}
	for _, s := range []struct {
		key string
		dst **string
	}{{"id", &out.ID}, {"detail", &out.Detail}, {"fingerprint", &out.Fingerprint}} {
		if v, ok := f.get(s.key); ok {
			*s.dst, _ = c.optStr(v, 0, f.at(s.key))
		}
	}
	c.extra(o, []string{"kind", "key", "name", "action", "id", "detail", "fingerprint"}, loc)
	return out, c.count() == before
}

func installResultFrom(c *checker, v any) (InstallResult, bool) {
	o, ok := c.model(v, "InstallResult", nil)
	if !ok {
		return InstallResult{}, false
	}
	f := fields{o, nil}
	before := c.count()
	out := InstallResult{BundleName: c.requiredStr(f, "bundle_name", 0, 0), SetupValues: wirejson.Object{}}
	if v, ok := f.get("installed_bundle_id"); ok {
		out.InstalledBundleID, _ = c.optStr(v, 0, f.at("installed_bundle_id"))
	}
	out.Entities = listOf(c, f, "entities", installedEntityFrom)
	if v, ok := f.get("setup_values"); ok {
		if d, ok := c.anyDict(v, f.at("setup_values")); ok {
			out.SetupValues = d
		}
	}
	c.extra(o, []string{"bundle_name", "installed_bundle_id", "entities", "setup_values"}, nil)
	return out, c.count() == before
}

// ValidateBundle is Bundle.model_validate at loc, with pydantic's errors.
func ValidateBundle(v any, loc ...any) (Bundle, []httpx.FieldError) {
	var c checker
	b, ok := bundleFrom(&c, v, loc)
	if !ok {
		return Bundle{}, c.errs
	}
	return b, nil
}

// ValidateSetupValues is a dict[str, Any] field at loc.
func ValidateSetupValues(v any, loc ...any) (wirejson.Object, []httpx.FieldError) {
	var c checker
	d, ok := c.anyDict(v, loc)
	if !ok {
		return nil, c.errs
	}
	return d, nil
}
