package service

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"strings"
	"time"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authz"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx/wirejson"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/netguard"
	catalogapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/catalog/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/catalog/store"
	identityapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/identity/api"
	modelsapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/models/api"
)

// BundleErrorKind is how the API answers a refused deploy.
type BundleErrorKind int

const (
	// BundleInstallFailed is BundleInstallError: 400 bundle_install_failed.
	BundleInstallFailed BundleErrorKind = iota
	// BundleInvalid is BundleValidationError: 422 bundle_invalid.
	BundleInvalid
	// BundlePlanChanged is BundlePlanChangedError: 409 bundle_plan_changed.
	BundlePlanChanged
	// BundleDeployRunning is another deploy of the bundle holding its lock: 409 bundle_deploy_running.
	BundleDeployRunning
)

// BundleError is a deploy refused before or while it wrote.
type BundleError struct {
	Kind   BundleErrorKind
	Msg    string
	Issues []PreviewIssue
}

func (e *BundleError) Error() string { return e.Msg }

func installError(msg string, issues ...PreviewIssue) *BundleError {
	return &BundleError{Kind: BundleInstallFailed, Msg: msg, Issues: issues}
}

func invalidError(msg string, issues ...PreviewIssue) *BundleError {
	return &BundleError{Kind: BundleInvalid, Msg: msg, Issues: issues}
}

// BundleDeps are the owners a bundle deploy writes through.
type BundleDeps struct {
	DB       db.Database
	Agents   catalogapi.BundleAgents
	MCPs     catalogapi.BundleMCPs
	OpenAPIs catalogapi.BundleOpenAPIs
	Triggers catalogapi.BundleTriggers
	Streams  catalogapi.BundleStreams
	Tasks    catalogapi.BundleTasks
	Projects catalogapi.BundleProjects
	Rules    catalogapi.BundleRules
	// Members are the workspace's members, whom an approval policy's approvers name.
	Members BundleMembers
	// Models resolves the model an agent runs, for the reasoning levels it takes.
	Models modelsapi.Resolver
	// ModelNames finds a model instance by name, and the currency a limit is in.
	ModelNames modelsapi.Directory
	// MayEdit is the per-object edit check of the entity's own update route.
	MayEdit func(ctx context.Context, c authn.Caller, resourceType, id string) (bool, error)
	// Admin is requires_workspace_admin, asked before a deploy writes a policy.
	Admin func(ctx context.Context) error
	// Guard and Net fetch a source_url; without them such an analyze fails.
	Guard func() *netguard.Guard
	Net   netguard.Clients
	Log   *slog.Logger
	Now   func() time.Time
}

// BundleMembers lists the members of the caller's workspace (identity module).
type BundleMembers interface {
	ListMembers(ctx context.Context, c authn.Caller) ([]identityapi.Member, error)
}

// Bundles analyzes and installs bundles into a workspace.
type Bundles struct {
	d     BundleDeps
	rows  store.Bundles
	specs store.MCPSpecs
}

// MissingDepsError names the owners a deploy service was built without.
type MissingDepsError struct{ Missing []string }

func (e *MissingDepsError) Error() string {
	return "catalog bundles: missing " + strings.Join(e.Missing, ", ")
}

// NewBundles builds the deploy service; every owner is required.
func NewBundles(d BundleDeps) (*Bundles, error) {
	var missing []string
	for _, dep := range []struct {
		name string
		set  bool
	}{{"database", d.DB != nil}, {"agents", d.Agents != nil}, {"MCP connections", d.MCPs != nil}, {"OpenAPI connections", d.OpenAPIs != nil}, {"triggers", d.Triggers != nil}, {"streams", d.Streams != nil}, {"tasks", d.Tasks != nil}, {"projects", d.Projects != nil}, {"members", d.Members != nil},
		{"policy rules", d.Rules != nil}, {"models", d.Models != nil}, {"model names", d.ModelNames != nil}, {"edit check", d.MayEdit != nil}, {"workspace admin", d.Admin != nil}} {
		if !dep.set {
			missing = append(missing, dep.name)
		}
	}
	if len(missing) > 0 {
		return nil, &MissingDepsError{Missing: missing}
	}
	if d.Log == nil {
		d.Log = slog.Default()
	}
	if d.Now == nil {
		d.Now = time.Now
	}
	return &Bundles{d: d}, nil
}

func callerOf(ctx context.Context) (authn.Caller, error) {
	c, ok := authn.CallerFrom(ctx)
	if !ok {
		return authn.Caller{}, authn.ErrWorkspaceNotSelected
	}
	return c, nil
}

// bundleShapes are the owners' pure checks.
type portShapes struct {
	agents   catalogapi.BundleAgents
	mcps     catalogapi.BundleMCPs
	openapis catalogapi.BundleOpenAPIs
	rules    catalogapi.BundleRules
}

func (p portShapes) HeaderIsSecret(name string) bool { return p.openapis.HeaderIsSecret(name) }

func (p portShapes) SkillProblem(content string) string { return p.agents.SkillProblem(content) }
func (p portShapes) SkillMainFile(paths []string) (string, bool) {
	return p.agents.SkillMainFile(paths)
}
func (p portShapes) CarriesSecretRef(v any) bool                 { return p.mcps.CarriesSecretRef(v) }
func (p portShapes) RuleProblem(r catalogapi.BundleRule) string  { return p.rules.RuleProblem(r) }
func (p portShapes) ContextSecretLength() (minimum, maximum int) { return p.mcps.ContextSecretLength() }

func (b *Bundles) shapes() bundleShapes {
	return portShapes{agents: b.d.Agents, mcps: b.d.MCPs, openapis: b.d.OpenAPIs, rules: b.d.Rules}
}

// workspace answers a deploy's existence and write questions for one caller.
type workspace struct {
	b        *Bundles
	c        authn.Caller
	catalogs map[string]*catalogMCP
	models   []modelsapi.InstanceName
	people   []identityapi.Member
}

func (b *Bundles) workspace(ctx context.Context) (*workspace, error) {
	c, err := callerOf(ctx)
	if err != nil {
		return nil, err
	}
	return &workspace{b: b, c: c, catalogs: map[string]*catalogMCP{}}, nil
}

// live is the entity a recorded id names, when it still stands.
type live struct {
	name    string
	trigger catalogapi.BundleTrigger
}

func (w *workspace) live(ctx context.Context, kind EntityKind, id string) (live, bool, error) {
	switch kind {
	case KindMCP:
		name, ok, err := w.b.d.MCPs.InstanceName(ctx, w.c, id)
		return live{name: name}, ok, err
	case KindSkill:
		ok, err := w.b.d.Agents.SkillLive(ctx, w.c, id)
		return live{}, ok, err
	case KindAgent:
		ok, err := w.b.d.Agents.AgentLive(ctx, w.c, id)
		return live{}, ok, err
	case KindChannel, KindAutomation:
		t, ok, err := w.b.d.Triggers.Trigger(ctx, id)
		return live{name: t.Name, trigger: t}, ok, err
	case KindPolicy:
		ok, err := w.b.d.Rules.RuleLive(ctx, w.c, id)
		return live{}, ok, err
	case KindStream:
		name, ok, err := w.b.d.Streams.StreamName(ctx, id)
		return live{name: name}, ok, err
	case KindOpenAPI:
		name, ok, err := w.b.d.OpenAPIs.ConnectionName(ctx, w.c, id)
		return live{name: name}, ok, err
	case KindTask:
		name, ok, err := w.b.d.Tasks.TaskName(ctx, w.c, id)
		return live{name: name}, ok, err
	case KindProject:
		name, ok, err := w.b.d.Projects.ProjectName(ctx, w.c, id)
		return live{name: name}, ok, err
	}
	return live{}, false, fmt.Errorf("bundle entity kind %q", kind)
}

func (w *workspace) refExists(ctx context.Context, kind EntityKind, id string) (bool, error) {
	_, ok, err := w.live(ctx, kind, id)
	return ok, err
}

func ownTrigger(triggers []catalogapi.BundleTrigger, name, agentID string, recorded *string) *string {
	for _, t := range triggers {
		if t.Name == name && t.AgentID == agentID && (recorded == nil || *recorded == t.ID) {
			id := t.ID
			return &id
		}
	}
	return nil
}

func (w *workspace) findTrigger(ctx context.Context, name, agentID string, recorded *string) (*string, error) {
	triggers, err := w.b.d.Triggers.Triggers(ctx)
	if err != nil {
		return nil, err
	}
	return ownTrigger(triggers, name, agentID, recorded), nil
}

func (w *workspace) findPolicy(ctx context.Context, p BundlePolicy, agentID *string) (*string, error) {
	if p.Subject == WorkspaceSubject {
		ws := w.c.Workspace.ID()
		agentID = &ws
	}
	if agentID == nil {
		return nil, nil
	}
	id, ok, err := w.b.d.Rules.MatchingRule(ctx, w.c, policyAsRule(p, *agentID))
	if err != nil || !ok {
		return nil, err
	}
	return &id, nil
}

func (w *workspace) streamNamed(ctx context.Context, name string) (*string, error) {
	id, ok, err := w.b.d.Streams.StreamNamed(ctx, name)
	if err != nil || !ok {
		return nil, err
	}
	return &id, nil
}

func (w *workspace) taskNamed(ctx context.Context, name string) ([]catalogapi.BundleTaskRef, error) {
	return w.b.d.Tasks.TaskNamed(ctx, w.c, name)
}

func (w *workspace) openAPIProblem(ctx context.Context, spec catalogapi.BundleOpenAPISpec) (string, error) {
	return w.b.d.OpenAPIs.OpenAPIProblem(ctx, w.c, spec)
}

func (w *workspace) streamProblem(ctx context.Context, spec catalogapi.BundleStreamSpec) (string, error) {
	return w.b.d.Streams.StreamProblem(ctx, spec)
}

func (w *workspace) channelCredentialKeys(ctx context.Context, id string) (map[string]bool, error) {
	creds, ok, err := w.b.d.Triggers.ChannelCredentials(ctx, id)
	if err != nil || !ok {
		return nil, err
	}
	out := make(map[string]bool, len(creds.Stored))
	for k, v := range creds.Stored {
		_, isRef := v.(map[string]any)
		out[k] = isRef
	}
	return out, nil
}

func (w *workspace) catalogMCP(ctx context.Context, catalogID string) (*catalogMCP, error) {
	if found, ok := w.catalogs[catalogID]; ok {
		return found, nil
	}
	var item store.CatalogMCPItem
	var ok bool
	err := w.b.read(ctx, w.c, func(sess db.Session) error {
		var err error
		item, ok, err = w.b.specs.CatalogMCPByExternalID(ctx, sess, catalogID)
		return err
	})
	if err != nil {
		return nil, err
	}
	var found *catalogMCP
	if ok {
		spec := ProjectCatalogMCPItem(item)
		found = &catalogMCP{SpecID: spec.ID}
		if t, ok := w.b.d.MCPs.SpecTransport(spec); ok {
			found.Transport = &t
		} else {
			w.b.d.Log.WarnContext(ctx, "Catalog server declares no transport", "catalog_id", catalogID)
		}
	}
	w.catalogs[catalogID] = found
	return found, nil
}

func int32Of(v *int64) *int32 {
	if v == nil {
		return nil
	}
	n := int32(*v)
	return &n
}

func (w *workspace) agentProblem(ctx context.Context, a BundleAgent, modelID string, clientID *string) (string, error) {
	problem, err := w.b.d.Agents.AgentProblem(ctx, w.c, catalogapi.BundleAgentConfig{ModelID: modelID, Toolsets: a.Toolsets,
		ClientID: clientID, ReasoningEffort: a.ReasoningEffort, ReasoningMaxTokens: int32Of(a.ReasoningMaxTokens)})
	if err != nil || problem != "" || a.ReasoningEffort == nil || *a.ReasoningEffort == "" || modelID == "" {
		return problem, err
	}
	m, err := w.b.d.Models.Model(ctx, modelsapi.Principal{WorkspaceID: w.c.Workspace.ID(), UserID: w.c.UserID}, modelID)
	switch {
	case errors.Is(err, modelsapi.ErrNotFound):
		return fmt.Sprintf("Model instance '%s' does not exist in this workspace.", modelID), nil
	case errors.Is(err, modelsapi.ErrRefused):
		return fmt.Sprintf("Model instance '%s' cannot be used: %s", modelID, err.Error()), nil
	case err != nil:
		return "", err
	}
	levels := m.ReasoningLevels
	if len(levels) == 0 {
		levels = m.Provider.ReasoningLevels
	}
	effort := *a.ReasoningEffort
	if len(levels) > 0 && !containsString(levels, effort) {
		return fmt.Sprintf("model %s takes reasoning_effort %s, not %s", m.ModelName, strings.Join(levels, ", "), effort), nil
	}
	return "", nil
}

func (w *workspace) isAdmin(ctx context.Context) (bool, error) {
	err := w.b.d.Admin(ctx)
	if errors.Is(err, authz.ErrNotWorkspaceAdmin) {
		return false, nil
	}
	return err == nil, err
}

func (w *workspace) members(ctx context.Context) ([]identityapi.Member, error) {
	if w.people == nil {
		found, err := w.b.d.Members.ListMembers(ctx, w.c)
		if err != nil {
			return nil, err
		}
		w.people = append([]identityapi.Member{}, found...)
	}
	return w.people, nil
}

func (w *workspace) billingCurrency() string { return w.b.d.ModelNames.BillingCurrency() }

const maxModelCandidates = 10

// modelID is ref when it is an id, else the one active chat instance named
// ref: by its own name first, then by its model's name.
func (w *workspace) modelID(ctx context.Context, ref string) (string, string, error) {
	if u, err := uuid.Parse(ref); err == nil {
		return u.String(), "", nil
	}
	if w.models == nil {
		found, err := w.b.d.ModelNames.ChatInstances(ctx, w.c.Workspace)
		if err != nil {
			return "", "", err
		}
		w.models = found
	}
	var byName, byModel []modelsapi.InstanceName
	for _, m := range w.models {
		if m.Name == ref {
			byName = append(byName, m)
		} else if m.ModelName == ref {
			byModel = append(byModel, m)
		}
	}
	matches := byName
	if len(matches) == 0 {
		matches = byModel
	}
	describe := func(l []modelsapi.InstanceName, withID bool) string {
		var parts []string
		for i, m := range l {
			if i == maxModelCandidates {
				parts = append(parts, fmt.Sprintf("and %d more", len(l)-i))
				break
			}
			if withID {
				parts = append(parts, fmt.Sprintf("'%s' (%s, %s)", m.Name, m.ModelName, m.ID))
			} else {
				parts = append(parts, fmt.Sprintf("'%s' (%s)", m.Name, m.ModelName))
			}
		}
		return strings.Join(parts, ", ")
	}
	switch len(matches) {
	case 1:
		return matches[0].ID, "", nil
	case 0:
		if len(w.models) == 0 {
			return "", fmt.Sprintf("model '%s' names no model instance: this workspace has no active chat model instance", ref), nil
		}
		return "", fmt.Sprintf("model '%s' names no active chat model instance in this workspace; the workspace has %s", ref, describe(w.models, false)), nil
	}
	return "", fmt.Sprintf("model '%s' names %d model instances here: %s; give the instance's id or a name only one of them has",
		ref, len(matches), describe(matches, true)), nil
}

func containsString(l []string, s string) bool {
	for _, x := range l {
		if x == s {
			return true
		}
	}
	return false
}

// automationSchedule is the trigger a creates: on its cron, or on streamID;
// running taskID when a runs a saved task.
func automationSchedule(b *Bundle, a BundleAutomation, agentID, streamID string, taskID *string) catalogapi.BundleSchedule {
	out := catalogapi.BundleSchedule{Name: triggerName(b, a.Key), Description: automationDescription(a), AgentID: agentID, Text: a.Prompt,
		Enabled: a.Enabled}
	if taskID != nil {
		out.TaskDefinitionID, out.Parameters, out.Text = taskID, plainObject(a.Parameters), ""
	}
	if a.On != nil {
		out.StreamID, out.Filter = &streamID, plainObject(a.On.Filter)
		return out
	}
	out.Cron, out.Timezone = a.Cron, a.Timezone
	return out
}

func automationDescription(a BundleAutomation) string {
	if a.On != nil {
		return fmt.Sprintf("Runs on stream %s", a.On.Stream)
	}
	return fmt.Sprintf("Runs %s (%s)", a.Cron, a.Timezone)
}

func (w *workspace) automationProblem(ctx context.Context, b *Bundle, a BundleAutomation) (string, error) {
	var task *string
	if a.Task != nil {
		task = strp(placeholderSubjectID)
	}
	return w.b.d.Triggers.ScheduleProblem(ctx, automationSchedule(b, a, placeholderSubjectID, placeholderSubjectID, task))
}

func editResourceType(kind EntityKind) string {
	return map[EntityKind]string{KindMCP: "mcp_instance", KindSkill: "skill", KindAgent: "agent", KindChannel: "trigger", KindAutomation: "trigger",
		KindStream: "stream", KindOpenAPI: "openapi_connection", KindTask: "task_definition"}[kind]
}

func (w *workspace) secretsDiffer(ctx context.Context, instanceID string, values map[string]string, contextSecret *string) (bool, error) {
	same, contextSame, err := w.b.d.MCPs.SecretsMatch(ctx, w.c, instanceID, values, contextSecret)
	if _, refused := refusalOf(err); refused {
		return true, nil
	}
	if err != nil {
		return false, err
	}
	for k := range values {
		if !same[k] {
			return true, nil
		}
	}
	return contextSecret != nil && !contextSame, nil // pragma: allowlist secret
}

func (w *workspace) specEditRefusal(ctx context.Context, instanceID string) (string, error) {
	specID, ok, err := w.b.d.MCPs.InstanceSpecID(ctx, w.c, instanceID)
	if err != nil {
		return "", err
	}
	if !ok {
		return fmt.Sprintf("its instance %s is gone", instanceID), nil
	}
	allowed, err := w.b.d.MayEdit(ctx, w.c, "mcp_server", specID)
	if err != nil || allowed {
		return "", err
	}
	return "you may not edit its MCP server spec " + specID, nil
}

func (w *workspace) mayEdit(ctx context.Context, kind EntityKind, id string) (bool, error) {
	return w.b.d.MayEdit(ctx, w.c, editResourceType(kind), id)
}

func (w *workspace) secretProblem(ctx context.Context, name string) (string, error) {
	problem, err := w.b.d.MCPs.SecretProblem(ctx, w.c, name)
	if err != nil || problem == "" {
		return "", err
	}
	return "is refused: " + problem, nil
}

func (b *Bundles) read(ctx context.Context, c authn.Caller, fn func(db.Session) error) error {
	sess, release, err := b.d.DB.Read(ctx, c.Workspace)
	if err != nil {
		return err
	}
	defer release()
	return fn(sess)
}

// BundleOrigin is where a deployed folder came from, as the CLI reports it: shown, never checked.
type BundleOrigin struct{ GitRemote, GitCommit, Path *string }

func (o *BundleOrigin) object() wirejson.Object {
	if o == nil {
		return nil
	}
	out := wirejson.Object{}
	for _, f := range []struct {
		key string
		v   *string
	}{{"git_remote", o.GitRemote}, {"git_commit", o.GitCommit}, {"path", o.Path}} {
		if f.v != nil {
			out.Set(f.key, *f.v)
		}
	}
	return out
}

// BundleTarget is the install a deploy updates: Into names it by id, or by
// the name of exactly one install. Without it the bundle's name must be free.
type BundleTarget struct {
	Into   *string
	Origin *BundleOrigin
}

// AnalyzeText is analyze_text: source text into a bundle, then its plan.
func (b *Bundles) AnalyzeText(ctx context.Context, text string, setup wirejson.Object, target BundleTarget) (ImportPreview, error) {
	pkg, err := ParseBundle(text)
	if err != nil {
		return ImportPreview{}, err
	}
	return b.AnalyzeBundle(ctx, pkg, setup, false, target)
}

// AnalyzeFiles is analyze_files: a bundle folder into a bundle, then its plan,
// blocking on required setup without a value.
func (b *Bundles) AnalyzeFiles(ctx context.Context, files StrPairs, setup wirejson.Object, target BundleTarget) (ImportPreview, error) {
	pkg, folderIssues, err := LoadBundleFolder(files)
	if err != nil {
		return ImportPreview{}, err
	}
	p, err := b.AnalyzeBundle(ctx, pkg, setup, true, target)
	if err != nil {
		return ImportPreview{}, err
	}
	p.Issues = append(folderIssues, p.Issues...)
	return p, nil
}

// AnalyzeBundle plans the install; reportMissingSetup also blocks on required setup with no value.
func (b *Bundles) AnalyzeBundle(ctx context.Context, pkg Bundle, setup wirejson.Object, reportMissingSetup bool, target BundleTarget) (ImportPreview, error) {
	w, err := b.workspace(ctx)
	if err != nil {
		return ImportPreview{}, err
	}
	t, err := b.target(ctx, w.c, pkg.Name, target.Into)
	if err != nil {
		return ImportPreview{}, err
	}
	if t.issue != nil {
		return ImportPreview{Bundle: pkg, Setup: pkg.Setup, Issues: []PreviewIssue{*t.issue}, ExistingInstall: t.existing}, nil
	}
	a, unreadable, err := b.analyzer(ctx, w, t, &pkg, setup)
	if err != nil {
		return ImportPreview{}, err
	}
	if unreadable != nil {
		return ImportPreview{Bundle: pkg, Setup: pkg.Setup, Issues: []PreviewIssue{*unreadable}, Install: t.summary}, nil
	}
	p, err := a.analyze(ctx, &pkg)
	if err != nil {
		return ImportPreview{}, err
	}
	p.Install = t.summary
	if reportMissingSetup {
		if missing := requiredSetupErrors(&pkg, effectiveSetup(&pkg, setup, a.prior), a.neededSetup); len(missing) > 0 {
			p.Issues = append(p.Issues, missing...)
			p.Installable = false
		}
	}
	return p, nil
}

// deployTarget is the install a deploy updates, or why it has none to update.
type deployTarget struct {
	row      *store.BundleRow
	summary  *InstallSummary
	issue    *PreviewIssue
	existing *InstallSummary
}

func codeIssue(code, msg string) *PreviewIssue {
	return &PreviewIssue{Severity: SeverityBlock, Message: msg, Code: &code}
}

func summaryOf(r store.BundleRow) (*InstallSummary, error) {
	var origin any
	if len(r.Source) > 0 {
		v, err := wirejson.Unmarshal(r.Source)
		if err != nil {
			return nil, fmt.Errorf("installed bundle %s: source: %w", r.ID, err)
		}
		origin = v
	}
	return &InstallSummary{ID: r.ID, Name: r.Name, CreatedBy: r.CreatedBy, UpdatedBy: r.UpdatedBy, UpdatedAt: r.UpdatedAt, Origin: origin}, nil
}

func lastDeployed(r store.BundleRow) string {
	by := r.CreatedBy
	if r.UpdatedBy != nil && *r.UpdatedBy != "" {
		by = *r.UpdatedBy
	}
	return fmt.Sprintf("last deployed by %s at %s", by, isoUTC(r.UpdatedAt))
}

// target resolves into, or the bundle's name when into is nil.
func (b *Bundles) target(ctx context.Context, c authn.Caller, name string, into *string) (deployTarget, error) {
	var t deployTarget
	var taken []store.BundleRow
	err := b.read(ctx, c, func(sess db.Session) error {
		if into == nil {
			var err error
			taken, err = b.rows.ByName(ctx, sess, name)
			return err
		}
		ref := pyStrip(*into)
		row, ok, err := b.rows.ByID(ctx, sess, ref)
		if err != nil {
			return err
		}
		if !ok {
			rows, err := b.rows.ByName(ctx, sess, ref)
			if err != nil {
				return err
			}
			switch len(rows) {
			case 0:
				t.issue = codeIssue(CodeInstallNotFound, fmt.Sprintf("bundle install %s not found; it was deleted — deploy without --into to create it again", ref))
				return nil
			case 1:
				row = rows[0]
			default:
				ids := make([]string, len(rows))
				for i, r := range rows {
					ids[i] = r.ID
				}
				t.issue = codeIssue(CodeInstallAmbiguous, fmt.Sprintf("%d bundle installs are named '%s' (%s); deploy --into one of their ids",
					len(rows), ref, strings.Join(ids, ", ")))
				return nil
			}
		}
		t.row = &row
		if row.Name == name {
			return nil
		}
		others, err := b.rows.ByName(ctx, sess, name)
		for _, r := range others {
			if r.ID != row.ID {
				taken = append(taken, r)
			}
		}
		return err
	})
	if err != nil {
		return deployTarget{}, err
	}
	if t.row != nil {
		if t.summary, err = summaryOf(*t.row); err != nil {
			return deployTarget{}, err
		}
	}
	if len(taken) > 0 {
		if t.existing, err = summaryOf(taken[0]); err != nil {
			return deployTarget{}, err
		}
		msg := fmt.Sprintf("bundle '%s' is already installed in this workspace as install %s (%s); deploy --into %s to update it, or give the bundle another name",
			name, taken[0].ID, lastDeployed(taken[0]), taken[0].ID)
		if t.row != nil {
			msg = fmt.Sprintf("renaming install %s to '%s' would give it the name of install %s (%s); choose another name",
				t.row.ID, name, taken[0].ID, lastDeployed(taken[0]))
		}
		t.issue = codeIssue(CodeBundleExists, msg)
	}
	return t, nil
}

// analyzer plans against the target install and the workspace's other installs;
// a record that no longer validates is a blocking issue, never "no prior install".
func (b *Bundles) analyzer(ctx context.Context, w *workspace, t deployTarget, pkg *Bundle, setup wirejson.Object) (*bundleAnalyzer, *PreviewIssue, error) {
	a := &bundleAnalyzer{existence: w, checks: w, shapes: b.shapes(), supplied: setup}
	var results []store.BundleResult
	if err := b.read(ctx, w.c, func(sess db.Session) error {
		var err error
		results, err = b.rows.Results(ctx, sess)
		return err
	}); err != nil {
		return nil, nil, err
	}
	own := ""
	if t.row != nil {
		own = t.row.ID
	}
	others, unreadable, err := othersOf(ctx, b.d.Log, results, own, pkg)
	if err != nil || unreadable != nil {
		return nil, unreadable, err
	}
	a.others = others
	if t.row == nil {
		return a, nil, nil
	}
	prior, unreadable, err := b.prior(ctx, *t.row)
	if err != nil || unreadable != nil {
		return nil, unreadable, err
	}
	a.prior, a.revision = prior, &installRevision{id: t.row.ID, updatedAt: isoUTC(t.row.UpdatedAt)}
	return a, nil, nil
}

// othersOf are the workspace's installs but own, with what they own. A record
// that no longer validates is skipped and logged, unless an entity name it
// still carries is one this bundle declares: then nothing is planned.
func othersOf(ctx context.Context, log *slog.Logger, results []store.BundleResult, own string, pkg *Bundle) ([]otherInstall, *PreviewIssue, error) {
	var out []otherInstall
	for _, r := range results {
		if r.ID == own {
			continue
		}
		result := InstallResult{BundleName: r.Name}
		if len(r.InstallResult) > 0 {
			raw, err := wirejson.Unmarshal(r.InstallResult)
			if err != nil {
				return nil, nil, fmt.Errorf("installed bundle %s: install_result: %w", r.ID, err)
			}
			if raw != nil {
				var c checker
				var valid bool
				if result, valid = installResultFrom(&c, raw); !valid {
					log.ErrorContext(ctx, "Stored install of bundle no longer validates", "install", r.ID, "errors", validationText("InstallResult", c.errs))
					if !namesOverlap(raw, pkg) {
						continue
					}
					return nil, &PreviewIssue{Severity: SeverityBlock, Message: fmt.Sprintf("the record of install %s ('%s') no longer validates "+
						"(%d errors) and names what this bundle declares, so what it owns cannot be told apart from this bundle; nothing is planned",
						r.ID, r.Name, len(c.errs))}, nil
				}
			}
		}
		out = append(out, otherInstall{id: r.ID, name: r.Name, result: result})
	}
	return out, nil, nil
}

// namesOverlap reports an entity name in a raw install record that pkg also declares.
func namesOverlap(raw any, pkg *Bundle) bool {
	declared := map[string]bool{}
	for _, m := range pkg.MCPs {
		declared[m.Name] = true
	}
	for _, s := range pkg.Skills {
		declared[s.Name] = true
	}
	for _, a := range pkg.Agents {
		declared[a.Name] = true
	}
	o, _ := raw.(wirejson.Object)
	entities, _ := o.Get("entities")
	list, _ := entities.([]any)
	for _, e := range list {
		eo, _ := e.(wirejson.Object)
		if name, _ := eo.Get("name"); declared[pyStr(name)] {
			return true
		}
	}
	return false
}

// prior is what the install row last declared and created.
func (b *Bundles) prior(ctx context.Context, row store.BundleRow) (*priorInstall, *PreviewIssue, error) {
	canonical, err := wirejson.Unmarshal(row.Canonical)
	if err != nil {
		return nil, nil, fmt.Errorf("installed bundle %s: canonical: %w", row.ID, err)
	}
	var c1 checker
	pkg, valid := bundleFrom(&c1, canonical, nil)
	result := InstallResult{BundleName: pkg.Name, SetupValues: wirejson.Object{}}
	if valid && len(row.InstallResult) > 0 {
		raw, err := wirejson.Unmarshal(row.InstallResult)
		if err != nil {
			return nil, nil, fmt.Errorf("installed bundle %s: install_result: %w", row.ID, err)
		}
		if raw != nil {
			result, valid = installResultFrom(&c1, raw)
		}
	}
	if !valid {
		b.d.Log.ErrorContext(ctx, "Stored install of bundle no longer validates", "bundle", row.Name, "errors", validationText("Bundle", c1.errs))
		return nil, &PreviewIssue{Severity: SeverityBlock, Message: fmt.Sprintf("the record of the last install of '%s' no longer validates "+
			"(%d errors), so what it created cannot be matched; nothing is planned", row.Name, len(c1.errs))}, nil
	}
	return &priorInstall{bundle: pkg, result: result}, nil, nil
}

func blockedMessage(block []PreviewIssue) string {
	msg := "package is not installable: " + block[0].Message
	if len(block) > 1 {
		msg += fmt.Sprintf(" (and %d more)", len(block)-1)
	}
	return msg
}

func planChanged(msg string, issues ...PreviewIssue) *BundleError {
	return &BundleError{Kind: BundlePlanChanged, Msg: msg, Issues: issues}
}

// installLockKey is the advisory lock one bundle name's deploys take in turn.
func installLockKey(workspaceID, name string) db.LockKey {
	return db.TextKey("bundle-install:" + workspaceID + ":" + name)
}

// Install plans the deploy again, refuses a plan other than the approved one
// or anything it blocks, then writes it and records what it did. target.Into
// is the install id the plan was made for; the digest names it and its
// revision. A deploy holds the bundle name's lock from the plan check to the
// record, so a second deploy of the name, first installs included, is refused
// while one runs. The MCPs' tools are discovered again once it committed.
func (b *Bundles) Install(ctx context.Context, pkg Bundle, setup wirejson.Object, digest string, target BundleTarget) (InstallResult, error) {
	w, err := b.workspace(ctx)
	if err != nil {
		return InstallResult{}, err
	}
	var result InstallResult
	var in *bundleInstaller
	var conflict error
	err = b.d.DB.Write(ctx, w.c.Workspace, func(ctx context.Context, sess db.Session) error {
		held, err := db.TryXactLock(ctx, sess.Q(), installLockKey(w.c.Workspace.ID(), pkg.Name))
		if err != nil {
			return err
		}
		if !held {
			return &BundleError{Kind: BundleDeployRunning, Msg: "a deploy of this bundle is running; try again when it finishes"}
		}
		record := func(ctx context.Context, fn func(context.Context, db.Session) error) error { return fn(ctx, sess) }
		result, in, conflict, err = b.install(ctx, w, record, pkg, setup, digest, target)
		return err
	})
	if err != nil {
		return InstallResult{}, err
	}
	if conflict != nil {
		return InstallResult{}, conflict
	}
	in.rediscoverMCPs(ctx, &result)
	return result, nil
}

// recorder runs a write of the install row: in the deploy's own transaction, or one of its own.
type recorder func(ctx context.Context, fn func(context.Context, db.Session) error) error

// install is Install under the lock; conflict is the 409 of a record that
// had to be kept over a newer revision, returned once that record committed.
func (b *Bundles) install(ctx context.Context, w *workspace, record recorder, pkg Bundle, setup wirejson.Object, digest string,
	target BundleTarget) (result InstallResult, in *bundleInstaller, conflict, err error) {
	result, in, err = b.installLocked(ctx, w, record, pkg, setup, digest, target)
	if err != nil || in == nil {
		return InstallResult{}, nil, nil, err
	}
	id, stale, err := b.recordID(ctx, record, w.c, &pkg, result, "installed", in.row, target.Origin)
	if err != nil {
		return InstallResult{}, nil, nil, err
	}
	if stale {
		return InstallResult{}, nil, planChanged(fmt.Sprintf("install %s was deployed by someone else while this deploy ran; both deploys' "+
			"entities are recorded (status conflict); analyze the bundle again and review the new plan", id)), nil
	}
	result.InstalledBundleID = &id
	return result, in, nil, nil
}

func (b *Bundles) installLocked(ctx context.Context, w *workspace, record recorder, pkg Bundle, setup wirejson.Object, digest string,
	target BundleTarget) (InstallResult, *bundleInstaller, error) {
	t, err := b.target(ctx, w.c, pkg.Name, target.Into)
	if err != nil {
		return InstallResult{}, nil, err
	}
	if t.issue != nil {
		return InstallResult{}, nil, planChanged(t.issue.Message+"; analyze the bundle again and review the new plan", *t.issue)
	}
	a, unreadable, err := b.analyzer(ctx, w, t, &pkg, setup)
	if err != nil {
		return InstallResult{}, nil, err
	}
	if unreadable != nil {
		return InstallResult{}, nil, invalidError(unreadable.Message, *unreadable)
	}
	preview, err := a.analyze(ctx, &pkg)
	if err != nil {
		return InstallResult{}, nil, err
	}
	if preview.PlanDigest == nil || *preview.PlanDigest != digest {
		return InstallResult{}, nil, planChanged("the deploy plan changed since it was shown; analyze the bundle again and review the new plan")
	}
	prior := a.prior
	values := effectiveSetup(&pkg, setup, prior)
	block := append(append(preview.Blocks(), requiredSetupErrors(&pkg, values, a.neededSetup)...), contextSecretErrors(b.shapes(), &pkg, values)...)
	if len(block) > 0 {
		return InstallResult{}, nil, invalidError(blockedMessage(block), block...)
	}
	approved := map[entityRef]bool{}
	writesPolicies := false
	for _, e := range preview.Entities {
		if e.Status == StatusWillUpdate {
			approved[entityRef{e.Kind, e.Key}] = true
		}
		writesPolicies = writesPolicies || e.Kind == KindPolicy && writes(e.Status)
	}
	in := &bundleInstaller{w: w, approved: approved, row: t.row}
	result, err := in.install(ctx, &pkg, setup, prior, &writesPolicies)
	if err != nil {
		if in.updatedInPlace {
			own := func(ctx context.Context, fn func(context.Context, db.Session) error) error {
				return b.d.DB.Write(ctx, w.c.Workspace, fn)
			}
			if rerr := b.recordPartial(context.WithoutCancel(ctx), own, w.c, &pkg, in, t.row, target.Origin); rerr != nil {
				b.d.Log.ErrorContext(ctx, "Could not record the failed redeploy of bundle", "bundle", pkg.Name, "error", rerr)
			}
		}
		return InstallResult{}, nil, err
	}
	return result, in, nil
}

// recordID writes the install row: the target's when the deploy updated one,
// else a new one. Over a row written since the deploy read it, it keeps both
// deploys' entities under status "conflict" and reports stale: what either
// created stays tracked, the next plan sees all of it.
func (b *Bundles) recordID(ctx context.Context, record recorder, c authn.Caller, pkg *Bundle, result InstallResult, status string,
	row *store.BundleRow, origin *BundleOrigin) (id string, stale bool, err error) {
	canonical, err := wirejson.Marshal(pkg.Dump(), wirejson.Compact)
	if err != nil {
		return "", false, err
	}
	encode := func(result InstallResult, status string) (store.BundleRecord, error) {
		installResult, err := wirejson.Marshal(result.Dump(), wirejson.Compact)
		if err != nil {
			return store.BundleRecord{}, err
		}
		r := store.BundleRecord{Name: pkg.Name, DisplayName: pkg.DisplayName, Description: pkg.Description,
			SchemaVersion: pkg.SchemaVersion, Status: status, Canonical: canonical, InstallResult: installResult}
		if o := origin.object(); o != nil {
			if r.Source, err = wirejson.Marshal(o, wirejson.Compact); err != nil {
				return store.BundleRecord{}, err
			}
		}
		return r, nil
	}
	r, err := encode(result, status)
	if err != nil {
		return "", false, err
	}
	err = record(ctx, func(ctx context.Context, sess db.Session) error {
		if row == nil {
			var err error
			id, err = b.rows.Insert(ctx, sess, c.UserID, r, b.d.Now().UTC())
			return err
		}
		id = row.ID
		seen := row.UpdatedAt
		ok, err := b.rows.Update(ctx, sess, row.ID, c.UserID, &seen, r, b.d.Now().UTC())
		if err != nil || ok {
			return err
		}
		current, found, err := b.rows.ByID(ctx, sess, row.ID)
		if err != nil || !found {
			return err
		}
		merged := result
		if theirs, unreadable, err := b.prior(ctx, current); err == nil && unreadable == nil && theirs != nil {
			merged = mergedResults(result, theirs.result)
		}
		if r, err = encode(merged, "conflict"); err != nil {
			return err
		}
		stale = true
		_, err = b.rows.Update(ctx, sess, row.ID, c.UserID, nil, r, b.d.Now().UTC())
		return err
	})
	return id, stale, err
}

// mergedResults is ours plus what theirs recorded that ours did not: an
// entity theirs created under a key ours also wrote, with another id, stays as an orphan.
func mergedResults(ours, theirs InstallResult) InstallResult {
	out := ours
	out.Entities = append([]InstalledEntity{}, ours.Entities...)
	for _, e := range theirs.Entities {
		var mine *InstalledEntity
		for i := range ours.Entities {
			if ours.Entities[i].Kind == e.Kind && ours.Entities[i].Key == e.Key {
				mine = &ours.Entities[i]
			}
		}
		switch {
		case mine == nil:
			out.Entities = append(out.Entities, e)
		case hasID(e) && !sameID(mine.ID, e.ID):
			detail := "recorded by a concurrent deploy; left in place, not deleted"
			e.Action, e.Detail = ActionOrphaned, &detail
			out.Entities = append(out.Entities, e)
		}
	}
	return out
}

func (b *Bundles) recordPartial(ctx context.Context, record recorder, c authn.Caller, pkg *Bundle, in *bundleInstaller, row *store.BundleRow,
	origin *BundleOrigin) error {
	partial, err := in.partialResult()
	if err != nil {
		return err
	}
	_, _, err = b.recordID(ctx, record, c, pkg, partial, "failed", row, origin)
	return err
}
