package service

import (
	"context"
	"fmt"
	"net/url"
	"sort"
	"strings"
	"unicode/utf8"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx/wirejson"
	catalogapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/catalog/api"
)

const (
	mcpNotApplied         = "changes not applied: MCP servers are not updated on redeploy yet"
	githubSkillNotApplied = "changes not applied: a GitHub skill is not re-imported on redeploy"
	orphanedDetail        = "removed from the bundle; left in place, not deleted"
	notYetCreated         = "<created by this deploy>"
	placeholderSubjectID  = "00000000-0000-0000-0000-000000000000"
	maxSkillErrorLength   = 300
	maxContextSecretLen   = 512
)

func supportedCommands() []string {
	return []string{"bunx", "deno", "node", "npx", "python", "python3", "uv", "uvx"}
}

func editGuarded() []EntityKind {
	return []EntityKind{KindSkill, KindAgent, KindChannel, KindAutomation}
}

func ownedAction(a InstallAction) bool {
	switch a {
	case ActionCreated, ActionUpdated, ActionUnchanged, ActionOrphaned, ActionSkipped:
		return true
	case ActionReused:
		return false
	}
	return false
}

func linkedAction(a InstallAction) bool {
	switch a {
	case ActionCreated, ActionUpdated, ActionUnchanged, ActionReused:
		return true
	case ActionOrphaned, ActionSkipped:
		return false
	}
	return false
}

func writes(s EntityStatus) bool { return s == StatusWillCreate || s == StatusWillUpdate }

type bundleSpec interface {
	specKey() string
	dump() wirejson.Object
}

func (m BundleMCP) specKey() string        { return m.Key }
func (s BundleSkill) specKey() string      { return s.Key }
func (a BundleAgent) specKey() string      { return a.Key }
func (ch BundleChannel) specKey() string   { return ch.Key }
func (a BundleAutomation) specKey() string { return a.Key }
func (p BundlePolicy) specKey() string     { return p.Key }

func specsOf[T bundleSpec](items []T) []bundleSpec {
	out := make([]bundleSpec, len(items))
	for i, x := range items {
		out[i] = x
	}
	return out
}

func bundleEntities(b *Bundle, kind EntityKind) []bundleSpec {
	switch kind {
	case KindMCP:
		return specsOf(b.MCPs)
	case KindSkill:
		return specsOf(b.Skills)
	case KindAgent:
		return specsOf(b.Agents)
	case KindChannel:
		return specsOf(b.Channels)
	case KindAutomation:
		return specsOf(b.Automations)
	case KindPolicy:
		return specsOf(b.Policies)
	}
	return nil
}

func triggerName(b *Bundle, key string) string { return b.Name + ":" + key }

func resolveTree(v any, values wirejson.Object) any {
	switch x := v.(type) {
	case string:
		return resolvePlaceholders(x, values)
	case wirejson.Object:
		out := make(wirejson.Object, len(x))
		for i, m := range x {
			out[i] = wirejson.Member{Key: m.Key, Value: resolveTree(m.Value, values)}
		}
		return out
	case []any:
		out := make([]any, len(x))
		for i, e := range x {
			out[i] = resolveTree(e, values)
		}
		return out
	}
	return v
}

func secretKeys(b *Bundle) map[string]bool {
	out := map[string]bool{}
	for _, f := range b.Setup {
		if f.Type == SetupSecret {
			out[f.Key] = true
		}
	}
	return out
}

// given is a setup value that counts as supplied: not missing, not a blank string.
func given(v any) bool {
	if v == nil {
		return false
	}
	if s, ok := v.(string); ok {
		return pyStrip(s) != ""
	}
	return true
}

func suppliedKeys(supplied wirejson.Object) map[string]bool {
	out := map[string]bool{}
	for _, m := range supplied {
		if given(m.Value) {
			out[m.Key] = true
		}
	}
	return out
}

// effectiveSetup is the setup in force: defaults, then remembered values, then supplied ones.
func effectiveSetup(b *Bundle, supplied wirejson.Object, prior *priorInstall) wirejson.Object {
	values := wirejson.Object{}
	for _, f := range b.Setup {
		if given(f.Default) {
			values.Set(f.Key, f.Default)
		}
	}
	for _, m := range rememberedSetup(b, nil, prior) {
		values.Set(m.Key, m.Value)
	}
	for _, m := range supplied {
		if given(m.Value) {
			values.Set(m.Key, m.Value)
		}
	}
	return values
}

// rememberedSetup is the non-secret values supplied to this and earlier installs.
func rememberedSetup(b *Bundle, supplied wirejson.Object, prior *priorInstall) wirejson.Object {
	secret := secretKeys(b)
	public := map[string]bool{}
	for _, f := range b.Setup {
		if !secret[f.Key] {
			public[f.Key] = true
		}
	}
	merged := wirejson.Object{}
	if prior != nil {
		merged = append(merged, prior.result.SetupValues...)
	}
	for _, m := range supplied {
		merged.Set(m.Key, m.Value)
	}
	out := wirejson.Object{}
	for _, m := range merged {
		if public[m.Key] && given(m.Value) {
			out = append(out, m)
		}
	}
	return out
}

// specFingerprint is sha256 of spec with its non-secret setup placeholders resolved.
func specFingerprint(b *Bundle, spec bundleSpec, values wirejson.Object) (string, error) {
	secret := secretKeys(b)
	public := wirejson.Object{}
	for _, m := range values {
		if !secret[m.Key] {
			public = append(public, m)
		}
	}
	return sha256Dumps(resolveTree(spec.dump(), public))
}

// channelCredentials are the channel's bound credentials that resolve fully
// from values; with supplied, only those whose setup keys were all given.
func channelCredentials(ch BundleChannel, values wirejson.Object, supplied map[string]bool) StrPairs {
	out := StrPairs{}
	for _, b := range ch.Bindings {
		refs := setupRefsOf(b.Value)
		if supplied != nil {
			all := len(refs) > 0
			for _, k := range refs {
				all = all && supplied[k]
			}
			if !all {
				continue
			}
		}
		v := resolvePlaceholders(b.Value, values)
		if len(setupRefsOf(v)) == 0 {
			out = append(out, StrPair{Key: b.Key, Value: v})
		}
	}
	return out
}

func refsIn(v any, into map[string]bool) {
	switch x := v.(type) {
	case string:
		for _, k := range setupRefsOf(x) {
			into[k] = true
		}
	case wirejson.Object:
		for _, m := range x {
			refsIn(m.Value, into)
		}
	case []any:
		for _, e := range x {
			refsIn(e, into)
		}
	}
}

func secretReferenceIssue(channelKey string, keys []string) PreviewIssue {
	return blockIssue(channelKey, fmt.Sprintf("channel '%s': %s name a workspace secret, which a deploy never replaces "+
		"with a value; change that secret, or leave the setup value out", channelKey, strings.Join(keys, ", ")))
}

func linkedID(r *InstallResult, kind EntityKind, key string) *string {
	for _, e := range r.Entities {
		if e.Kind == kind && e.Key == key && linkedAction(e.Action) {
			return e.ID
		}
	}
	return nil
}

func hasID(e InstalledEntity) bool { return e.ID != nil && *e.ID != "" }

// priorInstall is what the last install of a bundle declared and left behind.
type priorInstall struct {
	bundle Bundle
	result InstallResult
}

func (p *priorInstall) owned(kind EntityKind, key string) *InstalledEntity {
	for i, e := range p.result.Entities {
		if e.Kind == kind && e.Key == key && hasID(e) && ownedAction(e.Action) {
			return &p.result.Entities[i]
		}
	}
	return nil
}

func (p *priorInstall) spec(kind EntityKind, key string) bundleSpec {
	for _, s := range bundleEntities(&p.bundle, kind) {
		if s.specKey() == key {
			return s
		}
	}
	return nil
}

func (p *priorInstall) reused(kind EntityKind, key string) *InstalledEntity {
	for i, e := range p.result.Entities {
		if e.Kind == kind && e.Key == key && hasID(e) && e.Action == ActionReused {
			return &p.result.Entities[i]
		}
	}
	return nil
}

func (p *priorInstall) recorded(kind EntityKind, key string) *string {
	for _, e := range p.result.Entities {
		if e.Kind == kind && e.Key == key && hasID(e) {
			return e.ID
		}
	}
	return nil
}

func (p *priorInstall) ownedEntities() []InstalledEntity {
	var out []InstalledEntity
	for _, e := range p.result.Entities {
		if hasID(e) && ownedAction(e.Action) {
			out = append(out, e)
		}
	}
	return out
}

// fingerprint is what was last applied to key; a record predating fingerprints derives it.
func (p *priorInstall) fingerprint(kind EntityKind, key string) (*string, error) {
	ref := p.owned(kind, key)
	if ref == nil {
		return nil, nil
	}
	if ref.Fingerprint != nil {
		return ref.Fingerprint, nil
	}
	spec := p.spec(kind, key)
	if spec == nil {
		return nil, nil
	}
	values := wirejson.Object{}
	for _, f := range p.bundle.Setup {
		if given(f.Default) {
			values.Set(f.Key, f.Default)
		}
	}
	for _, m := range p.result.SetupValues {
		values.Set(m.Key, m.Value)
	}
	fp, err := specFingerprint(&p.bundle, spec, values)
	if err != nil {
		return nil, err
	}
	return &fp, nil
}

type entityRef struct {
	kind EntityKind
	key  string
}

func sameID(a, b *string) bool {
	if a == nil || b == nil {
		return a == nil && b == nil
	}
	return *a == *b
}

func (p *priorInstall) depsChanged(deps []entityRef, current func(entityRef) *string) bool {
	for _, d := range deps {
		if !sameID(current(d), linkedID(&p.result, d.kind, d.key)) {
			return true
		}
	}
	return false
}

// catalogMCP is the catalog server a bundle MCP's catalog id names.
type catalogMCP struct {
	SpecID    string
	Transport *string
}

// bundleExistence answers which entities a deploy finds in the workspace.
type bundleExistence interface {
	refExists(ctx context.Context, kind EntityKind, id string) (bool, error)
	findTrigger(ctx context.Context, name, agentID string, recorded *string) (*string, error)
	findPolicy(ctx context.Context, p BundlePolicy, agentID *string) (*string, error)
	// channelCredentialKeys are the channel's stored credential keys, each true
	// when it names a workspace secret; nil when nothing can be read.
	channelCredentialKeys(ctx context.Context, id string) (map[string]bool, error)
}

// deployChecks are the questions only the workspace answers, asked of every write.
type deployChecks interface {
	catalogMCP(ctx context.Context, catalogID string) (*catalogMCP, error)
	agentProblem(ctx context.Context, a BundleAgent, modelID string, clientID *string) (string, error)
	automationProblem(ctx context.Context, b *Bundle, a BundleAutomation) (string, error)
	mayEdit(ctx context.Context, kind EntityKind, id string) (bool, error)
	secretProblem(ctx context.Context, name string) (string, error)
}

// bundleShapes are the owners' pure checks a plan applies.
type bundleShapes interface {
	SkillProblem(content string) string
	SkillMainFile(paths []string) (string, bool)
	CarriesSecretRef(v any) bool
	RuleProblem(r catalogapi.BundleRule) string
	ContextSecretLength() (minimum, maximum int)
}

type noExistence struct{}

func (noExistence) refExists(context.Context, EntityKind, string) (bool, error) { return false, nil }
func (noExistence) findTrigger(context.Context, string, string, *string) (*string, error) {
	return nil, nil
}
func (noExistence) findPolicy(context.Context, BundlePolicy, *string) (*string, error) {
	return nil, nil
}
func (noExistence) channelCredentialKeys(context.Context, string) (map[string]bool, error) {
	return nil, nil
}

func policyAsRule(p BundlePolicy, subjectID string) catalogapi.BundleRule {
	subject := "agent"
	if p.Subject == "workspace" {
		subject = "workspace"
	}
	return catalogapi.BundleRule{Enabled: p.Enabled, Priority: p.Priority, SubjectType: subject, SubjectID: subjectID,
		Target: p.Target, Effect: p.Effect, Params: nonNilObject(p.Params), Condition: p.Condition}
}

// plainJSON is v with every object as map[string]any.
func plainJSON(v any) any {
	switch x := v.(type) {
	case wirejson.Object:
		out := make(map[string]any, len(x))
		for _, m := range x {
			out[m.Key] = plainJSON(m.Value)
		}
		return out
	case []any:
		out := make([]any, len(x))
		for i, e := range x {
			out[i] = plainJSON(e)
		}
		return out
	}
	return v
}

func specString(spec *wirejson.Object, key string) (string, bool) {
	if spec == nil {
		return "", false
	}
	v, _ := spec.Get(key)
	s, ok := v.(string)
	return s, ok
}

// mcpUnsupported is why the MCP cannot run in the container runtime, "" when it can.
func mcpUnsupported(m BundleMCP) string {
	if m.Catalog != nil {
		return ""
	}
	if t, _ := specString(m.JSONSpec, "type"); t != "command" {
		return ""
	}
	command, _ := specString(m.JSONSpec, "command")
	command = pyStrip(command)
	runtimes := strings.Join(supportedCommands(), ", ")
	switch {
	case command == "":
		return "command MCP has no 'command'"
	case strings.Contains(command, "${CLAUDE_PLUGIN_ROOT}") || strings.Contains(command, "$CLAUDE_PLUGIN_ROOT"):
		return "command references a plugin-local binary (${CLAUDE_PLUGIN_ROOT}); not available in the container runtime"
	case strings.HasPrefix(command, "/") || strings.HasPrefix(command, "./") || strings.HasPrefix(command, "../"):
		return fmt.Sprintf("command '%s' is a local path; only published runtimes (%s) are supported", command, runtimes)
	}
	for _, c := range supportedCommands() {
		if c == command {
			return ""
		}
	}
	return fmt.Sprintf("command '%s' is not a supported runtime (%s)", command, runtimes)
}

func secretDestination(m BundleMCP) string {
	raw, ok := specString(m.JSONSpec, "endpoint_url")
	if !ok || raw == "" {
		raw, ok = specString(m.JSONSpec, "url")
	}
	if ok && raw != "" {
		if u, err := url.Parse(raw); err == nil && u.Hostname() != "" {
			return strings.ToLower(u.Hostname())
		}
	}
	if m.Catalog != nil && *m.Catalog != "" {
		return fmt.Sprintf("catalog server '%s'", *m.Catalog)
	}
	return "a local server"
}

func jsonSpecSetupRefs(spec *wirejson.Object) []string {
	if spec == nil || len(*spec) == 0 {
		return nil
	}
	var out []string
	for _, k := range []string{"endpoint_url", "url"} {
		if s, ok := specString(spec, k); ok {
			out = append(out, setupRefsOf(s)...)
		}
	}
	if args, ok := spec.Get("args"); ok {
		if l, ok := args.([]any); ok {
			for _, a := range l {
				if s, ok := a.(string); ok {
					out = append(out, setupRefsOf(s)...)
				}
			}
		}
	}
	return out
}

func truncateRunes(s string, n int) string {
	if utf8.RuneCountInString(s) <= n {
		return s
	}
	return string([]rune(s)[:n-3]) + "..."
}

func skillContentError(shapes bundleShapes, content *string) string {
	text := ""
	if content != nil {
		text = *content
	}
	problem := shapes.SkillProblem(text)
	if problem == "" {
		return ""
	}
	problem = strings.Join(strings.Fields(strings.TrimPrefix(problem, "Failed to parse skill content: ")), " ")
	return truncateRunes(problem, maxSkillErrorLength) + " (check the frontmatter between the '---' lines)"
}

func skillProblem(shapes bundleShapes, s BundleSkill) string {
	switch s.SourceType {
	case "content":
		return skillContentError(shapes, s.Content)
	case "files":
		var files StrPairs
		if s.Files != nil {
			files = *s.Files
		}
		paths := make([]string, len(files))
		for i, f := range files {
			paths[i] = f.Key
		}
		main, ok := shapes.SkillMainFile(paths)
		if !ok || strings.Contains(main, "/") {
			return "files must include a SKILL.md at the root"
		}
		content, _ := files.Get(main)
		return skillContentError(shapes, &content)
	}
	return ""
}

// requiredSetupErrors blocks required setup fields without a value; needed
// narrows them to the keys a redeploy writes.
func requiredSetupErrors(b *Bundle, values wirejson.Object, needed map[string]bool) []PreviewIssue {
	var out []PreviewIssue
	for _, f := range b.Setup {
		if !f.Required || (needed != nil && !needed[f.Key]) {
			continue
		}
		v, ok := values.Get(f.Key)
		if !ok {
			v = f.Default
		}
		if !given(v) {
			out = append(out, blockIssue(f.Key, fmt.Sprintf("required setup field '%s' is missing", f.Key)))
		}
	}
	return out
}

// contextSecretErrors blocks a context_secret value the MCP service would refuse.
func contextSecretErrors(shapes bundleShapes, b *Bundle, values wirejson.Object) []PreviewIssue {
	minimum, _ := shapes.ContextSecretLength()
	var out []PreviewIssue
	for _, m := range b.MCPs {
		for _, key := range setupRefs(m.ContextSecret) {
			v, _ := values.Get(key)
			if v == nil || pyStr(v) == "" {
				continue
			}
			if n := utf8.RuneCountInString(pyStr(v)); n < minimum || n > maxContextSecretLen {
				out = append(out, blockIssue(key, fmt.Sprintf("setup field '%s' is the context_secret of mcp '%s' and must be %d to %d characters long",
					key, m.Key, minimum, maxContextSecretLen)))
			}
		}
	}
	return out
}

// bundleAnalyzer builds the import preview of a bundle.
type bundleAnalyzer struct {
	existence bundleExistence
	prior     *priorInstall
	checks    deployChecks
	shapes    bundleShapes
	supplied  wirejson.Object

	planned    map[entityRef]EntityStatus
	ids        map[entityRef]string
	unfinished map[string]bool
	pkg        *Bundle
	values     wirejson.Object
	// neededSetup are the setup keys this deploy writes; nil on a first install.
	neededSetup map[string]bool
}

func (a *bundleAnalyzer) analyze(ctx context.Context, b *Bundle) (ImportPreview, error) {
	if a.existence == nil {
		a.existence = noExistence{}
	}
	var issues []PreviewIssue
	var entities []PreviewEntity
	a.planned, a.ids, a.unfinished = map[entityRef]EntityStatus{}, map[entityRef]string{}, map[string]bool{}
	a.pkg = b
	a.values = effectiveSetup(b, a.supplied, a.prior)

	setupKeys, mcpKeys, skillKeys, agentKeys := map[string]bool{}, map[string]bool{}, map[string]bool{}, map[string]bool{}
	for _, f := range b.Setup {
		setupKeys[f.Key] = true
	}
	for _, m := range b.MCPs {
		mcpKeys[m.Key] = true
	}
	for _, s := range b.Skills {
		skillKeys[s.Key] = true
	}
	for _, ag := range b.Agents {
		agentKeys[ag.Key] = true
	}

	a.checkDuplicateKeys(b, &issues)
	unsupported, err := a.analyzeMCPs(ctx, b, setupKeys, &entities, &issues)
	if err != nil {
		return ImportPreview{}, err
	}
	steps := []func() error{
		func() error { return a.checkContextSecrets(ctx, b, &issues) },
		func() error { return a.analyzeSkills(ctx, b, &entities, &issues) },
		func() error { a.analyzeAgents(b, mcpKeys, skillKeys, setupKeys, unsupported, &issues); return nil },
		func() error { return a.populateAgentEntities(ctx, b, &entities) },
		func() error { return a.analyzeChannels(ctx, b, agentKeys, setupKeys, &entities, &issues) },
		func() error { return a.analyzeAutomations(ctx, b, agentKeys, &entities, &issues) },
		func() error { return a.analyzePolicies(ctx, b, agentKeys, &entities, &issues) },
		func() error { a.checkTriggerNames(b, &issues); return nil },
		func() error { return a.reportOrphans(ctx, b, &entities) },
		func() error {
			if a.checks == nil {
				return nil
			}
			return a.checkWrites(ctx, b, &issues)
		},
	}
	for _, step := range steps {
		if err := step(); err != nil {
			return ImportPreview{}, err
		}
	}

	a.neededSetup = a.needed(b)
	setup := append([]SetupField{}, b.Setup...)
	if a.neededSetup != nil {
		for i, f := range setup {
			_, has := a.values.Get(f.Key)
			setup[i].Required = f.Required && a.neededSetup[f.Key] && !has
		}
	}
	digest, err := a.digest(b, entities)
	if err != nil {
		return ImportPreview{}, err
	}
	return ImportPreview{Bundle: *b, Setup: setup, Entities: entities, Issues: issues,
		Installable: len(blocks(issues)) == 0, PlanDigest: &digest}, nil
}

// digest names the plan: the bundle and what it does with each entity, to
// which id, with which resolved spec.
func (a *bundleAnalyzer) digest(b *Bundle, entities []PreviewEntity) (string, error) {
	specs := map[entityRef]bundleSpec{}
	for _, kind := range entityKinds() {
		for _, s := range bundleEntities(b, kind) {
			specs[entityRef{kind, s.specKey()}] = s
		}
	}
	type row struct {
		values []any
		repr   string
	}
	rows := make([]row, 0, len(entities))
	for _, e := range entities {
		ref := entityRef{e.Kind, e.Key}
		var id, fp any
		if v, ok := a.ids[ref]; ok {
			id = v
		}
		if spec, ok := specs[ref]; ok {
			f, err := specFingerprint(b, spec, a.values)
			if err != nil {
				return "", err
			}
			fp = f
		}
		values := []any{string(e.Kind), e.Key, string(e.Status), id, fp}
		rows = append(rows, row{values, pyRepr(values)})
	}
	sort.SliceStable(rows, func(i, j int) bool { return rows[i].repr < rows[j].repr })
	plan := make([]any, len(rows))
	for i, r := range rows {
		plan[i] = r.values
	}
	return sha256Dumps(wirejson.Object{{Key: "bundle", Value: b.Dump()}, {Key: "plan", Value: plan}})
}

func (a *bundleAnalyzer) priorSpec(kind EntityKind, key string) bundleSpec {
	if a.prior == nil || a.prior.owned(kind, key) == nil {
		return nil
	}
	return a.prior.spec(kind, key)
}

func (a *bundleAnalyzer) needed(b *Bundle) map[string]bool {
	if a.prior == nil {
		return nil
	}
	out := map[string]bool{}
	for _, kind := range entityKinds() {
		for _, item := range bundleEntities(b, kind) {
			status := a.planned[entityRef{kind, item.specKey()}]
			switch {
			case status == StatusWillCreate:
				refsIn(item.dump(), out)
			case status == StatusWillUpdate && kind == KindAgent:
				ag := item.(BundleAgent)
				for _, k := range append(setupRefs(ag.Model), setupRefs(ag.Client)...) {
					out[k] = true
				}
			case kind == KindChannel && a.unfinished[item.specKey()]:
				refsIn(item.(BundleChannel).Bindings.object(), out)
			}
		}
	}
	return out
}

func (a *bundleAnalyzer) current(ref entityRef) *string {
	if v, ok := a.ids[ref]; ok {
		return &v
	}
	return nil
}

// plan is one entity's status against the previous install of the bundle.
func (a *bundleAnalyzer) plan(ctx context.Context, kind EntityKind, spec bundleSpec, deps []entityRef,
	findExisting func() (*string, error)) (EntityStatus, error) {
	ref := entityRef{kind, spec.specKey()}
	var owned *InstalledEntity
	if a.prior != nil {
		owned = a.prior.owned(kind, ref.key)
	}
	exists := false
	if owned != nil {
		var err error
		if exists, err = a.existence.refExists(ctx, kind, *owned.ID); err != nil {
			return "", err
		}
	}
	var status EntityStatus
	if exists {
		a.ids[ref] = *owned.ID
		fp, err := specFingerprint(a.pkg, spec, a.values)
		if err != nil {
			return "", err
		}
		last, err := a.prior.fingerprint(kind, ref.key)
		if err != nil {
			return "", err
		}
		if last == nil || *last != fp || a.prior.depsChanged(deps, a.current) {
			status = StatusWillUpdate
		} else {
			status = StatusUnchanged
		}
	} else {
		if findExisting == nil {
			findExisting = func() (*string, error) { return a.reusedID(ctx, kind, ref.key) }
		}
		found, err := findExisting()
		if err != nil {
			return "", err
		}
		if found != nil {
			status = StatusAlreadyExists
			a.ids[ref] = *found
		} else {
			status = StatusWillCreate
			a.ids[ref] = notYetCreated
		}
	}
	a.planned[ref] = status
	return status, nil
}

func (a *bundleAnalyzer) reusedID(ctx context.Context, kind EntityKind, key string) (*string, error) {
	if a.prior == nil {
		return nil, nil
	}
	ref := a.prior.reused(kind, key)
	if ref == nil {
		return nil, nil
	}
	ok, err := a.existence.refExists(ctx, kind, *ref.ID)
	if err != nil || !ok {
		return nil, err
	}
	return ref.ID, nil
}

// plannedID is the id key resolves to, nil when this deploy creates it.
func (a *bundleAnalyzer) plannedID(kind EntityKind, key string) *string {
	id, ok := a.ids[entityRef{kind, key}]
	if !ok || id == notYetCreated {
		return nil
	}
	return &id
}

func (a *bundleAnalyzer) findTrigger(ctx context.Context, kind EntityKind, key, agentKey string) (*string, error) {
	agentID := a.plannedID(KindAgent, agentKey)
	if agentID == nil {
		return nil, nil
	}
	var recorded *string
	if a.prior != nil {
		recorded = a.prior.recorded(kind, key)
	}
	return a.existence.findTrigger(ctx, triggerName(a.pkg, key), *agentID, recorded)
}

func (a *bundleAnalyzer) checkWrites(ctx context.Context, b *Bundle, issues *[]PreviewIssue) error {
	for _, ag := range b.Agents {
		if !writes(a.planned[entityRef{KindAgent, ag.Key}]) {
			continue
		}
		model := ""
		if ag.Model != nil {
			model = *ag.Model
		}
		modelID := resolvePlaceholders(model, a.values)
		var client *string
		if ag.Client != nil && *ag.Client != "" {
			client = strp(resolvePlaceholders(*ag.Client, a.values))
		}
		clientText := ""
		if client != nil {
			clientText = *client
		}
		unresolved := false
		for _, s := range []struct{ setting, value string }{{"model", modelID}, {"client", clientText}} {
			var optional []string
			for _, key := range setupRefsOf(s.value) {
				if f, ok := b.SetupField(key); ok && !f.Required {
					optional = append(optional, key)
				}
			}
			if len(optional) > 0 {
				*issues = append(*issues, blockIssue(ag.Key, fmt.Sprintf("agent '%s': %s needs setup field(s) %s, which have no value",
					ag.Key, s.setting, strings.Join(optional, ", "))))
			}
			unresolved = unresolved || len(setupRefsOf(s.value)) > 0
		}
		if modelID == "" || unresolved {
			continue
		}
		problem, err := a.checks.agentProblem(ctx, ag, modelID, client)
		if err != nil {
			return err
		}
		if problem != "" {
			*issues = append(*issues, blockIssue(ag.Key, fmt.Sprintf("agent '%s': %s", ag.Key, problem)))
		}
	}
	for _, auto := range b.Automations {
		if !writes(a.planned[entityRef{KindAutomation, auto.Key}]) {
			continue
		}
		problem, err := a.checks.automationProblem(ctx, b, auto)
		if err != nil {
			return err
		}
		if problem != "" {
			*issues = append(*issues, blockIssue(auto.Key, fmt.Sprintf("automation '%s': %s", auto.Key, problem)))
		}
	}
	for _, kind := range editGuarded() {
		for _, item := range bundleEntities(b, kind) {
			ref := entityRef{kind, item.specKey()}
			if a.planned[ref] != StatusWillUpdate {
				continue
			}
			id, ok := a.ids[ref]
			allowed := false
			if ok {
				var err error
				if allowed, err = a.checks.mayEdit(ctx, kind, id); err != nil {
					return err
				}
			} else {
				id = "None"
			}
			if !allowed {
				*issues = append(*issues, blockIssue(ref.key, fmt.Sprintf("%s '%s' would be updated, but you may not edit %s %s",
					kind, ref.key, kind, id)))
			}
		}
	}
	return nil
}

func (a *bundleAnalyzer) reportOrphans(ctx context.Context, b *Bundle, entities *[]PreviewEntity) error {
	if a.prior == nil {
		return nil
	}
	for _, ref := range a.prior.ownedEntities() {
		present := false
		for _, s := range bundleEntities(b, ref.Kind) {
			present = present || s.specKey() == ref.Key
		}
		if present {
			continue
		}
		ok, err := a.existence.refExists(ctx, ref.Kind, *ref.ID)
		if err != nil {
			return err
		}
		if !ok {
			continue
		}
		a.ids[entityRef{ref.Kind, ref.Key}] = *ref.ID
		*entities = append(*entities, PreviewEntity{Kind: ref.Kind, Key: ref.Key, Name: ref.Name, Status: StatusOrphaned,
			Detail: strp(orphanedDetail)})
	}
	return nil
}

func (a *bundleAnalyzer) checkDuplicateKeys(b *Bundle, issues *[]PreviewIssue) {
	setupKeys := make([]string, len(b.Setup))
	for i, f := range b.Setup {
		setupKeys[i] = f.Key
	}
	keysOf := func(kind EntityKind) []string {
		var out []string
		for _, s := range bundleEntities(b, kind) {
			out = append(out, s.specKey())
		}
		return out
	}
	for _, group := range []struct {
		label string
		keys  []string
	}{{"setup", setupKeys}, {"mcp", keysOf(KindMCP)}, {"skill", keysOf(KindSkill)}, {"agent", keysOf(KindAgent)},
		{"channel", keysOf(KindChannel)}, {"automation", keysOf(KindAutomation)}, {"policy", keysOf(KindPolicy)}} {
		seen := map[string]bool{}
		for _, k := range group.keys {
			if seen[k] {
				*issues = append(*issues, blockIssue(k, fmt.Sprintf("duplicate %s key '%s'", group.label, k)))
			}
			seen[k] = true
		}
	}
}

func (a *bundleAnalyzer) checkTriggerNames(b *Bundle, issues *[]PreviewIssue) {
	for _, group := range []struct {
		label string
		kind  EntityKind
	}{{"channel", KindChannel}, {"automation", KindAutomation}} {
		for _, item := range bundleEntities(b, group.kind) {
			name := triggerName(b, item.specKey())
			if utf8.RuneCountInString(name) > BundleMaxNameLength {
				*issues = append(*issues, blockIssue(item.specKey(), fmt.Sprintf("%s '%s' would create trigger '%s...' whose name is longer than %d characters",
					group.label, item.specKey(), string([]rune(name)[:40]), BundleMaxNameLength)))
			}
		}
	}
}

// mcpTransport is the MCP's transport type: its json_spec's, else the catalog's.
func (a *bundleAnalyzer) mcpTransport(ctx context.Context, m BundleMCP) (any, error) {
	if m.JSONSpec != nil {
		v, _ := m.JSONSpec.Get("type")
		return v, nil
	}
	if a.checks == nil || m.Catalog == nil {
		return nil, nil
	}
	found, err := a.checks.catalogMCP(ctx, *m.Catalog)
	if err != nil || found == nil || found.Transport == nil {
		return nil, err
	}
	return *found.Transport, nil
}

func (a *bundleAnalyzer) checkContextSecrets(ctx context.Context, b *Bundle, issues *[]PreviewIssue) error {
	for _, m := range b.MCPs {
		if m.ContextSecret == nil {
			continue
		}
		transport, err := a.mcpTransport(ctx, m)
		if err != nil {
			return err
		}
		if transport != nil && transport != "url" {
			*issues = append(*issues, blockIssue(m.Key, fmt.Sprintf("mcp '%s' context_secret applies to url MCPs only", m.Key)))
		}
		for _, key := range setupRefs(m.ContextSecret) {
			f, ok := b.SetupField(key)
			switch {
			case !ok:
				*issues = append(*issues, blockIssue(m.Key, fmt.Sprintf("mcp '%s' context_secret references unknown setup field '%s'", m.Key, key)))
			case f.Type != SetupSecret:
				*issues = append(*issues, blockIssue(m.Key, fmt.Sprintf("mcp '%s' context_secret must come from a setup field of type 'secret'; '%s' is '%s'",
					m.Key, key, f.Type)))
			}
		}
	}
	return nil
}

func (a *bundleAnalyzer) analyzeMCPs(ctx context.Context, b *Bundle, setupKeys map[string]bool, entities *[]PreviewEntity,
	issues *[]PreviewIssue) (map[string]bool, error) {
	unsupported := map[string]bool{}
	for _, m := range b.MCPs {
		reason := mcpUnsupported(m)
		var secretRefs []string
		for _, bind := range m.Bindings {
			if name, ok := secretBinding(bind.Value); ok {
				secretRefs = append(secretRefs, fmt.Sprintf("%s from secret '%s' to %s", bind.Key, name, secretDestination(m)))
				if a.checks != nil {
					problem, err := a.checks.secretProblem(ctx, name)
					if err != nil {
						return nil, err
					}
					if problem != "" {
						*issues = append(*issues, blockIssue(m.Key, fmt.Sprintf("mcp '%s' binding '%s' %s", m.Key, bind.Key, problem)))
					}
				}
				continue
			}
			if mentionsSecret(bind.Value) {
				*issues = append(*issues, blockIssue(m.Key, fmt.Sprintf("mcp '%s' binding '%s' must be ${secret.<name>} alone; "+
					"put any prefix such as 'Bearer ' into the secret's value", m.Key, bind.Key)))
				continue
			}
			refs := setupRefsOf(bind.Value)
			if len(refs) == 0 {
				*issues = append(*issues, blockIssue(m.Key, fmt.Sprintf("mcp '%s' binding '%s' must reference ${setup.<key>} or ${secret.<name>}",
					m.Key, bind.Key)))
			}
			for _, key := range refs {
				if !setupKeys[key] {
					*issues = append(*issues, blockIssue(m.Key, fmt.Sprintf("mcp '%s' binding references unknown setup field '%s'", m.Key, key)))
				}
			}
		}
		if m.JSONSpec != nil && a.shapes.CarriesSecretRef(plainJSON(*m.JSONSpec)) {
			*issues = append(*issues, blockIssue(m.Key, fmt.Sprintf("mcp '%s' json_spec may not hold a secret reference; bind it: ${secret.<name>}", m.Key)))
		}
		for _, key := range jsonSpecSetupRefs(m.JSONSpec) {
			if !setupKeys[key] {
				*issues = append(*issues, blockIssue(m.Key, fmt.Sprintf("mcp '%s' json_spec references unknown setup field '%s'", m.Key, key)))
			}
		}
		if m.Catalog != nil && a.checks != nil {
			found, err := a.checks.catalogMCP(ctx, *m.Catalog)
			if err != nil {
				return nil, err
			}
			switch {
			case found == nil:
				*issues = append(*issues, blockIssue(m.Key, fmt.Sprintf("mcp '%s' names catalog server '%s', which the catalog does not have", m.Key, *m.Catalog)))
			case found.Transport == nil:
				*issues = append(*issues, blockIssue(m.Key, fmt.Sprintf("mcp '%s' names catalog server '%s', which declares no transport", m.Key, *m.Catalog)))
			}
		}
		if reason != "" {
			unsupported[m.Key] = true
			*entities = append(*entities, PreviewEntity{Kind: KindMCP, Key: m.Key, Name: m.Name, Status: StatusUnsupported, Detail: strp(reason)})
			*issues = append(*issues, warnIssue(m.Key, fmt.Sprintf("mcp '%s' will be skipped: %s", m.Key, reason)))
			continue
		}
		status, err := a.plan(ctx, KindMCP, m, nil, nil)
		if err != nil {
			return nil, err
		}
		var detail *string
		if len(secretRefs) > 0 {
			detail = strp(strings.Join(secretRefs, "; "))
		}
		if status == StatusWillUpdate {
			status, detail = StatusChangesNotApplied, strp(mcpNotApplied)
			*issues = append(*issues, warnIssue(m.Key, fmt.Sprintf("mcp '%s' changed: %s", m.Key, mcpNotApplied)))
		}
		*entities = append(*entities, PreviewEntity{Kind: KindMCP, Key: m.Key, Name: m.Name, Status: status, Detail: detail})
	}
	return unsupported, nil
}

func (a *bundleAnalyzer) analyzeSkills(ctx context.Context, b *Bundle, entities *[]PreviewEntity, issues *[]PreviewIssue) error {
	for _, s := range b.Skills {
		if problem := skillProblem(a.shapes, s); problem != "" {
			*issues = append(*issues, blockIssue(s.Key, fmt.Sprintf("skill '%s' is not a valid SKILL.md: %s", s.Key, problem)))
		}
		status, err := a.plan(ctx, KindSkill, s, nil, nil)
		if err != nil {
			return err
		}
		var detail *string
		if status == StatusWillUpdate && s.SourceType == "github" {
			status, detail = StatusChangesNotApplied, strp(githubSkillNotApplied)
			a.planned[entityRef{KindSkill, s.Key}] = status
			*issues = append(*issues, warnIssue(s.Key, fmt.Sprintf("skill '%s' changed: %s", s.Key, githubSkillNotApplied)))
		}
		*entities = append(*entities, PreviewEntity{Kind: KindSkill, Key: s.Key, Name: s.Name, Status: status, Detail: detail})
	}
	return nil
}

func (a *bundleAnalyzer) analyzeAgents(b *Bundle, mcpKeys, skillKeys, setupKeys, unsupported map[string]bool, issues *[]PreviewIssue) {
	for _, ag := range b.Agents {
		for _, ref := range ag.MCPs {
			switch {
			case !mcpKeys[ref]:
				*issues = append(*issues, blockIssue(ag.Key, fmt.Sprintf("agent '%s' references unknown mcp '%s'", ag.Key, ref)))
			case unsupported[ref]:
				*issues = append(*issues, warnIssue(ag.Key, fmt.Sprintf("agent '%s' depends on unsupported mcp '%s'; it will be created without that tool", ag.Key, ref)))
			}
		}
		for _, ref := range ag.Skills {
			if !skillKeys[ref] {
				*issues = append(*issues, blockIssue(ag.Key, fmt.Sprintf("agent '%s' references unknown skill '%s'", ag.Key, ref)))
			}
		}
		if ag.Model == nil || *ag.Model == "" {
			*issues = append(*issues, blockIssue(ag.Key, fmt.Sprintf("agent '%s' has no model", ag.Key)))
		}
		for _, s := range []struct {
			setting string
			value   *string
		}{{"model", ag.Model}, {"client", ag.Client}} {
			for _, key := range setupRefs(s.value) {
				if !setupKeys[key] {
					*issues = append(*issues, blockIssue(ag.Key, fmt.Sprintf("agent '%s' %s references unknown setup field '%s'", ag.Key, s.setting, key)))
				}
			}
		}
	}
}

func (a *bundleAnalyzer) populateAgentEntities(ctx context.Context, b *Bundle, entities *[]PreviewEntity) error {
	for _, ag := range b.Agents {
		var deps []entityRef
		for _, ref := range ag.MCPs {
			deps = append(deps, entityRef{KindMCP, ref})
		}
		for _, ref := range ag.Skills {
			deps = append(deps, entityRef{KindSkill, ref})
		}
		status, err := a.plan(ctx, KindAgent, ag, deps, nil)
		if err != nil {
			return err
		}
		*entities = append(*entities, PreviewEntity{Kind: KindAgent, Key: ag.Key, Name: ag.Name, Status: status})
	}
	return nil
}

func pyBool(b bool) string {
	if b {
		return "True"
	}
	return "False"
}

func (a *bundleAnalyzer) analyzeAutomations(ctx context.Context, b *Bundle, agentKeys map[string]bool, entities *[]PreviewEntity,
	issues *[]PreviewIssue) error {
	for _, auto := range b.Automations {
		if !agentKeys[auto.Agent] {
			*issues = append(*issues, blockIssue(auto.Key, fmt.Sprintf("automation '%s' references unknown agent '%s'", auto.Key, auto.Agent)))
		}
		status, err := a.plan(ctx, KindAutomation, auto, []entityRef{{KindAgent, auto.Agent}}, func() (*string, error) {
			return a.findTrigger(ctx, KindAutomation, auto.Key, auto.Agent)
		})
		if err != nil {
			return err
		}
		*entities = append(*entities, PreviewEntity{Kind: KindAutomation, Key: auto.Key, Name: auto.Key, Status: status,
			Detail: strp(fmt.Sprintf("cron '%s' (%s), enabled=%s", auto.Cron, auto.Timezone, pyBool(auto.Enabled)))})
	}
	return nil
}

func (a *bundleAnalyzer) analyzeChannels(ctx context.Context, b *Bundle, agentKeys, setupKeys map[string]bool, entities *[]PreviewEntity,
	issues *[]PreviewIssue) error {
	for _, ch := range b.Channels {
		if !agentKeys[ch.Agent] {
			*issues = append(*issues, blockIssue(ch.Key, fmt.Sprintf("channel '%s' references unknown agent '%s'", ch.Key, ch.Agent)))
		}
		for _, bind := range ch.Bindings {
			for _, key := range setupRefsOf(bind.Value) {
				if !setupKeys[key] {
					*issues = append(*issues, blockIssue(ch.Key, fmt.Sprintf("channel '%s' binding references unknown setup field '%s'", ch.Key, key)))
				}
			}
		}
		if before, ok := a.priorSpec(KindChannel, ch.Key).(BundleChannel); ok && before.Type != ch.Type {
			*issues = append(*issues, blockIssue(ch.Key, fmt.Sprintf("channel '%s' changes type from %s to %s, which a redeploy cannot apply; give it a new key",
				ch.Key, before.Type, ch.Type)))
		}
		status, err := a.plan(ctx, KindChannel, ch, []entityRef{{KindAgent, ch.Agent}}, func() (*string, error) {
			return a.findTrigger(ctx, KindChannel, ch.Key, ch.Agent)
		})
		if err != nil {
			return err
		}
		if (status == StatusUnchanged || status == StatusWillUpdate) && len(ch.Bindings) > 0 {
			var stored map[string]bool
			if id, ok := a.ids[entityRef{KindChannel, ch.Key}]; ok && id != "" {
				if stored, err = a.existence.channelCredentialKeys(ctx, id); err != nil {
					return err
				}
			}
			overlap := false
			for _, bind := range ch.Bindings {
				if _, ok := stored[bind.Key]; ok {
					overlap = true
				}
			}
			if stored != nil && !overlap {
				a.unfinished[ch.Key] = true
				status = StatusWillUpdate
			} else if rewrite := channelCredentials(ch, a.values, suppliedKeys(a.supplied)); len(rewrite) > 0 {
				status = StatusWillUpdate
				var referenced []string
				for _, r := range rewrite {
					if stored[r.Key] {
						referenced = append(referenced, r.Key)
					}
				}
				sort.Strings(referenced)
				if len(referenced) > 0 {
					*issues = append(*issues, secretReferenceIssue(ch.Key, referenced))
				}
			}
			a.planned[entityRef{KindChannel, ch.Key}] = status
		}
		*entities = append(*entities, PreviewEntity{Kind: KindChannel, Key: ch.Key, Name: ch.Name, Status: status,
			Detail: strp(fmt.Sprintf("%s, enabled=%s", ch.Type, pyBool(ch.Enabled)))})
	}
	return nil
}

func (a *bundleAnalyzer) analyzePolicies(ctx context.Context, b *Bundle, agentKeys map[string]bool, entities *[]PreviewEntity,
	issues *[]PreviewIssue) error {
	for _, p := range b.Policies {
		if p.Subject != "workspace" && !agentKeys[p.Subject] {
			*issues = append(*issues, blockIssue(p.Key, fmt.Sprintf("policy '%s' subject '%s' is neither 'workspace' nor a known agent key", p.Key, p.Subject)))
		}
		if problem := a.shapes.RuleProblem(policyAsRule(p, placeholderSubjectID)); problem != "" {
			*issues = append(*issues, blockIssue(p.Key, fmt.Sprintf("policy '%s' target '%s' is invalid (%s); it would install but never enforce",
				p.Key, p.Target, problem)))
		}
		status, err := a.plan(ctx, KindPolicy, p, []entityRef{{KindAgent, p.Subject}}, func() (*string, error) {
			if p.Subject == "workspace" {
				return a.existence.findPolicy(ctx, p, nil)
			}
			agentID := a.plannedID(KindAgent, p.Subject)
			if agentID == nil {
				return nil, nil
			}
			return a.existence.findPolicy(ctx, p, agentID)
		})
		if err != nil {
			return err
		}
		*entities = append(*entities, PreviewEntity{Kind: KindPolicy, Key: p.Key, Name: p.Key, Status: status,
			Detail: strp(fmt.Sprintf("%s %s on %s", p.Effect, p.Target, p.Subject))})
	}
	return nil
}
