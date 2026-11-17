package service

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"strings"
	"time"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx/wirejson"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/netguard"
	catalogapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/catalog/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/catalog/store"
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
	Triggers catalogapi.BundleTriggers
	Rules    catalogapi.BundleRules
	// Models resolves the model an agent runs, for the reasoning levels it takes.
	Models modelsapi.Resolver
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
	}{{"database", d.DB != nil}, {"agents", d.Agents != nil}, {"MCP connections", d.MCPs != nil}, {"triggers", d.Triggers != nil},
		{"policy rules", d.Rules != nil}, {"models", d.Models != nil}, {"edit check", d.MayEdit != nil}, {"workspace admin", d.Admin != nil}} {
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
	agents catalogapi.BundleAgents
	mcps   catalogapi.BundleMCPs
	rules  catalogapi.BundleRules
}

func (p portShapes) SkillProblem(content string) string { return p.agents.SkillProblem(content) }
func (p portShapes) SkillMainFile(paths []string) (string, bool) {
	return p.agents.SkillMainFile(paths)
}
func (p portShapes) CarriesSecretRef(v any) bool                 { return p.mcps.CarriesSecretRef(v) }
func (p portShapes) RuleProblem(r catalogapi.BundleRule) string  { return p.rules.RuleProblem(r) }
func (p portShapes) ContextSecretLength() (minimum, maximum int) { return p.mcps.ContextSecretLength() }

func (b *Bundles) shapes() bundleShapes {
	return portShapes{agents: b.d.Agents, mcps: b.d.MCPs, rules: b.d.Rules}
}

// workspace answers a deploy's existence and write questions for one caller.
type workspace struct {
	b        *Bundles
	c        authn.Caller
	catalogs map[string]*catalogMCP
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
	subjectID := w.c.Workspace.ID()
	if p.Subject != "workspace" {
		if agentID == nil {
			return nil, nil
		}
		subjectID = *agentID
	}
	id, ok, err := w.b.d.Rules.MatchingRule(ctx, w.c, policyAsRule(p, subjectID))
	if err != nil || !ok {
		return nil, err
	}
	return &id, nil
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

func containsString(l []string, s string) bool {
	for _, x := range l {
		if x == s {
			return true
		}
	}
	return false
}

func automationCron(b *Bundle, a BundleAutomation, agentID string) catalogapi.BundleCron {
	return catalogapi.BundleCron{Name: triggerName(b, a.Key), Description: fmt.Sprintf("Runs %s (%s)", a.Cron, a.Timezone),
		AgentID: agentID, Cron: a.Cron, Timezone: a.Timezone, Text: a.Prompt, Enabled: a.Enabled}
}

func (w *workspace) automationProblem(ctx context.Context, b *Bundle, a BundleAutomation) (string, error) {
	return w.b.d.Triggers.CronProblem(ctx, automationCron(b, a, placeholderSubjectID))
}

func editResourceType(kind EntityKind) string {
	return map[EntityKind]string{KindSkill: "skill", KindAgent: "agent", KindChannel: "trigger", KindAutomation: "trigger"}[kind]
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

// AnalyzeText is analyze_text: source text into a bundle, then its plan.
func (b *Bundles) AnalyzeText(ctx context.Context, text string, setup wirejson.Object) (ImportPreview, error) {
	pkg, err := ParseBundle(text)
	if err != nil {
		return ImportPreview{}, err
	}
	return b.AnalyzeBundle(ctx, pkg, setup, false)
}

// AnalyzeFiles is analyze_files: an agent folder into a bundle, then its plan,
// blocking on required setup without a value.
func (b *Bundles) AnalyzeFiles(ctx context.Context, files StrPairs, setup wirejson.Object) (ImportPreview, error) {
	pkg, folderIssues, err := LoadBundleFolder(files)
	if err != nil {
		return ImportPreview{}, err
	}
	p, err := b.AnalyzeBundle(ctx, pkg, setup, true)
	if err != nil {
		return ImportPreview{}, err
	}
	p.Issues = append(folderIssues, p.Issues...)
	return p, nil
}

// AnalyzeBundle plans the install; reportMissingSetup also blocks on required setup with no value.
func (b *Bundles) AnalyzeBundle(ctx context.Context, pkg Bundle, setup wirejson.Object, reportMissingSetup bool) (ImportPreview, error) {
	w, err := b.workspace(ctx)
	if err != nil {
		return ImportPreview{}, err
	}
	prior, unreadable, err := b.prior(ctx, w.c, pkg.Name)
	if err != nil {
		return ImportPreview{}, err
	}
	if unreadable != nil {
		return ImportPreview{Bundle: pkg, Setup: pkg.Setup, Issues: []PreviewIssue{*unreadable}}, nil
	}
	a := &bundleAnalyzer{existence: w, prior: prior, checks: w, shapes: b.shapes(), supplied: setup}
	p, err := a.analyze(ctx, &pkg)
	if err != nil {
		return ImportPreview{}, err
	}
	if reportMissingSetup {
		if missing := requiredSetupErrors(&pkg, effectiveSetup(&pkg, setup, prior), a.neededSetup); len(missing) > 0 {
			p.Issues = append(p.Issues, missing...)
			p.Installable = false
		}
	}
	return p, nil
}

// prior is the last install of the bundle in the workspace; a record that no
// longer validates is a blocking issue, never "no prior install".
func (b *Bundles) prior(ctx context.Context, c authn.Caller, name string) (*priorInstall, *PreviewIssue, error) {
	var row store.BundleRow
	var ok bool
	if err := b.read(ctx, c, func(sess db.Session) error {
		var err error
		row, ok, err = b.rows.ByName(ctx, sess, name)
		return err
	}); err != nil || !ok {
		return nil, nil, err
	}
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
		b.d.Log.ErrorContext(ctx, "Stored install of bundle no longer validates", "bundle", name, "errors", validationText("Bundle", c1.errs))
		return nil, &PreviewIssue{Severity: SeverityBlock, Message: fmt.Sprintf("the record of the last install of '%s' no longer validates "+
			"(%d errors), so what it created cannot be matched; nothing is planned", name, len(c1.errs))}, nil
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

// Install plans the deploy again, refuses a plan other than the approved one
// or anything it blocks, then writes it and records what it did.
func (b *Bundles) Install(ctx context.Context, pkg Bundle, setup wirejson.Object, digest string) (InstallResult, error) {
	w, err := b.workspace(ctx)
	if err != nil {
		return InstallResult{}, err
	}
	prior, unreadable, err := b.prior(ctx, w.c, pkg.Name)
	if err != nil {
		return InstallResult{}, err
	}
	if unreadable != nil {
		return InstallResult{}, invalidError(unreadable.Message, *unreadable)
	}
	a := &bundleAnalyzer{existence: w, prior: prior, checks: w, shapes: b.shapes(), supplied: setup}
	preview, err := a.analyze(ctx, &pkg)
	if err != nil {
		return InstallResult{}, err
	}
	if preview.PlanDigest == nil || *preview.PlanDigest != digest {
		return InstallResult{}, &BundleError{Kind: BundlePlanChanged,
			Msg: "the deploy plan changed since it was shown; analyze the bundle again and review the new plan"}
	}
	values := effectiveSetup(&pkg, setup, prior)
	block := append(append(preview.Blocks(), requiredSetupErrors(&pkg, values, a.neededSetup)...), contextSecretErrors(b.shapes(), &pkg, values)...)
	if len(block) > 0 {
		return InstallResult{}, invalidError(blockedMessage(block), block...)
	}
	approved := map[entityRef]bool{}
	writesPolicies := false
	for _, e := range preview.Entities {
		if e.Status == StatusWillUpdate {
			approved[entityRef{e.Kind, e.Key}] = true
		}
		writesPolicies = writesPolicies || e.Kind == KindPolicy && writes(e.Status)
	}
	in := &bundleInstaller{w: w, approved: approved}
	result, err := in.install(ctx, &pkg, setup, prior, &writesPolicies)
	if err != nil {
		if in.updatedInPlace {
			if rerr := b.recordPartial(context.WithoutCancel(ctx), w.c, &pkg, in); rerr != nil {
				b.d.Log.ErrorContext(ctx, "Could not record the failed redeploy of bundle", "bundle", pkg.Name, "error", rerr)
			}
		}
		return InstallResult{}, err
	}
	id, err := b.recordID(ctx, w.c, &pkg, result, "installed")
	if err != nil {
		return InstallResult{}, err
	}
	result.InstalledBundleID = &id
	return result, nil
}

func (b *Bundles) record(ctx context.Context, c authn.Caller, pkg *Bundle, result InstallResult, status string) error {
	_, err := b.recordID(ctx, c, pkg, result, status)
	return err
}

// recordID upserts the installed_bundles row of the bundle, by name.
func (b *Bundles) recordID(ctx context.Context, c authn.Caller, pkg *Bundle, result InstallResult, status string) (string, error) {
	canonical, err := wirejson.Marshal(pkg.Dump(), wirejson.Compact)
	if err != nil {
		return "", err
	}
	installResult, err := wirejson.Marshal(result.Dump(), wirejson.Compact)
	if err != nil {
		return "", err
	}
	r := store.BundleRecord{Name: pkg.Name, DisplayName: pkg.DisplayName, Description: pkg.Description,
		SchemaVersion: pkg.SchemaVersion, Status: status, Canonical: canonical, InstallResult: installResult}
	var id string
	err = b.d.DB.Write(ctx, c.Workspace, func(ctx context.Context, sess db.Session) error {
		existing, ok, err := b.rows.ByName(ctx, sess, pkg.Name)
		if err != nil {
			return err
		}
		if ok {
			id = existing.ID
			return b.rows.Update(ctx, sess, existing.ID, r, b.d.Now().UTC())
		}
		id, err = b.rows.Insert(ctx, sess, c.UserID, r, b.d.Now().UTC())
		return err
	})
	return id, err
}

func (b *Bundles) recordPartial(ctx context.Context, c authn.Caller, pkg *Bundle, in *bundleInstaller) error {
	partial, err := in.partialResult()
	if err != nil {
		return err
	}
	return b.record(ctx, c, pkg, partial, "failed")
}
