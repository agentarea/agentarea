package service

import (
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx/wirejson"
)

// AnalyzeRequest is POST /bundles/analyze's body: exactly one source.
type AnalyzeRequest struct {
	Source, SourceURL *string
	Files             StrPairs
	Bundle            *Bundle
	SetupValues       wirejson.Object
	// Target is into (the install to update) and origin (where the folder came from).
	Target BundleTarget
}

// InstallRequest is POST /bundles/install's body.
type InstallRequest struct {
	Bundle      Bundle
	SetupValues wirejson.Object
	PlanDigest  string
	// Target is install_id (the install the plan was made for) and origin.
	Target BundleTarget
}

func (c *checker) origin(f fields) *BundleOrigin {
	v, ok := f.get("origin")
	if !ok || v == nil {
		return nil
	}
	o, ok := c.model(v, "BundleOrigin", f.at("origin"))
	if !ok {
		return nil
	}
	of := fields{o, f.at("origin")}
	out := &BundleOrigin{GitRemote: c.nullableStr(of, "git_remote"), GitCommit: c.nullableStr(of, "git_commit"), Path: c.nullableStr(of, "path")}
	c.extra(o, []string{"git_remote", "git_commit", "path"}, f.at("origin"))
	return out
}

func (c *checker) installRef(f fields, key string) *string {
	s := c.nullableStr(f, key)
	if s != nil && pyStrip(*s) == "" {
		c.add(fieldErr("string_too_short", "String should have at least 1 character", f.at(key)))
		return nil
	}
	return s
}

func (c *checker) nullableStr(f fields, key string) *string {
	v, ok := f.get(key)
	if !ok || v == nil {
		return nil
	}
	s, ok := c.str(v, 0, 0, f.at(key))
	if !ok {
		return nil
	}
	return &s
}

func (c *checker) setupValues(f fields) wirejson.Object {
	v, ok := f.get("setup_values")
	if !ok {
		return wirejson.Object{}
	}
	d, _ := c.anyDict(v, f.at("setup_values"))
	return d
}

// ValidateAnalyzeRequest is AnalyzeRequest.model_validate of the body object.
func ValidateAnalyzeRequest(o wirejson.Object) (AnalyzeRequest, []httpx.FieldError) {
	var c checker
	f := fields{o, []any{"body"}}
	var out AnalyzeRequest
	out.Source = c.nullableStr(f, "source")
	out.SourceURL = c.nullableStr(f, "source_url")
	if v, ok := f.get("files"); ok && v != nil {
		out.Files, _ = c.strDict(v, f.at("files"))
	}
	if v, ok := f.get("bundle"); ok && v != nil {
		if b, ok := bundleFrom(&c, v, f.at("bundle")); ok {
			out.Bundle = &b
		}
	}
	out.SetupValues = c.setupValues(f)
	out.Target = BundleTarget{Into: c.installRef(f, "into"), Origin: c.origin(f)}
	if len(c.errs) > 0 {
		return AnalyzeRequest{}, c.errs
	}
	provided := 0
	for _, s := range []*string{out.Source, out.SourceURL} {
		if s != nil && pyStrip(*s) != "" {
			provided++
		}
	}
	if len(out.Files) > 0 {
		provided++
	}
	if out.Bundle != nil {
		provided++
	}
	loc := []any{"body"}
	if provided != 1 {
		c.valueError("provide exactly one of 'source', 'source_url', 'files' or 'bundle'", loc)
		return AnalyzeRequest{}, c.errs
	}
	for _, p := range out.Files {
		if err := CheckFolderPath(p.Key); err != nil {
			c.valueError(err.Error(), loc)
			return AnalyzeRequest{}, c.errs
		}
	}
	if FolderSize(out.Files) > BundleMaxBytes {
		c.valueError("agent folder exceeds 5MB limit", loc)
		return AnalyzeRequest{}, c.errs
	}
	return out, nil
}

// ValidateInstallRequest is InstallRequest.model_validate of the body object.
func ValidateInstallRequest(o wirejson.Object) (InstallRequest, []httpx.FieldError) {
	var c checker
	f := fields{o, []any{"body"}}
	var out InstallRequest
	if v, ok := f.get("bundle"); !ok {
		c.missing(f.at("bundle"))
	} else {
		out.Bundle, _ = bundleFrom(&c, v, f.at("bundle"))
	}
	out.SetupValues = c.setupValues(f)
	out.PlanDigest = c.requiredStr(f, "plan_digest", 1, 0)
	out.Target = BundleTarget{Into: c.installRef(f, "install_id"), Origin: c.origin(f)}
	if len(c.errs) > 0 {
		return InstallRequest{}, c.errs
	}
	return out, nil
}
