package service

import (
	"context"
	"fmt"
	"strings"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx/wirejson"
	catalogapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/catalog/api"
)

func (s BundleStream) specKey() string      { return s.Key }
func (s BundleStream) renamedFrom() *string { return s.RenamedFrom }

func (s BundleStream) writers() []BundleStreamWriter {
	return append(append([]BundleStreamWriter{}, s.Processors...), s.Forwards...)
}

// outputs are the streams s writes into, each once, in order.
func (s BundleStream) outputs() []string {
	var out []string
	for _, w := range s.writers() {
		for _, o := range w.Outputs {
			if !containsString(out, o) {
				out = append(out, o)
			}
		}
	}
	return out
}

// streamOrder is the streams with each one after the streams it writes into.
func streamOrder(streams []BundleStream) ([]BundleStream, []string) {
	return dependencyOrder(streams, func(s BundleStream) string { return s.Key }, BundleStream.outputs)
}

func streamKeys(b *Bundle) map[string]bool {
	out := map[string]bool{}
	for _, s := range b.Streams {
		out[s.Key] = true
	}
	return out
}

func streamDeps(s BundleStream, keys map[string]bool) []entityRef {
	var out []entityRef
	for _, o := range s.outputs() {
		if keys[o] {
			out = append(out, entityRef{KindStream, o})
		}
	}
	return out
}

func counted(n int, noun string) string {
	if n == 1 {
		return "1 " + noun
	}
	return fmt.Sprintf("%d %ss", n, noun)
}

func streamDetail(s BundleStream) string {
	sources := "no sources"
	if len(s.Sources) > 0 {
		sources = counted(len(s.Sources), "source")
	}
	var writers []string
	if len(s.Processors) > 0 {
		writers = append(writers, counted(len(s.Processors), "processor"))
	}
	if len(s.Forwards) > 0 {
		writers = append(writers, counted(len(s.Forwards), "forward"))
	}
	if len(writers) == 0 {
		writers = []string{"no writers"}
	}
	return sources + ", " + strings.Join(writers, ", ")
}

// suppliesSecret reports a secret setup value given to this deploy that a
// credential of s reads: the fingerprint never sees it, so the stream is written.
func suppliesSecret(b *Bundle, s BundleStream, supplied map[string]bool) bool {
	for _, src := range s.Sources {
		for _, cred := range src.Credentials {
			for _, k := range setupRefsOf(cred.Value) {
				if f, ok := b.SetupField(k); ok && f.Type == SetupSecret && supplied[k] {
					return true
				}
			}
		}
	}
	return false
}

func plainObject(o wirejson.Object) map[string]any {
	m, _ := plainJSON(nonNilObject(o)).(map[string]any)
	return m
}

// streamSpecOf is s as the streams module takes it: credentials resolved
// from values, those still unresolved left out, and outputs as stream ids.
func streamSpecOf(s BundleStream, values wirejson.Object, output func(string) string) catalogapi.BundleStreamSpec {
	spec := catalogapi.BundleStreamSpec{Name: s.Name, Description: s.Description}
	for _, src := range s.Sources {
		out := catalogapi.BundleStreamSource{Type: src.Type, Kind: src.Kind, Config: map[string]string{}, Values: map[string]string{},
			Secrets: map[string]string{}}
		for _, c := range src.Config {
			if v := resolvePlaceholders(c.Value, values); len(setupRefsOf(v)) == 0 {
				out.Config[c.Key] = v
			}
		}
		for _, c := range src.Credentials {
			if name, ok := secretBinding(c.Value); ok {
				out.Secrets[c.Key] = name
			} else if v := resolvePlaceholders(c.Value, values); len(setupRefsOf(v)) == 0 {
				out.Values[c.Key] = v
			}
		}
		spec.Sources = append(spec.Sources, out)
	}
	for _, w := range s.writers() {
		outputs := make([]string, len(w.Outputs))
		for i, o := range w.Outputs {
			outputs[i] = output(o)
		}
		spec.Writers = append(spec.Writers, catalogapi.BundleStreamWriter{Code: w.Code, Outputs: outputs, Filter: plainObject(w.Filter)})
	}
	return spec
}

func strangerStream(what, ref string) string {
	return fmt.Sprintf("%s '%s', which is neither a stream of this bundle nor a stream of the workspace", what, ref)
}

// knownStream reports ref naming a stream of the bundle or, when the plan
// reads the workspace, one of the workspace.
func (a *bundleAnalyzer) knownStream(ctx context.Context, keys map[string]bool, ref string) (bool, error) {
	if keys[ref] || a.checks == nil {
		return true, nil
	}
	id, err := a.existence.streamNamed(ctx, ref)
	return id != nil, err
}

func (a *bundleAnalyzer) streamCredentialIssues(ctx context.Context, s BundleStream, setupKeys map[string]bool, issues *[]PreviewIssue) ([]string, error) {
	var secrets []string
	for _, src := range s.Sources {
		for _, cred := range src.Credentials {
			if name, ok := secretBinding(cred.Value); ok {
				secrets = append(secrets, fmt.Sprintf("%s from secret '%s'", cred.Key, name))
				if a.checks == nil {
					continue
				}
				problem, err := a.checks.secretProblem(ctx, name)
				if err != nil {
					return nil, err
				}
				if problem != "" {
					*issues = append(*issues, blockIssue(s.Key, fmt.Sprintf("stream '%s' credential '%s' %s", s.Key, cred.Key, problem)))
				}
				continue
			}
			refs := setupRefsOf(cred.Value)
			if mentionsSecret(cred.Value) || len(refs) == 0 {
				*issues = append(*issues, blockIssue(s.Key, fmt.Sprintf("stream '%s' source %s credential '%s' must be ${secret.<name>} or reference ${setup.<key>}",
					s.Key, src.Type, cred.Key)))
				continue
			}
			for _, k := range refs {
				if !setupKeys[k] {
					*issues = append(*issues, blockIssue(s.Key, fmt.Sprintf("stream '%s' source %s credential '%s' references unknown setup field '%s'",
						s.Key, src.Type, cred.Key, k)))
				}
			}
		}
		for _, c := range src.Config {
			for _, k := range setupRefsOf(c.Value) {
				if !setupKeys[k] {
					*issues = append(*issues, blockIssue(s.Key, fmt.Sprintf("stream '%s' source %s setting '%s' references unknown setup field '%s'",
						s.Key, src.Type, c.Key, k)))
				}
			}
		}
	}
	return secrets, nil
}

func (a *bundleAnalyzer) analyzeStreams(ctx context.Context, b *Bundle, setupKeys map[string]bool, entities *[]PreviewEntity, issues *[]PreviewIssue) error {
	keys := streamKeys(b)
	order, cycle := streamOrder(b.Streams)
	if cycle != nil {
		*issues = append(*issues, blockIssue(cycle[0], "streams write into each other in a cycle: "+strings.Join(cycle, " -> ")))
	}
	for _, s := range order {
		secrets, err := a.streamCredentialIssues(ctx, s, setupKeys, issues)
		if err != nil {
			return err
		}
		for _, o := range s.outputs() {
			known, err := a.knownStream(ctx, keys, o)
			if err != nil {
				return err
			}
			if !known {
				*issues = append(*issues, blockIssue(s.Key, strangerStream(fmt.Sprintf("stream '%s' writes into", s.Key), o)))
			}
		}
		if before, ok := a.priorSpec(KindStream, s.Key).(BundleStream); ok && before.Name != s.Name {
			*issues = append(*issues, blockIssue(s.Key, fmt.Sprintf("stream '%s' changes name from %s to %s, which a redeploy cannot apply; give it a new key",
				s.Key, before.Name, s.Name)))
		}
		status, err := a.plan(ctx, KindStream, s, streamDeps(s, keys), func() (*string, error) { return a.existence.streamNamed(ctx, s.Name) })
		if err != nil {
			return err
		}
		if status == StatusUnchanged && suppliesSecret(b, s, suppliedKeys(a.supplied)) {
			status = StatusWillUpdate
			a.planned[entityRef{KindStream, s.Key}] = status
		}
		detail := streamDetail(s)
		if len(secrets) > 0 {
			detail += "; " + strings.Join(secrets, "; ")
		}
		*entities = append(*entities, PreviewEntity{Kind: KindStream, Key: s.Key, Name: s.Name, Status: status, Detail: &detail})
	}
	return nil
}

// automationStreamIssues blocks a stream automation on a stream nobody has,
// and an automation whose trigger a redeploy would have to replace.
func (a *bundleAnalyzer) automationStreamIssues(ctx context.Context, b *Bundle, auto BundleAutomation, issues *[]PreviewIssue) error {
	if auto.On != nil {
		known, err := a.knownStream(ctx, streamKeys(b), auto.On.Stream)
		if err != nil {
			return err
		}
		if !known {
			*issues = append(*issues, blockIssue(auto.Key, strangerStream(fmt.Sprintf("automation '%s' runs on stream", auto.Key), auto.On.Stream)))
		}
	}
	before, ok := a.priorSpec(KindAutomation, auto.Key).(BundleAutomation)
	if !ok {
		return nil
	}
	change := ""
	switch {
	case before.On == nil && auto.On != nil:
		change = "changes from a cron schedule to a stream trigger"
	case before.On != nil && auto.On == nil:
		change = "changes from a stream trigger to a cron schedule"
	case before.On != nil && before.On.Stream != auto.On.Stream:
		change = fmt.Sprintf("changes its stream from %s to %s", before.On.Stream, auto.On.Stream)
	}
	if change != "" {
		*issues = append(*issues, blockIssue(auto.Key, fmt.Sprintf("automation '%s' %s, which a redeploy cannot apply; give it a new key", auto.Key, change)))
	}
	return nil
}

func automationDeps(b *Bundle, auto BundleAutomation) []entityRef {
	var deps []entityRef
	if t, ok := bundleTask(b, auto); ok {
		deps = append(deps, entityRef{KindTask, t.Key})
	}
	if agent := automationAgent(b, auto); agent != "" {
		deps = append(deps, entityRef{KindAgent, agent})
	}
	if auto.On != nil && streamKeys(b)[auto.On.Stream] {
		deps = append(deps, entityRef{KindStream, auto.On.Stream})
	}
	return deps
}

func automationDetail(auto BundleAutomation) string {
	runs := ""
	if auto.Task != nil {
		runs = "; runs task " + *auto.Task
	}
	if auto.On != nil {
		return fmt.Sprintf("on stream '%s', enabled=%s%s", auto.On.Stream, pyBool(auto.Enabled), runs)
	}
	return fmt.Sprintf("cron '%s' (%s), enabled=%s%s", auto.Cron, auto.Timezone, pyBool(auto.Enabled), runs)
}

// -- install

// streamID is the stream ref names: one this deploy wrote, else the workspace's stream of that name.
func (in *bundleInstaller) streamID(ctx context.Context, ref string) (string, error) {
	if id, ok := in.streamIDs[ref]; ok {
		return id, nil
	}
	if !streamKeys(in.pkg)[ref] {
		id, ok, err := in.w.b.d.Streams.StreamNamed(ctx, ref)
		if err != nil || ok {
			return id, err
		}
	}
	return "", installError(strangerStream("the bundle refers to stream", ref))
}

func (in *bundleInstaller) streamSpec(ctx context.Context, s BundleStream) (catalogapi.BundleStreamSpec, error) {
	ids := map[string]string{}
	for _, o := range s.outputs() {
		id, err := in.streamID(ctx, o)
		if err != nil {
			return catalogapi.BundleStreamSpec{}, err
		}
		ids[o] = id
	}
	return streamSpecOf(s, in.values, func(o string) string { return ids[o] }), nil
}

func (in *bundleInstaller) installStreams(ctx context.Context) error {
	st := in.w.b.d.Streams
	in.streamIDs = map[string]string{}
	keys := streamKeys(in.pkg)
	order, _ := streamOrder(in.pkg.Streams)
	for _, s := range order {
		detail := streamDetail(s)
		fp, err := in.fingerprint(s)
		if err != nil {
			return err
		}
		id, _, err := in.owned(ctx, KindStream, s.Key)
		if err != nil {
			return err
		}
		if id != nil {
			in.streamIDs[s.Key] = *id
			update, err := in.needsUpdate(KindStream, s, streamDeps(s, keys))
			if err != nil {
				return err
			}
			action := ActionUnchanged
			if update || suppliesSecret(in.pkg, s, in.supplied) {
				if err := in.authorizeUpdate(ctx, KindStream, s.Key, *id); err != nil {
					return err
				}
				spec, err := in.streamSpec(ctx, s)
				if err != nil {
					return err
				}
				if err := refusedInstall(st.UpdateStream(ctx, *id, spec)); err != nil {
					return err
				}
				in.updatedInPlace = true
				action = ActionUpdated
			}
			in.add(InstalledEntity{Kind: KindStream, Key: s.Key, Name: s.Name, Action: action, ID: id, Detail: &detail, Fingerprint: fp})
			continue
		}
		existing, ok, err := st.StreamNamed(ctx, s.Name)
		if err != nil {
			return err
		}
		if ok {
			in.streamIDs[s.Key] = existing
			in.add(reusedEntity(KindStream, s.Key, s.Name, existing))
			continue
		}
		spec, err := in.streamSpec(ctx, s)
		if err != nil {
			return err
		}
		made, err := st.CreateStream(ctx, spec)
		if err != nil {
			return refusedInstall(err)
		}
		in.track(fmt.Sprintf("stream '%s'", s.Name), func(ctx context.Context) error { return st.DeleteStream(ctx, made) })
		in.streamIDs[s.Key] = made
		in.add(InstalledEntity{Kind: KindStream, Key: s.Key, Name: s.Name, Action: ActionCreated, ID: &made, Detail: &detail, Fingerprint: fp})
	}
	return nil
}
