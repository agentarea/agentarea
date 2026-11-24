package service

import (
	"context"
	"encoding/json"
	"fmt"
	"log/slog"
	"strconv"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/catalog/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/catalog/domain"
)

// ManifestError is a malformed reconcile manifest: nothing ran.
type ManifestError struct{ Msg string }

func (e *ManifestError) Error() string { return e.Msg }

func manifestString(c map[string]any, k string) *string {
	switch v := c[k].(type) {
	case string:
		return &v
	case nil:
		return nil
	default:
		s := fmt.Sprint(v)
		return &s
	}
}

func manifestInt(c map[string]any, k string) (*int, error) {
	var i int
	switch v := c[k].(type) {
	case nil:
		return nil, nil
	case int:
		i = v
	case int64:
		i = int(v)
	case float64:
		if v != float64(int(v)) {
			return nil, valueErr("%s must be an integer", k)
		}
		i = int(v)
	case json.Number:
		n, err := strconv.Atoi(string(v))
		if err != nil {
			return nil, valueErr("%s must be an integer", k)
		}
		i = n
	default:
		return nil, valueErr("%s must be an integer", k)
	}
	return &i, nil
}

func retired(c map[string]any) bool { b, ok := c["active"].(bool); return ok && !b }

func strDefault(c map[string]any, k, d string) string {
	if v := manifestString(c, k); v != nil {
		return *v
	}
	return d
}

// validateManifest is _reconcile's up-front check of every entry.
func validateManifest(m []map[string]any) error {
	for i, c := range m {
		_, named := c["name"]
		_, hasURL := c["source_url"]
		if c == nil || !named || (!hasURL && !retired(c)) {
			return &ManifestError{Msg: fmt.Sprintf("Registry entry %d must be a mapping with 'name' and 'source_url'", i)}
		}
	}
	return nil
}

// manifestRegistryType is manifest_registry_type.
func (s *Service) manifestRegistryType(ctx context.Context, c map[string]any) (string, error) {
	t := manifestString(c, "type")
	if strDefault(c, "source_type", "") == "github" {
		if t != nil && *t != domain.TypeSkills {
			return "", valueErr("Registry %s: a github source holds skills, not %s", PyRepr(*manifestString(c, "name")), PyRepr(*t))
		}
		return domain.TypeSkills, nil
	}
	if t != nil && *t != "" {
		return *t, nil
	}
	data, err := s.d.Fetch.PlatformSource(ctx, *manifestString(c, "source_url"))
	if err != nil {
		return "", err
	}
	typ, err := DetectType(data)
	if err != nil {
		return "", valueErr("%s", err.Error())
	}
	return typ, nil
}

func sameStr(a, b *string) bool {
	if a == nil || b == nil {
		return a == b
	}
	return *a == *b
}

// reconcilePatch is reconcile_existing_registry's changes: the patch and the
// names of the fields it changes.
func reconcilePatch(existing domain.Registry, c map[string]any, credentials *string) (domain.RegistryPatch, []string, error) {
	if t := manifestString(c, "type"); t != nil && *t != "" && *t != existing.RegistryType {
		return domain.RegistryPatch{}, nil, valueErr("Registry %s holds %s, the manifest says %s: retire it (active: false) and add the new source under a new name",
			PyRepr(existing.Name), existing.RegistryType, *t)
	}
	var p domain.RegistryPatch
	var changed []string
	str := func(name string, f *domain.Field[*string], want, have *string) {
		if !sameStr(want, have) {
			*f = domain.Field[*string]{Set: true, Value: want}
			changed = append(changed, name)
		}
	}
	sourceType := strDefault(c, "source_type", "url")
	str("source_type", &p.SourceType, &sourceType, &existing.SourceType)
	str("source_url", &p.SourceURL, manifestString(c, "source_url"), &existing.SourceURL)
	str("source_ref", &p.SourceRef, manifestString(c, "source_ref"), existing.SourceRef)
	str("source_path", &p.SourcePath, manifestString(c, "source_path"), existing.SourcePath)
	if _, ok := c["mode"]; ok {
		str("mode", &p.Mode, manifestString(c, "mode"), &existing.Mode)
	}
	if _, ok := c["trust"]; ok {
		str("trust", &p.Trust, manifestString(c, "trust"), &existing.Trust)
	}
	prio, err := manifestInt(c, "recommendation_priority")
	if err != nil {
		return p, nil, err
	}
	if prio != nil && *prio != existing.RecommendationPriority {
		p.RecommendationPriority = domain.Field[*int]{Set: true, Value: prio}
		changed = append(changed, "recommendation_priority")
	}
	str("credentials_secret_ref", &p.CredentialsSecretRef, credentials, existing.CredentialsSecretRef)
	return p, changed, nil
}

// Reconcile is `agentarea-api reconcile`: make the platform registries what
// the manifest says and sync them, each under its own session lock; retired
// entries last, their uses moved onto the registries synced before them.
func (s *Service) Reconcile(ctx context.Context, o api.ReconcileOptions) (api.ReconcileResult, error) {
	res := api.ReconcileResult{Failed: map[string]string{}, WorkspaceFailed: map[string]string{}}
	if !s.HasSync() {
		return res, ErrNoSync
	}
	if err := validateManifest(o.Manifest); err != nil {
		return res, err
	}
	var ordered []map[string]any
	for _, c := range o.Manifest {
		if !retired(c) {
			ordered = append(ordered, c)
		}
	}
	for _, c := range o.Manifest {
		if retired(c) {
			ordered = append(ordered, c)
		}
	}
	var replacements []string
	for _, c := range ordered {
		name := *manifestString(c, "name")
		var synced string
		held, err := s.d.DB.TrySessionLock(ctx, db.TextKey("registry-sync:platform:"+name), func(ctx context.Context, _ db.Querier) error {
			id, err := s.reconcileOne(ctx, c, name, replacements, o.Force)
			synced = id
			return err
		})
		switch {
		case err != nil:
			s.d.Log.ErrorContext(ctx, "Reconcile failed for registry", slog.String("registry", name), slog.Any("error", err))
			res.Failed[name] = err.Error()
		case !held:
			s.d.Log.WarnContext(ctx, "Skipped registry: another reconcile is syncing it", slog.String("registry", name))
			res.Skipped = append(res.Skipped, name)
		default:
			res.Succeeded = append(res.Succeeded, name)
			if synced != "" {
				replacements = append(replacements, synced)
			}
		}
	}
	if o.WorkspaceRegistries {
		s.reconcileWorkspaces(ctx, o.Force, &res)
	}
	return res, nil
}

// reconcileOne makes one manifest entry so and syncs it; the id synced, ""
// for a retired entry.
func (s *Service) reconcileOne(ctx context.Context, c map[string]any, name string, replacements []string, force bool) (string, error) {
	ws := platformWorkspace()
	var existing domain.Registry
	var found bool
	if err := s.read(ctx, ws, func(sess db.Session) (err error) {
		existing, found, err = s.d.Sync.PlatformByName(ctx, sess, name)
		return err
	}); err != nil {
		return "", err
	}
	if retired(c) {
		if found {
			deleted, err := s.RetireRegistry(ctx, existing.ID, replacements)
			if err != nil {
				return "", err
			}
			s.d.Log.InfoContext(ctx, "Retired registry", slog.String("registry_id", existing.ID), slog.Int("deleted", deleted))
		}
		return "", nil
	}
	var credentials *string
	if ref := manifestString(c, "credentials_secret_ref"); ref != nil && *ref != "" {
		if s.d.PlatformSecrets == nil {
			return "", &ConfigurationError{Msg: fmt.Sprintf("Registry %s names credentials but this reconcile has no platform secrets", PyRepr(name))}
		}
		id, err := s.d.PlatformSecrets.SecretID(ctx, *ref)
		if err != nil {
			return "", err
		}
		credentials = &id
	}
	hadCredentials := found && existing.CredentialsSecretRef != nil
	var id string
	if found {
		id = existing.ID
		p, changed, err := reconcilePatch(existing, c, credentials)
		if err != nil {
			return "", err
		}
		if len(changed) > 0 {
			if _, err := s.UpdateRegistry(ctx, ws, existing, p); err != nil {
				return "", err
			}
			s.d.Log.InfoContext(ctx, "Reconcile changed registry", slog.String("registry", name), slog.String("registry_id", id), slog.Any("fields", changed))
		}
	} else {
		typ, err := s.manifestRegistryType(ctx, c)
		if err != nil {
			return "", err
		}
		prio, err := manifestInt(c, "recommendation_priority")
		if err != nil {
			return "", err
		}
		r, err := s.CreateRegistry(ctx, ws, domain.NewRegistry{
			Name: name, RegistryType: typ, SourceType: strDefault(c, "source_type", "url"), SourceURL: *manifestString(c, "source_url"),
			Description: manifestString(c, "description"), Scope: "platform", Mode: strDefault(c, "mode", "mirror"),
			Trust: strDefault(c, "trust", "official"), CredentialsSecretRef: credentials,
			SourceRef: manifestString(c, "source_ref"), SourcePath: manifestString(c, "source_path"),
		}, prio)
		if err != nil {
			return "", err
		}
		id = r.ID
		s.d.Log.InfoContext(ctx, "Created registry", slog.String("registry", name), slog.String("registry_id", id))
	}
	if credentials != nil || hadCredentials {
		if s.d.PlatformSecrets == nil {
			return "", &ConfigurationError{Msg: fmt.Sprintf("Registry %s had credentials but this reconcile has no platform secrets", PyRepr(name))}
		}
		if err := s.d.PlatformSecrets.RecordReference(ctx, id, credentials); err != nil {
			return "", err
		}
	}
	st, err := s.SyncRegistry(ctx, id, force)
	if err != nil {
		return id, err
	}
	if st.Skipped > 0 {
		s.d.Log.WarnContext(ctx, "Reconcile skipped items that failed validation", slog.String("registry", name), slog.Int("skipped", st.Skipped))
	}
	return id, nil
}

// reconcileWorkspaces is _reconcile_workspace_registries: a tenant's broken
// source is recorded on its registry and reported, never failing the run.
func (s *Service) reconcileWorkspaces(ctx context.Context, force bool, res *api.ReconcileResult) {
	var rs []domain.Registry
	if err := s.read(ctx, platformWorkspace(), func(sess db.Session) (err error) {
		rs, err = s.d.Sync.ActiveWorkspaceRegistries(ctx, sess)
		return err
	}); err != nil {
		s.d.Log.ErrorContext(ctx, "Could not list workspace registries", slog.Any("error", err))
		res.WorkspaceFailed["*"] = err.Error()
		return
	}
	for _, r := range rs {
		label := r.Name
		if r.WorkspaceID != nil {
			label = *r.WorkspaceID + "/" + r.Name
		}
		held, err := s.d.DB.TrySessionLock(ctx, db.TextKey("registry-sync:"+r.ID), func(ctx context.Context, _ db.Querier) error {
			_, err := s.SyncRegistry(ctx, r.ID, force)
			return err
		})
		switch {
		case err != nil:
			s.d.Log.ErrorContext(ctx, "Reconcile failed for workspace registry", slog.String("registry", label), slog.Any("error", err))
			res.WorkspaceFailed[label] = err.Error()
		case !held:
			s.d.Log.WarnContext(ctx, "Skipped workspace registry: another reconcile is syncing it", slog.String("registry", label))
			res.Skipped = append(res.Skipped, label)
		default:
			res.WorkspaceSynced = append(res.WorkspaceSynced, label)
		}
	}
}
