package service

import (
	"context"
	"errors"
	"fmt"
	"sort"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx/wirejson"
	catalogapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/catalog/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/catalog/store"
)

// created is one thing an install created and how to delete it again.
type created struct {
	what   string
	delete func(context.Context) error
	before int
}

// bundleInstaller writes a bundle through the owners of each kind, in
// dependency order: MCPs, OpenAPI connections, skills, agents, tasks,
// projects, streams, channels, automations, policies. An
// install that only creates is all-or-nothing by compensation; once a
// redeploy has updated in place, a failure keeps what it created.
type bundleInstaller struct {
	w        *workspace
	approved map[entityRef]bool
	// row is the install this deploy updates; nil creates one.
	row *store.BundleRow

	prior          *priorInstall
	pkg            *Bundle
	values         wirejson.Object
	supplied       map[string]bool
	result         InstallResult
	created        []created
	updatedInPlace bool

	mcpIDs, skillIDs, agentIDs, streamIDs, openapiIDs, taskIDs map[string]string
}

func refusalOf(err error) (string, bool) {
	var r *catalogapi.BundleRefusal
	if errors.As(err, &r) {
		return r.Msg, true
	}
	return "", false
}

func (in *bundleInstaller) install(ctx context.Context, b *Bundle, supplied wirejson.Object, prior *priorInstall, writesPolicies *bool) (InstallResult, error) {
	renames, _ := renamesOf(b, prior)
	in.prior, in.pkg = prior.renamed(renames), b
	in.values = effectiveSetup(b, supplied, prior)
	in.supplied = suppliedKeys(supplied)
	if err := in.refuseBlockingIssues(ctx, b, supplied); err != nil {
		return InstallResult{}, err
	}
	policies := len(b.Policies) > 0
	if writesPolicies != nil {
		policies = *writesPolicies
	}
	if policies {
		if err := in.w.b.d.Admin(ctx); err != nil {
			return InstallResult{}, err
		}
	}
	in.result = InstallResult{BundleName: b.Name, SetupValues: rememberedSetup(b, supplied, prior)}
	in.created, in.updatedInPlace = nil, false
	steps := []func(context.Context) error{in.installMCPs, in.installOpenAPIs, in.installSkills, in.installAgents, in.installTasks, in.installProjects, in.installStreams, in.installChannels,
		in.installAutomations, in.installPolicies, in.recordOrphans}
	for _, step := range steps {
		if err := step(ctx); err != nil {
			if in.updatedInPlace {
				in.w.b.d.Log.WarnContext(ctx, "Redeploy of bundle failed after updating in place; keeping what it created",
					"bundle", b.Name, "error", err)
			}
			in.undoCreated(context.WithoutCancel(ctx), in.updatedInPlace)
			return InstallResult{}, err
		}
	}
	return in.result, nil
}

func (in *bundleInstaller) refuseBlockingIssues(ctx context.Context, b *Bundle, supplied wirejson.Object) error {
	preview, err := (&bundleAnalyzer{prior: in.prior, shapes: in.w.b.shapes(), supplied: supplied}).analyze(ctx, b)
	if err != nil {
		return err
	}
	if block := preview.Blocks(); len(block) > 0 {
		return invalidError(blockedMessage(block), block...)
	}
	if in.prior == nil {
		if missing := requiredSetupErrors(b, in.values, nil); len(missing) > 0 {
			return invalidError("package is not installable: missing required setup", missing...)
		}
	}
	if secret := contextSecretErrors(in.w.b.shapes(), b, in.values); len(secret) > 0 {
		return invalidError("package is not installable: "+secret[0].Message, secret...)
	}
	return nil
}

// partialResult is what a failed redeploy wrote, plus what earlier installs own that it never reached.
func (in *bundleInstaller) partialResult() (InstallResult, error) {
	out := in.result
	out.Entities = append([]InstalledEntity{}, in.result.Entities...)
	if in.prior == nil {
		return out, nil
	}
	reached := map[entityRef]bool{}
	for _, e := range out.Entities {
		reached[entityRef{e.Kind, e.Key}] = true
	}
	for _, ref := range in.prior.ownedEntities() {
		if reached[entityRef{ref.Kind, ref.Key}] {
			continue
		}
		fp, err := in.prior.fingerprint(ref.Kind, ref.Key)
		if err != nil {
			return InstallResult{}, err
		}
		ref.Fingerprint = fp
		out.Entities = append(out.Entities, ref)
	}
	return out, nil
}

func (in *bundleInstaller) track(what string, del func(context.Context) error) {
	in.created = append(in.created, created{what: what, delete: del, before: len(in.result.Entities)})
}

// undoCreated deletes what this install created, newest first, past failures;
// unfinishedOnly removes just the parts of the entity the failure interrupted.
func (in *bundleInstaller) undoCreated(ctx context.Context, unfinishedOnly bool) {
	recorded := len(in.result.Entities)
	for len(in.created) > 0 {
		c := in.created[len(in.created)-1]
		in.created = in.created[:len(in.created)-1]
		if unfinishedOnly && c.before < recorded {
			break
		}
		if err := c.delete(ctx); err != nil {
			in.w.b.d.Log.ErrorContext(ctx, "Failed to remove what a failed bundle install created", "what", c.what, "error", err)
		}
	}
}

func (in *bundleInstaller) add(e InstalledEntity) { in.result.Entities = append(in.result.Entities, e) }

func (in *bundleInstaller) fingerprint(spec bundleSpec) (*string, error) {
	fp, err := specFingerprint(in.pkg, spec, in.values)
	if err != nil {
		return nil, err
	}
	return &fp, nil
}

func (in *bundleInstaller) applied(kind EntityKind, key string) (*string, error) {
	if in.prior == nil {
		return nil, nil
	}
	return in.prior.fingerprint(kind, key)
}

func (in *bundleInstaller) needsUpdate(kind EntityKind, spec bundleSpec, deps []entityRef) (bool, error) {
	if in.prior == nil {
		return true, nil
	}
	fp, err := in.fingerprint(spec)
	if err != nil {
		return false, err
	}
	applied, err := in.prior.fingerprint(kind, spec.specKey())
	if err != nil {
		return false, err
	}
	if !sameID(applied, fp) {
		return true, nil
	}
	return in.prior.depsChanged(deps, func(r entityRef) *string { return linkedID(&in.result, r.kind, r.key) }), nil
}

// owned is the live entity an earlier install of this bundle created for key.
func (in *bundleInstaller) owned(ctx context.Context, kind EntityKind, key string) (*string, live, error) {
	if in.prior == nil {
		return nil, live{}, nil
	}
	return in.live(ctx, kind, in.prior.owned(kind, key))
}

// reused is the live entity an earlier install of this bundle linked for key.
func (in *bundleInstaller) reused(ctx context.Context, kind EntityKind, key string) (*string, error) {
	if in.prior == nil {
		return nil, nil
	}
	id, _, err := in.live(ctx, kind, in.prior.reused(kind, key))
	return id, err
}

func (in *bundleInstaller) live(ctx context.Context, kind EntityKind, ref *InstalledEntity) (*string, live, error) {
	if ref == nil || ref.ID == nil {
		return nil, live{}, nil
	}
	l, ok, err := in.w.live(ctx, kind, *ref.ID)
	if err != nil || !ok {
		return nil, live{}, err
	}
	id := *ref.ID
	return &id, l, nil
}

func reusedEntity(kind EntityKind, key, name, id string) InstalledEntity {
	return InstalledEntity{Kind: kind, Key: key, Name: name, Action: ActionReused, ID: &id}
}

func (in *bundleInstaller) authorizeUpdate(ctx context.Context, kind EntityKind, key, id string) error {
	refusal := ""
	if !in.approved[entityRef{kind, key}] {
		refusal = fmt.Sprintf("%s '%s' would be updated, but the deploy plan did not approve it", kind, key)
	} else if containsKind(editGuarded(), kind) {
		ok, err := in.w.mayEdit(ctx, kind, id)
		if err != nil {
			return err
		}
		if !ok {
			refusal = fmt.Sprintf("%s '%s' would be updated, but you may not edit %s %s", kind, key, kind, id)
		}
	}
	if refusal != "" {
		return installError(refusal, blockIssue(key, refusal))
	}
	return nil
}

func containsKind(kinds []EntityKind, k EntityKind) bool {
	for _, x := range kinds {
		if x == k {
			return true
		}
	}
	return false
}

// skipped stays owned when an earlier install created it, so it is managed again once fixed.
func (in *bundleInstaller) skipped(kind EntityKind, key, name, detail string) (InstalledEntity, error) {
	e := InstalledEntity{Kind: kind, Key: key, Name: name, Action: ActionSkipped, Detail: &detail}
	if in.prior == nil {
		return e, nil
	}
	if ref := in.prior.owned(kind, key); ref != nil {
		e.ID = ref.ID
		fp, err := in.prior.fingerprint(kind, key)
		if err != nil {
			return InstalledEntity{}, err
		}
		e.Fingerprint = fp
	}
	return e, nil
}

func (in *bundleInstaller) addSkipped(kind EntityKind, key, name, detail string) error {
	e, err := in.skipped(kind, key, name, detail)
	if err != nil {
		return err
	}
	in.add(e)
	return nil
}

func (in *bundleInstaller) recordOrphans(ctx context.Context) error {
	if in.prior == nil {
		return nil
	}
	for _, ref := range in.prior.ownedEntities() {
		declared := false
		for _, s := range bundleEntities(in.pkg, ref.Kind) {
			declared = declared || s.specKey() == ref.Key
		}
		if declared || ref.ID == nil {
			continue
		}
		ok, err := in.w.refExists(ctx, ref.Kind, *ref.ID)
		if err != nil {
			return err
		}
		if !ok {
			continue
		}
		fp, err := in.applied(ref.Kind, ref.Key)
		if err != nil {
			return err
		}
		detail := orphanedDetail
		in.add(InstalledEntity{Kind: ref.Kind, Key: ref.Key, Name: ref.Name, Action: ActionOrphaned, ID: ref.ID, Detail: &detail, Fingerprint: fp})
	}
	return nil
}

// -- MCP

func (in *bundleInstaller) installMCPs(ctx context.Context) error {
	ids := map[string]string{}
	for _, m := range in.pkg.MCPs {
		if reason := mcpUnsupported(m); reason != "" {
			if err := in.addSkipped(KindMCP, m.Key, m.Name, reason); err != nil {
				return err
			}
			continue
		}
		id, l, err := in.owned(ctx, KindMCP, m.Key)
		if err != nil {
			return err
		}
		if id != nil {
			ids[m.Key] = *id
			e, err := in.redeployMCP(ctx, m, *id, l.name)
			if err != nil {
				return err
			}
			in.add(e)
			continue
		}
		reused, err := in.reused(ctx, KindMCP, m.Key)
		if err != nil {
			return err
		}
		if reused != nil {
			ids[m.Key] = *reused
			in.add(reusedEntity(KindMCP, m.Key, m.Name, *reused))
			continue
		}
		instanceID, err := in.createMCP(ctx, m)
		if err != nil {
			return err
		}
		ids[m.Key] = instanceID
		fp, err := in.fingerprint(m)
		if err != nil {
			return err
		}
		in.add(InstalledEntity{Kind: KindMCP, Key: m.Key, Name: m.Name, Action: ActionCreated, ID: &instanceID, Fingerprint: fp})
	}
	in.mcpIDs = ids
	return nil
}

func (in *bundleInstaller) resolve(v any) any {
	if s, ok := v.(string); ok {
		return resolvePlaceholders(s, in.values)
	}
	return v
}

// transportFields is the runtime transport of a bundle MCP's json_spec, its placeholders resolved.
func (in *bundleInstaller) transportFields(spec wirejson.Object) map[string]any {
	typ, _ := spec.Get("type")
	out := map[string]any{"type": plainJSON(typ)}
	switch typ {
	case "command":
		command, _ := spec.Get("command")
		out["command"] = plainJSON(command)
		if args, _ := spec.Get("args"); args != nil {
			if l, ok := args.([]any); ok && len(l) > 0 {
				resolved := make([]any, len(l))
				for i, a := range l {
					resolved[i] = plainJSON(in.resolve(a))
				}
				out["args"] = resolved
			}
		}
	case "docker":
		image, _ := spec.Get("image")
		out["image"] = plainJSON(image)
	case "url":
		endpoint, _ := spec.Get("endpoint_url")
		if !given(endpoint) {
			endpoint, _ = spec.Get("url")
		}
		out["endpoint_url"] = plainJSON(in.resolve(endpoint))
	}
	return out
}

func plainConfig(spec *wirejson.Object, field string) wirejson.Object {
	if spec == nil {
		return nil
	}
	v, _ := spec.Get(field)
	o, _ := v.(wirejson.Object)
	return o
}

func (in *bundleInstaller) envSchema(m BundleMCP) []any {
	var out []any
	for _, b := range m.Bindings {
		_, isSecret := secretBinding(b.Value)
		if refs := setupRefsOf(b.Value); !isSecret && len(refs) > 0 {
			f, ok := in.pkg.SetupField(refs[0])
			isSecret = ok && f.Type == "secret"
		}
		out = append(out, map[string]any{"name": b.Key, "description": fmt.Sprintf("%s for %s", b.Key, m.Name), "isSecret": isSecret})
	}
	for _, field := range []string{"environment", "headers"} {
		for _, c := range plainConfig(m.JSONSpec, field) {
			if _, bound := m.Bindings.Get(c.Key); bound {
				continue
			}
			out = append(out, map[string]any{"name": c.Key, "description": fmt.Sprintf("%s for %s", c.Key, m.Name), "isSecret": false})
		}
	}
	if out == nil {
		out = []any{}
	}
	return out
}

func strOf(v any) *string {
	if s, ok := v.(string); ok {
		return &s
	}
	return nil
}

// mcpWrite is what the bundle declares of an MCP, its placeholders resolved:
// the spec it creates (nil for a catalog server, whose spec id it names) and the instance.
type mcpWrite struct {
	catalogSpecID string
	spec          *catalogapi.MCPSpecNew
	instance      catalogapi.BundleInstance
	// contextSecret: instance.ContextSecret is the declared one, resolved.
	contextSecret bool
}

// mcpWrite builds m's spec and instance; keep is what an unresolved secret
// binding is sent as, nil leaving it out.
func (in *bundleInstaller) mcpWrite(ctx context.Context, m BundleMCP, keep any) (mcpWrite, error) {
	w := in.w
	var out mcpWrite
	var transport string
	var specFields map[string]any
	if m.Catalog != nil {
		found, err := w.catalogMCP(ctx, *m.Catalog)
		if err != nil {
			return mcpWrite{}, err
		}
		if found == nil {
			return mcpWrite{}, invalidError(fmt.Sprintf("mcp '%s' names catalog server '%s', which the catalog does not have", m.Key, *m.Catalog))
		}
		if found.Transport == nil {
			return mcpWrite{}, invalidError(fmt.Sprintf("mcp '%s' names catalog server '%s', which declares no transport", m.Key, *m.Catalog))
		}
		transport, out.catalogSpecID = *found.Transport, found.SpecID
	} else {
		spec := wirejson.Object{}
		if m.JSONSpec != nil {
			spec = *m.JSONSpec
		}
		specFields = in.transportFields(spec)
		transport, _ = specFields["type"].(string)
		n := catalogapi.MCPSpecNew{Name: m.Name, Description: fmt.Sprintf("Imported from package '%s'", in.pkg.Name),
			Version: "1.0.0", EnvSchema: in.envSchema(m), JSONSpec: specFields, Tags: []any{}}
		switch transport {
		case "command":
			if command := specFields["command"]; given(command) {
				args, _ := specFields["args"].([]any)
				n.Cmd = append([]any{command}, args...)
			}
		case "docker":
			n.DockerImageURL = strOf(specFields["image"])
		case "url":
			n.RemoteURL = strOf(specFields["endpoint_url"])
		}
		out.spec = &n
	}

	target := "environment"
	if transport == "url" {
		target = "headers"
	}
	resolved := wirejson.Object{}
	for _, b := range m.Bindings {
		if name, ok := secretBinding(b.Value); ok {
			resolved.Set(b.Key, w.b.d.MCPs.SecretRef(name))
		} else if v := resolvePlaceholders(b.Value, in.values); len(setupRefsOf(v)) == 0 {
			resolved.Set(b.Key, v)
		} else if keep != nil && bindsSecret(in.pkg, b.Value) {
			resolved.Set(b.Key, keep)
		}
	}
	instanceJSON := map[string]any{}
	for _, field := range []string{"environment", "headers"} {
		values := append(wirejson.Object{}, plainConfig(m.JSONSpec, field)...)
		if field == target {
			for _, r := range resolved {
				values.Set(r.Key, r.Value)
			}
		}
		if len(values) > 0 {
			instanceJSON[field] = plainJSON(values)
		}
	}
	out.instance = catalogapi.BundleInstance{Name: m.Name, JSONSpec: instanceJSON}
	if m.ContextSecret != nil && *m.ContextSecret != "" {
		if v := resolvePlaceholders(*m.ContextSecret, in.values); len(setupRefsOf(v)) == 0 {
			out.instance.ContextSecret, out.contextSecret = &v, true
		}
	}
	return out, nil
}

func (in *bundleInstaller) createMCP(ctx context.Context, m BundleMCP) (string, error) {
	w := in.w
	plan, err := in.mcpWrite(ctx, m, nil)
	if err != nil {
		return "", err
	}
	var made catalogapi.BundleMCPCreated
	if plan.spec == nil {
		made, err = w.b.d.MCPs.CreateFromSpec(ctx, w.c, plan.catalogSpecID, plan.instance)
	} else {
		made, err = w.b.d.MCPs.CreateWithSpec(ctx, w.c, *plan.spec, plan.instance)
	}
	if msg, ok := refusalOf(err); ok {
		return "", invalidError(fmt.Sprintf("MCP '%s' was refused: %s", m.Key, msg))
	}
	if err != nil {
		return "", err
	}
	if plan.spec != nil || (made.SpecID != "" && made.SpecID != plan.catalogSpecID) {
		what := fmt.Sprintf("MCP server spec '%s'", m.Name)
		if plan.spec == nil {
			what = fmt.Sprintf("MCP server spec copy '%s'", m.Name)
		}
		specID := made.SpecID
		in.track(what, func(ctx context.Context) error { return w.b.d.MCPs.DeleteSpec(ctx, w.c, specID) })
	}
	instanceID := made.InstanceID
	in.track(fmt.Sprintf("MCP instance '%s'", m.Name), func(ctx context.Context) error {
		return w.b.d.MCPs.DeleteInstance(ctx, w.c, instanceID)
	})
	return instanceID, nil
}

// redeployMCP applies the bundle to an MCP an earlier install created, when it
// changed or was given a secret, then discovers its tools again so agents see
// the ones it serves now.
func (in *bundleInstaller) redeployMCP(ctx context.Context, m BundleMCP, id, name string) (InstalledEntity, error) {
	w := in.w
	e := InstalledEntity{Kind: KindMCP, Key: m.Key, Name: name, Action: ActionUnchanged, ID: &id}
	changed, err := in.needsUpdate(KindMCP, m, nil)
	if err != nil {
		return InstalledEntity{}, err
	}
	values, contextSecret := suppliedSecrets(in.pkg, m, in.values, in.supplied)
	same, contextSame := map[string]bool{}, false
	if len(values) > 0 || contextSecret != nil { // pragma: allowlist secret
		// Comparing needs edit on the instance: without it the update is refused below, by authorizeUpdate.
		allowed, err := w.mayEdit(ctx, KindMCP, id)
		if err != nil {
			return InstalledEntity{}, err
		}
		if allowed {
			same, contextSame, err = w.b.d.MCPs.SecretsMatch(ctx, w.c, id, values, contextSecret)
			if _, refused := refusalOf(err); refused {
				err = nil
			}
			if err != nil {
				return InstalledEntity{}, err
			}
		}
	}
	differ := contextSecret != nil && !contextSame // pragma: allowlist secret
	for k := range values {
		differ = differ || !same[k]
	}
	if changed || differ {
		if err := in.authorizeUpdate(ctx, KindMCP, m.Key, id); err != nil {
			return InstalledEntity{}, err
		}
		if m.Catalog == nil {
			refusal, err := w.specEditRefusal(ctx, id)
			if err != nil {
				return InstalledEntity{}, err
			}
			if refusal != "" {
				msg := fmt.Sprintf("mcp '%s' would be updated, but %s", m.Key, refusal)
				return InstalledEntity{}, installError(msg, blockIssue(m.Key, msg))
			}
		}
		plan, err := in.mcpWrite(ctx, m, w.b.d.MCPs.KeepSecret())
		if err != nil {
			return InstalledEntity{}, err
		}
		keep := w.b.d.MCPs.KeepSecret()
		for _, field := range []string{"environment", "headers"} {
			if set, ok := plan.instance.JSONSpec[field].(map[string]any); ok {
				for k := range set {
					if same[k] {
						set[k] = keep
					}
				}
			}
		}
		u := catalogapi.BundleMCPUpdate{Spec: plan.spec, Instance: plan.instance, SetContextSecret: plan.contextSecret && !contextSame}
		if before, ok := in.prior.spec(KindMCP, m.Key).(BundleMCP); ok && m.ContextSecret == nil && before.ContextSecret != nil {
			u.SetContextSecret = true // pragma: allowlist secret
		}
		err = w.b.d.MCPs.UpdateMCP(ctx, w.c, id, u)
		if msg, ok := refusalOf(err); ok {
			return InstalledEntity{}, installError(fmt.Sprintf("MCP '%s' was refused: %s", m.Key, msg))
		}
		if errors.Is(err, catalogapi.ErrBundleEntityGone) {
			return InstalledEntity{}, installError(fmt.Sprintf("mcp '%s' disappeared mid-update", m.Key))
		}
		if err != nil {
			return InstalledEntity{}, err
		}
		in.updatedInPlace = true
		e.Action, e.Name = ActionUpdated, m.Name
	}
	if e.Fingerprint, err = in.fingerprint(m); err != nil {
		return InstalledEntity{}, err
	}
	return e, nil
}

// rediscoverMCPs discovers again the tools of the MCPs this deploy created or
// updated, and of the unchanged ones the caller may edit, once the install
// committed: agents see the tools each serves now. The outcome is each MCP's
// detail in result, never the install's: the writes are done.
func (in *bundleInstaller) rediscoverMCPs(ctx context.Context, result *InstallResult) {
	w := in.w
	refused := "tools not re-discovered: you may not edit it"
	for i, e := range result.Entities {
		if e.Kind != KindMCP || !hasID(e) {
			continue
		}
		set := func(d string) { result.Entities[i].Detail = &d }
		switch e.Action {
		case ActionCreated, ActionUpdated:
		case ActionUnchanged:
			allowed, err := w.mayEdit(ctx, KindMCP, *e.ID)
			if err != nil {
				w.b.d.Log.ErrorContext(ctx, "Could not check edit on a bundle's MCP", "mcp", e.Key, "instance_id", *e.ID, "error", err)
				set("tools not re-discovered: " + err.Error())
				continue
			}
			if !allowed {
				set(refused)
				continue
			}
		case ActionOrphaned, ActionReused, ActionSkipped:
			continue
		}
		found, err := w.b.d.MCPs.Rediscover(ctx, w.c, *e.ID)
		if _, isRefusal := refusalOf(err); isRefusal {
			set(refused)
			continue
		}
		switch {
		case err != nil:
			w.b.d.Log.ErrorContext(ctx, "Could not re-discover the tools of a bundle's MCP", "mcp", e.Key, "instance_id", *e.ID, "error", err)
			set("tools not re-discovered: " + err.Error())
		case found.Status != "succeeded":
			d := "tools not re-discovered: verification " + found.Status
			if found.Error != nil && *found.Error != "" {
				d += ": " + *found.Error
			}
			set(d)
		default:
			set(fmt.Sprintf("tools re-discovered: %d", found.Tools))
		}
	}
}

// -- skills

func skillFiles(s BundleSkill) []catalogapi.BundleFile {
	if s.SourceType != "files" {
		content := ""
		if s.Content != nil {
			content = *s.Content
		}
		return []catalogapi.BundleFile{{Path: "SKILL.md", Text: content}}
	}
	var out []catalogapi.BundleFile
	if s.Files != nil {
		for _, f := range *s.Files {
			out = append(out, catalogapi.BundleFile{Path: f.Key, Text: f.Value})
		}
	}
	return out
}

func notValidSkill(key, msg string) error {
	return invalidError(fmt.Sprintf("skill '%s' is not a valid SKILL.md: %s", key, msg))
}

func (in *bundleInstaller) installSkills(ctx context.Context) error {
	w := in.w
	in.skillIDs = map[string]string{}
	for _, s := range in.pkg.Skills {
		id, _, err := in.owned(ctx, KindSkill, s.Key)
		if err != nil {
			return err
		}
		if id != nil {
			in.skillIDs[s.Key] = *id
			e := InstalledEntity{Kind: KindSkill, Key: s.Key, Name: s.Name, Action: ActionUnchanged, ID: id}
			if e.Fingerprint, err = in.fingerprint(s); err != nil {
				return err
			}
			update, err := in.needsUpdate(KindSkill, s, nil)
			if err != nil {
				return err
			}
			switch {
			case update && s.SourceType == "github":
				detail := githubSkillNotApplied
				e.Detail = &detail
				applied, err := in.applied(KindSkill, s.Key)
				if err != nil {
					return err
				}
				if applied != nil && *applied != "" {
					e.Fingerprint = applied
				}
			case update:
				if err := in.authorizeUpdate(ctx, KindSkill, s.Key, *id); err != nil {
					return err
				}
				err := w.b.d.Agents.ReplaceSkillFiles(ctx, w.c, *id, skillFiles(s))
				if msg, ok := refusalOf(err); ok {
					return notValidSkill(s.Key, msg)
				}
				if err != nil {
					return err
				}
				in.updatedInPlace = true
				err = w.b.d.Agents.RenameSkill(ctx, w.c, *id, s.Name)
				if msg, ok := refusalOf(err); ok {
					return installError(msg)
				}
				if err != nil {
					return err
				}
				e.Action = ActionUpdated
			}
			in.add(e)
			continue
		}
		reused, err := in.reused(ctx, KindSkill, s.Key)
		if err != nil {
			return err
		}
		if reused != nil {
			in.skillIDs[s.Key] = *reused
			in.add(reusedEntity(KindSkill, s.Key, s.Name, *reused))
			continue
		}
		created, err := in.createSkill(ctx, s)
		if err != nil {
			return err
		}
		in.track(fmt.Sprintf("skill '%s'", s.Name), func(ctx context.Context) error { return w.b.d.Agents.DeleteSkill(ctx, w.c, created) })
		in.skillIDs[s.Key] = created
		fp, err := in.fingerprint(s)
		if err != nil {
			return err
		}
		in.add(InstalledEntity{Kind: KindSkill, Key: s.Key, Name: s.Name, Action: ActionCreated, ID: &created, Fingerprint: fp})
	}
	return nil
}

func (in *bundleInstaller) createSkill(ctx context.Context, s BundleSkill) (string, error) {
	w := in.w
	n := catalogapi.BundleSkillNew{Name: s.Name}
	switch s.SourceType {
	case "github":
		n.GitHubURL = *s.SourceURL
	case "files":
		n.Files = skillFiles(s)
	default:
		n.Content = *s.Content
	}
	id, err := w.b.d.Agents.CreateSkill(ctx, w.c, n)
	msg, refused := refusalOf(err)
	switch {
	case refused && s.SourceType == "github":
		w.b.d.Log.WarnContext(ctx, "Failed to import skill", "skill", s.Name, "source_url", n.GitHubURL, "error", err)
		return "", installError(fmt.Sprintf("failed to import skill '%s' from %s: %s", s.Name, n.GitHubURL, msg))
	case refused:
		return "", notValidSkill(s.Key, msg)
	}
	return id, err
}

// -- agents

func (in *bundleInstaller) clientID(a BundleAgent) (*string, error) {
	if a.Client == nil {
		return nil, nil
	}
	u, err := uuid.Parse(resolvePlaceholders(*a.Client, in.values))
	if err != nil {
		return nil, invalidError(fmt.Sprintf("agent '%s': client must be the id of a Codex or Claude Code client", a.Key))
	}
	return strp(u.String()), nil
}

// linkedBefore are the ids the last install pointed refs at.
func (in *bundleInstaller) linkedBefore(kind EntityKind, refs []string) []string {
	if in.prior == nil {
		return nil
	}
	var out []string
	for _, r := range refs {
		if id := linkedID(&in.prior.result, kind, r); id != nil && *id != "" {
			out = append(out, *id)
		}
	}
	return out
}

func setStr(s *string) bool { return s != nil && *s != "" }
func setInt(n *int64) bool  { return n != nil && *n != 0 }

// modelName is the model an agent names by name rather than id, "" when it gives an id or a placeholder left unresolved.
func modelName(a BundleAgent, values wirejson.Object) string {
	if a.Model == nil {
		return ""
	}
	ref := resolvePlaceholders(*a.Model, values)
	if ref == "" || len(setupRefsOf(ref)) > 0 {
		return ""
	}
	if _, err := uuid.Parse(ref); err == nil {
		return ""
	}
	return ref
}

// namedModel is the instance recorded for an agent whose model is a name: what a later plan compares the name against.
func (in *bundleInstaller) namedModel(a BundleAgent, id string) *string {
	if modelName(a, in.values) == "" {
		return nil
	}
	return &id
}

// modelID is the instance an agent's model names, its setup placeholders resolved.
func (in *bundleInstaller) modelID(ctx context.Context, a BundleAgent) (string, error) {
	model := ""
	if a.Model != nil {
		model = *a.Model
	}
	id, problem, err := in.w.modelID(ctx, resolvePlaceholders(model, in.values))
	if err != nil {
		return "", err
	}
	if problem != "" {
		return "", invalidError(fmt.Sprintf("agent '%s': %s", a.Key, problem))
	}
	return id, nil
}

// installAgents writes the agents delegates first, so a delegate tool names an agent that exists.
func (in *bundleInstaller) installAgents(ctx context.Context) error {
	w := in.w
	in.agentIDs = map[string]string{}
	order, _ := agentOrder(in.pkg.Agents)
	for _, a := range order {
		var tools []catalogapi.BundleTool
		for _, n := range a.Toolsets {
			tools = append(tools, catalogapi.BundleTool{Type: "code", Name: n})
		}
		for _, ref := range a.MCPs {
			if id, ok := in.mcpIDs[ref]; ok {
				tools = append(tools, catalogapi.BundleTool{Type: "mcp", Name: id})
			}
		}
		for _, ref := range a.OpenAPI {
			if id, ok := in.openapiIDs[ref]; ok {
				tools = append(tools, openAPITool(id))
			}
		}
		for _, ref := range a.Delegates {
			if id, ok := in.agentIDs[ref]; ok {
				tools = append(tools, catalogapi.BundleTool{Type: "agent", Name: ref, AgentID: strp(id)})
			}
		}
		var skillIDs []string
		for _, ref := range a.Skills {
			if id, ok := in.skillIDs[ref]; ok {
				skillIDs = append(skillIDs, id)
			}
		}
		id, _, err := in.owned(ctx, KindAgent, a.Key)
		if err != nil {
			return err
		}
		if id != nil {
			in.agentIDs[a.Key] = *id
			e := InstalledEntity{Kind: KindAgent, Key: a.Key, Name: a.Name, Action: ActionUnchanged, ID: id,
				ModelID: in.prior.owned(KindAgent, a.Key).ModelID}
			update, err := in.needsUpdate(KindAgent, a, agentDeps(a))
			if err != nil {
				return err
			}
			// The plan also approves an agent whose model name now names another instance.
			if update || in.approved[entityRef{KindAgent, a.Key}] {
				modelID, err := in.modelID(ctx, a)
				if err != nil {
					return err
				}
				if err := in.updateAgent(ctx, *id, a, modelID, tools, skillIDs); err != nil {
					return err
				}
				in.updatedInPlace = true
				e.Action, e.ModelID = ActionUpdated, in.namedModel(a, modelID)
			}
			if e.Fingerprint, err = in.fingerprint(a); err != nil {
				return err
			}
			in.add(e)
			continue
		}
		reused, err := in.reused(ctx, KindAgent, a.Key)
		if err != nil {
			return err
		}
		if reused != nil {
			in.agentIDs[a.Key] = *reused
			in.add(reusedEntity(KindAgent, a.Key, a.Name, *reused))
			continue
		}
		client, err := in.clientID(a)
		if err != nil {
			return err
		}
		modelID, err := in.modelID(ctx, a)
		if err != nil {
			return err
		}
		created, err := w.b.d.Agents.CreateAgent(ctx, w.c, catalogapi.BundleAgentNew{Name: a.Name, Description: a.Description,
			Instruction: a.Instruction, ModelID: modelID, ClientID: client, Tools: tools, SkillIDs: skillIDs,
			ReasoningEffort: a.ReasoningEffort, ReasoningMaxTokens: int32Of(a.ReasoningMaxTokens)})
		if msg, ok := refusalOf(err); ok {
			return installError(msg)
		}
		if err != nil {
			return err
		}
		in.track(fmt.Sprintf("agent '%s'", a.Name), func(ctx context.Context) error { return w.b.d.Agents.DeleteAgent(ctx, w.c, created) })
		in.agentIDs[a.Key] = created
		fp, err := in.fingerprint(a)
		if err != nil {
			return err
		}
		in.add(InstalledEntity{Kind: KindAgent, Key: a.Key, Name: a.Name, Action: ActionCreated, ID: &created, Fingerprint: fp,
			ModelID: in.namedModel(a, modelID)})
	}
	return nil
}

func (in *bundleInstaller) updateAgent(ctx context.Context, id string, a BundleAgent, modelID string, tools []catalogapi.BundleTool, skillIDs []string) error {
	w := in.w
	if err := in.authorizeUpdate(ctx, KindAgent, a.Key, id); err != nil {
		return err
	}
	var before *BundleAgent
	if in.prior != nil {
		if s, ok := in.prior.spec(KindAgent, a.Key).(BundleAgent); ok {
			before = &s
		}
	}
	u := catalogapi.BundleAgentUpdate{Name: a.Name, Description: a.Description, Instruction: a.Instruction, ModelID: modelID,
		Tools: tools, SkillIDs: skillIDs}
	if before != nil {
		for _, n := range before.Toolsets {
			u.ManagedTools = append(u.ManagedTools, catalogapi.BundleTool{Type: "code", Name: n})
		}
		for _, mid := range in.linkedBefore(KindMCP, before.MCPs) {
			u.ManagedTools = append(u.ManagedTools, catalogapi.BundleTool{Type: "mcp", Name: mid})
		}
		for _, oid := range in.linkedBefore(KindOpenAPI, before.OpenAPI) {
			u.ManagedTools = append(u.ManagedTools, openAPITool(oid))
		}
		for _, d := range before.Delegates {
			u.ManagedTools = append(u.ManagedTools, catalogapi.BundleTool{Type: "agent", Name: d, AgentID: linkedID(&in.prior.result, KindAgent, d)})
		}
		u.ManagedSkillIDs = in.linkedBefore(KindSkill, before.Skills)
	}
	if setStr(a.ReasoningEffort) || setInt(a.ReasoningMaxTokens) ||
		(before != nil && (setStr(before.ReasoningEffort) || setInt(before.ReasoningMaxTokens))) {
		u.SetReasoning, u.ReasoningEffort, u.ReasoningMaxTokens = true, a.ReasoningEffort, int32Of(a.ReasoningMaxTokens)
	}
	if setStr(a.Client) || (before != nil && setStr(before.Client)) {
		client, err := in.clientID(a)
		if err != nil {
			return err
		}
		u.SetClient, u.ClientID = true, client
	}
	err := w.b.d.Agents.UpdateAgent(ctx, w.c, id, u)
	if errors.Is(err, catalogapi.ErrBundleEntityGone) {
		return installError(fmt.Sprintf("agent '%s' disappeared mid-update", a.Key))
	}
	if msg, ok := refusalOf(err); ok {
		return installError(msg)
	}
	return err
}

// -- channels and automations

func (in *bundleInstaller) enabledChanged(kind EntityKind, key string, enabled bool) bool {
	if in.prior == nil {
		return true
	}
	switch before := in.prior.spec(kind, key).(type) {
	case BundleChannel:
		return before.Enabled != enabled
	case BundleAutomation:
		return before.Enabled != enabled
	case BundlePolicy:
		return before.Enabled != enabled
	}
	return true
}

func (in *bundleInstaller) ownTrigger(triggers []catalogapi.BundleTrigger, kind EntityKind, key, name, agentID string) *string {
	var recorded *string
	if in.prior != nil {
		recorded = in.prior.recorded(kind, key)
	}
	return ownTrigger(triggers, name, agentID, recorded)
}

func pairsMap(p StrPairs) map[string]string {
	out := make(map[string]string, len(p))
	for _, e := range p {
		out[e.Key] = e.Value
	}
	return out
}

// channelRewrite is the credentials a redeploy stores: the supplied ones
// merged in, or all of them when none were stored. A credential that names a
// workspace secret is never replaced by a value.
func (in *bundleInstaller) channelRewrite(ctx context.Context, ch BundleChannel, triggerID string) (*catalogapi.BundleChannelCredentials, error) {
	if len(ch.Bindings) == 0 {
		return nil, nil
	}
	creds, ok, err := in.w.b.d.Triggers.ChannelCredentials(ctx, triggerID)
	if err != nil || !ok {
		return nil, err
	}
	unfinished := true
	for _, b := range ch.Bindings {
		if _, has := creds.Stored[b.Key]; has {
			unfinished = false
		}
	}
	supplied := in.supplied
	if unfinished {
		supplied = nil
	}
	rewrite := channelCredentials(ch, in.values, supplied)
	var referenced []string
	for _, r := range rewrite {
		if _, isRef := creds.Stored[r.Key].(map[string]any); isRef {
			referenced = append(referenced, r.Key)
		}
	}
	if len(referenced) > 0 {
		sort.Strings(referenced)
		issue := secretReferenceIssue(ch.Key, referenced)
		return nil, invalidError(issue.Message, issue)
	}
	if len(rewrite) == 0 {
		return nil, nil
	}
	merged := make(map[string]any, len(creds.Stored)+len(rewrite))
	for k, v := range creds.Stored {
		merged[k] = v
	}
	for _, r := range rewrite {
		merged[r.Key] = r.Value
	}
	creds.Stored = merged
	return &creds, nil
}

func refusedInstall(err error) error {
	if msg, ok := refusalOf(err); ok {
		return installError(msg)
	}
	return err
}

func (in *bundleInstaller) installChannels(ctx context.Context) error {
	t := in.w.b.d.Triggers
	triggers, err := t.Triggers(ctx)
	if err != nil {
		return err
	}
	for _, ch := range in.pkg.Channels {
		name := triggerName(in.pkg, ch.Key)
		agentID, ok := in.agentIDs[ch.Agent]
		if !ok {
			if err := in.addSkipped(KindChannel, ch.Key, name, fmt.Sprintf("agent '%s' was not created", ch.Agent)); err != nil {
				return err
			}
			continue
		}
		detail := fmt.Sprintf("%s · enabled=%s", ch.Type, pyBool(ch.Enabled))
		fp, err := in.fingerprint(ch)
		if err != nil {
			return err
		}
		id, _, err := in.owned(ctx, KindChannel, ch.Key)
		if err != nil {
			return err
		}
		if id != nil {
			update, err := in.needsUpdate(KindChannel, ch, []entityRef{{KindAgent, ch.Agent}})
			if err != nil {
				return err
			}
			creds, err := in.channelRewrite(ctx, ch, *id)
			if err != nil {
				return err
			}
			if update || creds != nil {
				if err := in.authorizeUpdate(ctx, KindChannel, ch.Key, *id); err != nil {
					return err
				}
			}
			if update {
				if err := refusedInstall(t.UpdateTrigger(ctx, *id, catalogapi.BundleTriggerUpdate{Description: ch.Name, AgentID: agentID, Text: ch.Prompt})); err != nil {
					return err
				}
				in.updatedInPlace = true
				if in.enabledChanged(KindChannel, ch.Key, ch.Enabled) {
					if err := t.SetTriggerEnabled(ctx, *id, ch.Enabled); err != nil {
						return err
					}
				}
			}
			if creds != nil {
				if err := t.SetChannelCredentials(ctx, *creds); err != nil {
					return err
				}
				in.updatedInPlace = true
			}
			action := ActionUnchanged
			if update || creds != nil {
				action = ActionUpdated
			}
			in.add(InstalledEntity{Kind: KindChannel, Key: ch.Key, Name: name, Action: action, ID: id, Detail: &detail, Fingerprint: fp})
			continue
		}
		if reused := in.ownTrigger(triggers, KindChannel, ch.Key, name, agentID); reused != nil {
			in.add(reusedEntity(KindChannel, ch.Key, name, *reused))
			continue
		}
		slug := ch.Type
		if slug == "generic" {
			slug = "generic_webhook"
		}
		made, err := t.CreateChannel(ctx, catalogapi.BundleChannelNew{Name: name, Description: ch.Name, AgentID: agentID, Text: ch.Prompt,
			SourceType: slug, Enabled: ch.Enabled, Credentials: pairsMap(channelCredentials(ch, in.values, nil))})
		if err != nil {
			return refusedInstall(err)
		}
		in.track(fmt.Sprintf("channel '%s'", name), func(ctx context.Context) error { return t.DeleteChannel(ctx, made) })
		triggerID := made.TriggerID
		in.add(InstalledEntity{Kind: KindChannel, Key: ch.Key, Name: name, Action: ActionCreated, ID: &triggerID, Detail: &detail, Fingerprint: fp})
	}
	return nil
}

func (in *bundleInstaller) installAutomations(ctx context.Context) error {
	t := in.w.b.d.Triggers
	triggers, err := t.Triggers(ctx)
	if err != nil {
		return err
	}
	for _, a := range in.pkg.Automations {
		name := triggerName(in.pkg, a.Key)
		agentID, taskID, ok, err := in.automationTarget(ctx, a)
		if err != nil {
			return err
		}
		if !ok {
			what := fmt.Sprintf("agent '%s'", automationAgent(in.pkg, a))
			if a.Task != nil {
				what = fmt.Sprintf("task '%s' or its agent", *a.Task)
			}
			if err := in.addSkipped(KindAutomation, a.Key, name, what+" was not created"); err != nil {
				return err
			}
			continue
		}
		detail := "enabled=" + pyBool(a.Enabled)
		fp, err := in.fingerprint(a)
		if err != nil {
			return err
		}
		streamID := ""
		if a.On != nil {
			if streamID, err = in.streamID(ctx, a.On.Stream); err != nil {
				return err
			}
		}
		id, l, err := in.owned(ctx, KindAutomation, a.Key)
		if err != nil {
			return err
		}
		if id != nil {
			action := ActionUnchanged
			update, err := in.needsUpdate(KindAutomation, a, automationDeps(in.pkg, a))
			if err != nil {
				return err
			}
			if update {
				if err := in.authorizeUpdate(ctx, KindAutomation, a.Key, *id); err != nil {
					return err
				}
				u := catalogapi.BundleTriggerUpdate{Description: automationDescription(a), AgentID: agentID, Text: a.Prompt,
					TaskDefinitionSet: true, TaskDefinitionID: taskID, Parameters: plainObject(a.Parameters)}
				if a.On != nil {
					if l.trigger.StreamID == nil || *l.trigger.StreamID != streamID {
						return installError(fmt.Sprintf("automation '%s' would move its trigger to another stream, which a redeploy cannot apply; give it a new key", a.Key))
					}
					u.Filter = plainObject(a.On.Filter)
				} else {
					cron, tz := a.Cron, a.Timezone
					u.Cron, u.Timezone = &cron, &tz
				}
				if err := refusedInstall(t.UpdateTrigger(ctx, *id, u)); err != nil {
					return err
				}
				in.updatedInPlace = true
				if in.enabledChanged(KindAutomation, a.Key, a.Enabled) {
					if err := t.SetTriggerEnabled(ctx, *id, a.Enabled); err != nil {
						return err
					}
				}
				action = ActionUpdated
			}
			in.add(InstalledEntity{Kind: KindAutomation, Key: a.Key, Name: name, Action: action, ID: id, Detail: &detail, Fingerprint: fp})
			continue
		}
		if reused := in.ownTrigger(triggers, KindAutomation, a.Key, name, agentID); reused != nil {
			in.add(reusedEntity(KindAutomation, a.Key, name, *reused))
			continue
		}
		created, err := t.CreateSchedule(ctx, automationSchedule(in.pkg, a, agentID, streamID, taskID))
		if err != nil {
			return refusedInstall(err)
		}
		in.track(fmt.Sprintf("automation trigger '%s'", name), func(ctx context.Context) error { return t.DeleteTrigger(ctx, created) })
		in.add(InstalledEntity{Kind: KindAutomation, Key: a.Key, Name: name, Action: ActionCreated, ID: &created, Detail: &detail, Fingerprint: fp})
	}
	return nil
}

// -- policies

func (in *bundleInstaller) installPolicies(ctx context.Context) error {
	w := in.w
	r := w.b.d.Rules
	for _, p := range in.pkg.Policies {
		workspaceWide := p.Subject == WorkspaceSubject
		subjectID, ok := in.agentIDs[p.Subject]
		if workspaceWide {
			subjectID, ok = w.c.Workspace.ID(), true
		}
		if !ok {
			if err := in.addSkipped(KindPolicy, p.Key, p.Key, fmt.Sprintf("agent '%s' was not created", p.Subject)); err != nil {
				return err
			}
			continue
		}
		approvers, err := in.approvers(ctx, p)
		if err != nil {
			return err
		}
		rule := policyAsRule(withApprovers(p, approvers), subjectID)
		if problem := r.RuleProblem(rule); problem != "" {
			if err := in.addSkipped(KindPolicy, p.Key, p.Key, "would never enforce: "+problem); err != nil {
				return err
			}
			continue
		}
		detail, deps := policyDetail(p, approvers.names), []entityRef{{KindAgent, p.Subject}}
		if workspaceWide {
			deps = nil
		}
		fp, err := in.fingerprint(p)
		if err != nil {
			return err
		}
		id, _, err := in.owned(ctx, KindPolicy, p.Key)
		if err != nil {
			return err
		}
		if id != nil {
			action := ActionUnchanged
			update, err := in.needsUpdate(KindPolicy, p, deps)
			if err != nil {
				return err
			}
			if update {
				if err := in.authorizeUpdate(ctx, KindPolicy, p.Key, *id); err != nil {
					return err
				}
				err := r.UpdateRule(ctx, w.c, *id, rule, in.enabledChanged(KindPolicy, p.Key, p.Enabled))
				if errors.Is(err, catalogapi.ErrBundleEntityGone) {
					return installError(fmt.Sprintf("policy '%s' disappeared mid-update", p.Key))
				}
				if err != nil {
					return err
				}
				in.updatedInPlace = true
				action = ActionUpdated
			}
			in.add(InstalledEntity{Kind: KindPolicy, Key: p.Key, Name: p.Key, Action: action, ID: id, Detail: &detail, Fingerprint: fp})
			continue
		}
		existing, ok, err := r.MatchingRule(ctx, w.c, rule)
		if err != nil {
			return err
		}
		if ok {
			in.add(InstalledEntity{Kind: KindPolicy, Key: p.Key, Name: p.Key, Action: ActionReused, ID: &existing})
			continue
		}
		created, err := r.CreateRule(ctx, w.c, rule)
		if err != nil {
			return err
		}
		in.track(fmt.Sprintf("policy '%s'", p.Key), func(ctx context.Context) error { return r.DeleteRule(ctx, w.c, created) })
		if setStr(p.Message) {
			detail += " — " + *p.Message
		}
		in.add(InstalledEntity{Kind: KindPolicy, Key: p.Key, Name: p.Key, Action: ActionCreated, ID: &created, Detail: &detail, Fingerprint: fp})
	}
	return nil
}
