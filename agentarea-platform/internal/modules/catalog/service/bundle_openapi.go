package service

import (
	"context"
	"errors"
	"fmt"
	"strings"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx/wirejson"
	catalogapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/catalog/api"
)

func (o BundleOpenAPI) specKey() string      { return o.Key }
func (o BundleOpenAPI) renamedFrom() *string { return o.RenamedFrom }

func openAPIKeys(b *Bundle) map[string]bool {
	out := map[string]bool{}
	for _, o := range b.OpenAPI {
		out[o.Key] = true
	}
	return out
}

func openAPITool(id string) catalogapi.BundleTool {
	return catalogapi.BundleTool{Type: "openapi", Name: id, ConnectionID: strp(id)}
}

func openAPIDetail(o BundleOpenAPI) string {
	if o.SpecURL != nil {
		return "spec at " + *o.SpecURL
	}
	return "inline spec"
}

// readsSecretSetup reports a value reading a secret setup field.
func readsSecretSetup(b *Bundle, value string) bool {
	for _, k := range setupRefsOf(value) {
		if f, ok := b.SetupField(k); ok && f.Type == SetupSecret {
			return true
		}
	}
	return false
}

func (o BundleOpenAPI) params() []StrPairs { return []StrPairs{o.Headers, o.Query, o.Variables} }

// suppliesOpenAPISecret reports a secret setup value given to this deploy
// that o reads: the fingerprint never sees it, so the connection is written.
func suppliesOpenAPISecret(b *Bundle, o BundleOpenAPI, supplied map[string]bool) bool {
	for _, ps := range o.params() {
		for _, p := range ps {
			for _, k := range setupRefsOf(p.Value) {
				if f, ok := b.SetupField(k); ok && f.Type == SetupSecret && supplied[k] {
					return true
				}
			}
		}
	}
	return false
}

// openAPIParams are ps as the connection takes them: a workspace secret by
// name, else the value resolved from values; one still unresolved is kept as
// stored when keep, else left out.
func openAPIParams(b *Bundle, ps StrPairs, values wirejson.Object, keep, query bool) []catalogapi.BundleOpenAPIParam {
	out := []catalogapi.BundleOpenAPIParam{}
	for _, p := range ps {
		if name, ok := secretBinding(p.Value); ok {
			out = append(out, catalogapi.BundleOpenAPIParam{Name: p.Key, SecretName: strp(name), Secret: query})
			continue
		}
		secret := query && readsSecretSetup(b, p.Value) // pragma: allowlist secret
		v := resolvePlaceholders(p.Value, values)
		switch {
		case len(setupRefsOf(v)) == 0:
			out = append(out, catalogapi.BundleOpenAPIParam{Name: p.Key, Value: v, Secret: secret})
		case keep:
			out = append(out, catalogapi.BundleOpenAPIParam{Name: p.Key, Keep: true, Secret: secret})
		}
	}
	return out
}

func openAPISpecOf(b *Bundle, o BundleOpenAPI, values wirejson.Object, keep bool) catalogapi.BundleOpenAPISpec {
	out := catalogapi.BundleOpenAPISpec{Name: o.Name, BaseURL: resolvePlaceholders(o.BaseURL, values),
		Headers: openAPIParams(b, o.Headers, values, keep, false), Query: openAPIParams(b, o.Query, values, keep, true),
		Variables: openAPIParams(b, o.Variables, values, keep, false)}
	if o.Description != "" {
		out.Description = strp(o.Description)
	}
	if o.SpecURL != nil {
		out.SpecURL = strp(resolvePlaceholders(*o.SpecURL, values))
	}
	if o.Spec != nil {
		out.Spec = *o.Spec
	}
	return out
}

func (a *bundleAnalyzer) openAPIValueIssues(ctx context.Context, o BundleOpenAPI, what, name, value string, secretField bool,
	setupKeys map[string]bool, secrets *[]string, issues *[]PreviewIssue) error {
	block := func(format string, args ...any) {
		*issues = append(*issues, blockIssue(o.Key, fmt.Sprintf("openapi '%s' %s '%s' ", o.Key, what, name)+fmt.Sprintf(format, args...)))
	}
	if secret, ok := secretBinding(value); ok {
		*secrets = append(*secrets, fmt.Sprintf("%s from secret '%s'", name, secret))
		if a.checks == nil {
			return nil
		}
		problem, err := a.checks.secretProblem(ctx, secret)
		if err != nil || problem == "" {
			return err
		}
		block("%s", problem)
		return nil
	}
	if mentionsSecret(value) {
		block("must be ${secret.<name>} alone")
		return nil
	}
	refs := setupRefsOf(value)
	for _, k := range refs {
		if !setupKeys[k] {
			block("references unknown setup field '%s'", k)
		}
	}
	if secretField && len(refs) == 0 {
		block("must be ${secret.<name>} or reference ${setup.<key>}")
	}
	return nil
}

func (a *bundleAnalyzer) analyzeOpenAPIs(ctx context.Context, b *Bundle, setupKeys map[string]bool, entities *[]PreviewEntity, issues *[]PreviewIssue) error {
	for _, o := range b.OpenAPI {
		var secrets []string
		addresses := []struct{ what, value string }{{"base_url", o.BaseURL}}
		if o.SpecURL != nil {
			addresses = append(addresses, struct{ what, value string }{"spec_url", *o.SpecURL})
		}
		for _, u := range addresses {
			if mentionsSecret(u.value) {
				*issues = append(*issues, blockIssue(o.Key, fmt.Sprintf("openapi '%s' %s may not read a secret; put it in a header or query parameter", o.Key, u.what)))
			}
			for _, k := range setupRefsOf(u.value) {
				if !setupKeys[k] {
					*issues = append(*issues, blockIssue(o.Key, fmt.Sprintf("openapi '%s' %s references unknown setup field '%s'", o.Key, u.what, k)))
				}
			}
		}
		for _, group := range []struct {
			what   string
			params StrPairs
			secret func(string) bool
		}{{"header", o.Headers, a.shapes.HeaderIsSecret}, {"query parameter", o.Query, func(string) bool { return false }},
			{"variable", o.Variables, func(string) bool { return false }}} {
			for _, p := range group.params {
				if err := a.openAPIValueIssues(ctx, o, group.what, p.Key, p.Value, group.secret(p.Key), setupKeys, &secrets, issues); err != nil {
					return err
				}
			}
		}
		status, err := a.plan(ctx, KindOpenAPI, o, nil, nil)
		if err != nil {
			return err
		}
		if status == StatusUnchanged && suppliesOpenAPISecret(b, o, suppliedKeys(a.supplied)) {
			status = StatusWillUpdate
			a.planned[entityRef{KindOpenAPI, o.Key}] = status
		}
		detail := openAPIDetail(o)
		if len(secrets) > 0 {
			detail += "; " + strings.Join(secrets, "; ")
		}
		*entities = append(*entities, PreviewEntity{Kind: KindOpenAPI, Key: o.Key, Name: o.Name, Status: status, Detail: &detail})
	}
	return nil
}

func (in *bundleInstaller) installOpenAPIs(ctx context.Context) error {
	w := in.w
	op := w.b.d.OpenAPIs
	in.openapiIDs = map[string]string{}
	for _, o := range in.pkg.OpenAPI {
		detail := openAPIDetail(o)
		fp, err := in.fingerprint(o)
		if err != nil {
			return err
		}
		id, _, err := in.owned(ctx, KindOpenAPI, o.Key)
		if err != nil {
			return err
		}
		if id != nil {
			in.openapiIDs[o.Key] = *id
			update, err := in.needsUpdate(KindOpenAPI, o, nil)
			if err != nil {
				return err
			}
			action := ActionUnchanged
			if update || suppliesOpenAPISecret(in.pkg, o, in.supplied) {
				if err := in.authorizeUpdate(ctx, KindOpenAPI, o.Key, *id); err != nil {
					return err
				}
				err := op.UpdateOpenAPI(ctx, w.c, *id, openAPISpecOf(in.pkg, o, in.values, true))
				if errors.Is(err, catalogapi.ErrBundleEntityGone) {
					return installError(fmt.Sprintf("openapi '%s' disappeared mid-update", o.Key))
				}
				if err := refusedInstall(err); err != nil {
					return err
				}
				in.updatedInPlace = true
				action = ActionUpdated
			}
			in.add(InstalledEntity{Kind: KindOpenAPI, Key: o.Key, Name: o.Name, Action: action, ID: id, Detail: &detail, Fingerprint: fp})
			continue
		}
		reused, err := in.reused(ctx, KindOpenAPI, o.Key)
		if err != nil {
			return err
		}
		if reused != nil {
			in.openapiIDs[o.Key] = *reused
			in.add(reusedEntity(KindOpenAPI, o.Key, o.Name, *reused))
			continue
		}
		made, err := op.CreateOpenAPI(ctx, w.c, openAPISpecOf(in.pkg, o, in.values, false))
		if err != nil {
			return refusedInstall(err)
		}
		in.track(fmt.Sprintf("openapi connection '%s'", o.Name), func(ctx context.Context) error { return op.DeleteOpenAPI(ctx, w.c, made) })
		in.openapiIDs[o.Key] = made
		in.add(InstalledEntity{Kind: KindOpenAPI, Key: o.Key, Name: o.Name, Action: ActionCreated, ID: &made, Detail: &detail, Fingerprint: fp})
	}
	return nil
}
