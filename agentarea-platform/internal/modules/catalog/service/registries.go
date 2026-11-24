package service

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"math"
	"regexp"
	"slices"
	"strings"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx/wirejson"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/catalog/domain"
)

// PlatformWorkspaceID is PLATFORM_WORKSPACE_ID.
const PlatformWorkspaceID = "platform"

// DefaultRegistryPriority is DEFAULT_REGISTRY_PRIORITY.
const DefaultRegistryPriority = 100

// ValueError is a ValueError the routes answer 400 with, verbatim.
type ValueError struct{ Msg string }

func (e *ValueError) Error() string { return e.Msg }

func valueErr(format string, a ...any) error { return &ValueError{Msg: fmt.Sprintf(format, a...)} }

// NotFoundError is a 404 with its detail.
type NotFoundError struct{ Detail string }

func (e *NotFoundError) Error() string { return e.Detail }

// ConflictError is a 409 with its detail.
type ConflictError struct{ Detail string }

func (e *ConflictError) Error() string { return e.Detail }

// ForbiddenError is a 403 with its detail.
type ForbiddenError struct{ Detail string }

func (e *ForbiddenError) Error() string { return e.Detail }

// PlatformWriteDetail is require_platform_catalog_write's refusal.
const PlatformWriteDetail = "Only the platform may modify the global registry catalog"

// ErrRegistryNotFound is the routes' 404 "Registry not found".
func ErrRegistryNotFound() error { return &NotFoundError{Detail: "Registry not found"} }

// ErrItemNotFound is the routes' 404 "Catalog item not found".
func ErrItemNotFound() error { return &NotFoundError{Detail: "Catalog item not found"} }

// ErrNoFields is the PATCH routes' 400.
func ErrNoFields() error { return &ValueError{Msg: "No fields to update"} }

// PyTuple is repr() of a tuple of strings.
func PyTuple(vs ...string) string {
	q := make([]string, len(vs))
	for i, v := range vs {
		q[i] = PyRepr(v)
	}
	if len(q) == 1 {
		return "(" + q[0] + ",)"
	}
	return "(" + strings.Join(q, ", ") + ")"
}

// PyRepr is repr() of a str.
func PyRepr(s string) string {
	quote := "'"
	if strings.Contains(s, "'") && !strings.Contains(s, `"`) {
		quote = `"`
	}
	var b strings.Builder
	b.WriteString(quote)
	for _, r := range s {
		switch {
		case r == '\\':
			b.WriteString(`\\`)
		case string(r) == quote:
			b.WriteString(`\` + quote)
		case r == '\n':
			b.WriteString(`\n`)
		case r == '\r':
			b.WriteString(`\r`)
		case r == '\t':
			b.WriteString(`\t`)
		case r < 0x20 || r == 0x7f:
			fmt.Fprintf(&b, `\x%02x`, r)
		default:
			b.WriteRune(r)
		}
	}
	b.WriteString(quote)
	return b.String()
}

var (
	githubRepo = regexp.MustCompile(`^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})/[A-Za-z0-9._-]{1,100}$`)
	gitRef     = regexp.MustCompile(`^[A-Za-z0-9_][A-Za-z0-9._/-]{0,254}$`)
)

// IsGitHubRepo is is_github_repo.
func IsGitHubRepo(v string) bool {
	if !githubRepo.MatchString(v) || strings.HasSuffix(v, "\n") {
		return false
	}
	_, name, _ := strings.Cut(v, "/")
	return name != "." && name != ".."
}

func checkGitRef(ref *string) error {
	if ref == nil {
		return nil
	}
	r := *ref
	if !gitRef.MatchString(r) || strings.HasSuffix(r, "\n") || strings.Contains(r, "..") || strings.Contains(r, "//") ||
		strings.HasSuffix(r, "/") || strings.HasSuffix(r, ".lock") {
		return valueErr("source_ref must be a branch, tag or commit name")
	}
	return nil
}

func checkSourcePath(path *string) error {
	if path == nil {
		return nil
	}
	stripped := strings.Trim(*path, "/")
	if stripped == "" {
		return nil
	}
	bad := strings.Contains(stripped, `\`) || strings.Contains(stripped, "\x00")
	for _, part := range strings.Split(stripped, "/") {
		if part == "" || part == "." || part == ".." {
			bad = true
		}
	}
	if bad {
		return valueErr("source_path must be a plain relative folder path")
	}
	return nil
}

// SourceCheck is validate_registry_source's arguments.
type SourceCheck struct {
	RegistryType, SourceType, SourceURL, Scope string
	WorkspaceID                                *string
	Mode, Trust                                *string
	Credentials                                bool
	SourceRef, SourcePath                      *string
}

func strOr(p *string) string {
	if p == nil {
		return "\x00none"
	}
	return *p
}

// ValidateSource is validate_registry_source.
func (s *Service) ValidateSource(ctx context.Context, c SourceCheck) error {
	if c.Scope != "platform" && c.Scope != "workspace" {
		return valueErr("scope must be one of %s", PyTuple("platform", "workspace"))
	}
	if m := strOr(c.Mode); m != "mirror" && m != "upstream" {
		return valueErr("mode must be one of %s", PyTuple("mirror", "upstream"))
	}
	trust := strOr(c.Trust)
	if !slices.Contains([]string{"official", "verified", "community", "private"}, trust) {
		return valueErr("trust must be one of %s", PyTuple("official", "verified", "community", "private"))
	}
	if err := checkGitRef(c.SourceRef); err != nil {
		return err
	}
	if err := checkSourcePath(c.SourcePath); err != nil {
		return err
	}
	if c.SourceType == "github" {
		if c.RegistryType != domain.TypeSkills {
			return valueErr("a GitHub repository source holds skills")
		}
		if !IsGitHubRepo(c.SourceURL) {
			return valueErr("a GitHub source_url is the repository as owner/repo")
		}
	}
	if c.Credentials && c.RegistryType == domain.TypeSkills && *c.Mode != "mirror" {
		return valueErr("a skills registry read with credentials mirrors its content")
	}
	if c.Scope == "platform" {
		if c.WorkspaceID != nil {
			return valueErr("a platform registry belongs to no workspace")
		}
		return nil
	}
	if c.WorkspaceID == nil || *c.WorkspaceID == "" {
		return valueErr("a workspace registry needs its workspace")
	}
	if c.RegistryType != domain.TypeSkills && c.RegistryType != domain.TypeAgents {
		return valueErr("a workspace registry holds skills or agents")
	}
	if c.SourceType != "url" && c.SourceType != "github" {
		return valueErr("a workspace registry's source_type is one of %s", PyTuple("url", "github"))
	}
	if trust != "private" && trust != "community" {
		return valueErr("a workspace registry's trust is one of %s", PyTuple("private", "community"))
	}
	if c.SourceType == "url" {
		if s.d.PublicHTTPS == nil {
			return errors.New("catalog: no outbound URL policy configured")
		}
		if !s.d.PublicHTTPS(ctx, c.SourceURL) {
			return valueErr("a workspace registry's index is a public https URL")
		}
	}
	return nil
}

func validatedPriority(p *int) (int, error) {
	if p == nil {
		return DefaultRegistryPriority, nil
	}
	if *p < 0 {
		return 0, valueErr("recommendation_priority must be a non-negative integer, got %d", *p)
	}
	if *p > math.MaxInt32 {
		return 0, valueErr("recommendation_priority must be at most %d, got %d", math.MaxInt32, *p)
	}
	return *p, nil
}

func (s *Service) requirePlatformWrite(ctx context.Context, c authn.Caller) error {
	ok, err := s.d.Authority.CanWrite(ctx, c, PlatformWorkspaceID)
	if err != nil {
		return err
	}
	if !ok {
		return &ForbiddenError{Detail: PlatformWriteDetail}
	}
	return nil
}

// RequirePlatformWrite is require_platform_catalog_write.
func (s *Service) RequirePlatformWrite(ctx context.Context, c authn.Caller) error {
	return s.requirePlatformWrite(ctx, c)
}

// CreateRegistry is create_registry; the caller has passed the platform
// write guard (platform scope) or the admin guard (workspace scope).
func (s *Service) CreateRegistry(ctx context.Context, ws scope.Workspace, n domain.NewRegistry, priority *int) (domain.Registry, error) {
	if !slices.Contains(domain.RegistryTypes(), n.RegistryType) {
		return domain.Registry{}, valueErr("registry_type must be one of %s", PyTuple(domain.RegistryTypes()...))
	}
	if !slices.Contains([]string{"url", "github", "api", "managed"}, n.SourceType) {
		return domain.Registry{}, valueErr("source_type must be one of %s", PyTuple("url", "github", "api", "managed"))
	}
	if n.SourceType == "managed" {
		if n.SourceURL == "" {
			n.SourceURL = "managed://catalog"
		}
	} else if n.SourceURL == "" {
		return domain.Registry{}, valueErr("source_url is required for synchronized registries")
	}
	if err := s.ValidateSource(ctx, SourceCheck{
		RegistryType: n.RegistryType, SourceType: n.SourceType, SourceURL: n.SourceURL, Scope: n.Scope,
		WorkspaceID: n.WorkspaceID, Mode: &n.Mode, Trust: &n.Trust, Credentials: n.CredentialsSecretRef != nil,
		SourceRef: n.SourceRef, SourcePath: n.SourcePath,
	}); err != nil {
		return domain.Registry{}, err
	}
	p, err := validatedPriority(priority)
	if err != nil {
		return domain.Registry{}, err
	}
	n.RecommendationPriority = p
	var out domain.Registry
	err = s.d.DB.Write(ctx, ws, func(ctx context.Context, sess db.Session) error {
		out, err = s.d.Registries.Create(ctx, sess, n, s.d.Now())
		return err
	})
	return out, err
}

// UpdateRegistry is update_registry on a registry the route found.
func (s *Service) UpdateRegistry(ctx context.Context, ws scope.Workspace, current domain.Registry, p domain.RegistryPatch) (domain.Registry, error) {
	if err := s.validatePatch(ctx, current, p); err != nil {
		return domain.Registry{}, err
	}
	clearEtag := p.SourceURL.Set || p.SourceType.Set || p.SourceRef.Set || p.SourcePath.Set || p.Mode.Set
	if p.RecommendationPriority.Set {
		v, err := validatedPriority(p.RecommendationPriority.Value)
		if err != nil {
			return domain.Registry{}, err
		}
		p.RecommendationPriority.Value = &v
	}
	var out domain.Registry
	err := s.d.DB.Write(ctx, ws, func(ctx context.Context, sess db.Session) error {
		r, ok, err := s.d.Registries.Update(ctx, sess, current.ID, p, clearEtag, s.d.Now())
		if err != nil {
			return err
		}
		if !ok {
			return ErrRegistryNotFound()
		}
		out = r
		return nil
	})
	return out, err
}

// validatePatch is update_registry's validate_registry_source over the
// fields a patch sets.
func (s *Service) validatePatch(ctx context.Context, current domain.Registry, p domain.RegistryPatch) error {
	if p.SourceURL.Set || p.SourceType.Set || p.SourceRef.Set || p.SourcePath.Set || p.Mode.Set || p.Trust.Set || p.CredentialsSecretRef.Set {
		pick := func(f domain.Field[*string], cur *string) *string {
			if f.Set {
				return f.Value
			}
			return cur
		}
		url := current.SourceURL
		if p.SourceURL.Set {
			url = strOr(p.SourceURL.Value)
		}
		if err := s.ValidateSource(ctx, SourceCheck{
			RegistryType: current.RegistryType, SourceType: *pick(p.SourceType, &current.SourceType), SourceURL: url, Scope: current.Scope,
			WorkspaceID: current.WorkspaceID, Mode: pick(p.Mode, &current.Mode), Trust: pick(p.Trust, &current.Trust),
			Credentials: pick(p.CredentialsSecretRef, current.CredentialsSecretRef) != nil,
			SourceRef:   pick(p.SourceRef, current.SourceRef), SourcePath: pick(p.SourcePath, current.SourcePath),
		}); err != nil {
			return err
		}
	}
	return nil
}

// PlatformRegistry is get_platform_registry.
func (s *Service) PlatformRegistry(ctx context.Context, ws scope.Workspace, id string) (domain.Registry, bool, error) {
	var r domain.Registry
	var ok bool
	err := s.read(ctx, ws, func(sess db.Session) (err error) {
		r, ok, err = s.d.Registries.Get(ctx, sess, id)
		return err
	})
	return r, ok && r.Scope == "platform", err
}

// WorkspaceRegistry is get_workspace_registry for ws.
func (s *Service) WorkspaceRegistry(ctx context.Context, ws scope.Workspace, id string) (domain.Registry, bool, error) {
	var r domain.Registry
	var ok bool
	err := s.read(ctx, ws, func(sess db.Session) (err error) {
		r, ok, err = s.d.Registries.Get(ctx, sess, id)
		return err
	})
	if !ok || r.Scope != "workspace" || r.WorkspaceID == nil || *r.WorkspaceID != ws.ID() {
		return domain.Registry{}, false, err
	}
	return r, true, err
}

// VisibleRegistry is get_visible_registry.
func (s *Service) VisibleRegistry(ctx context.Context, ws scope.Workspace, id string) (domain.Registry, bool, error) {
	var r domain.Registry
	var ok bool
	err := s.read(ctx, ws, func(sess db.Session) (err error) {
		r, ok, err = s.d.Registries.Get(ctx, sess, id)
		return err
	})
	if !ok || !r.Visible(ws.ID()) {
		return domain.Registry{}, false, err
	}
	return r, true, err
}

// ListRegistries is list_visible_registries.
func (s *Service) ListRegistries(ctx context.Context, ws scope.Workspace, activeOnly bool, registryType, regScope string) ([]domain.Registry, error) {
	var out []domain.Registry
	err := s.read(ctx, ws, func(sess db.Session) (err error) {
		out, err = s.d.Registries.ListVisible(ctx, sess, activeOnly, registryType, regScope)
		return err
	})
	return out, err
}

// DeleteRegistry is delete_registry.
func (s *Service) DeleteRegistry(ctx context.Context, ws scope.Workspace, id string) (bool, error) {
	var ok bool
	err := s.d.DB.Write(ctx, ws, func(ctx context.Context, sess db.Session) (err error) {
		ok, err = s.d.Registries.Delete(ctx, sess, id)
		return err
	})
	return ok, err
}

// RegistriesOf are the registries of a page of items.
func (s *Service) RegistriesOf(ctx context.Context, ws scope.Workspace, items []domain.Item) (map[string]domain.Registry, error) {
	ids := map[string]bool{}
	var list []string
	for _, i := range items {
		if !ids[i.RegistryID] {
			ids[i.RegistryID] = true
			list = append(list, i.RegistryID)
		}
	}
	out := map[string]domain.Registry{}
	if len(list) == 0 {
		return out, nil
	}
	err := s.read(ctx, ws, func(sess db.Session) (err error) {
		out, err = s.d.Registries.Many(ctx, sess, list)
		return err
	})
	return out, err
}

// ListItems is list_items on a visible registry.
func (s *Service) ListItems(ctx context.Context, ws scope.Workspace, registryID string, limit, offset int32) ([]domain.Item, error) {
	var out []domain.Item
	err := s.read(ctx, ws, func(sess db.Session) (err error) {
		out, err = s.d.Registries.ListItems(ctx, sess, registryID, limit, offset)
		return err
	})
	return out, err
}

// Browse is browse_catalog; sort is "recommended" or "name".
func (s *Service) Browse(ctx context.Context, ws scope.Workspace, f domain.BrowseFilter, sort string, limit, offset int32) (domain.Browse, error) {
	var out domain.Browse
	err := s.read(ctx, ws, func(sess db.Session) (err error) {
		out, err = s.d.Registries.Browse(ctx, sess, f, sort == "name", limit, offset)
		return err
	})
	return out, err
}

// Search is search_catalog: the tag is applied after paging.
func (s *Service) Search(ctx context.Context, ws scope.Workspace, q, tag string, updateAvailable *bool, limit, offset int32) ([]domain.Item, error) {
	pattern := ""
	if q != "" {
		pattern = "%" + q + "%"
	}
	var rows []domain.Item
	err := s.read(ctx, ws, func(sess db.Session) (err error) {
		rows, err = s.d.Registries.Search(ctx, sess, pattern, tag, updateAvailable, limit, offset)
		return err
	})
	return rows, err
}

// VisibleItem is get_item: nil for another workspace's item.
func (s *Service) VisibleItem(ctx context.Context, ws scope.Workspace, id string) (domain.Item, bool, error) {
	var it domain.Item
	var ok bool
	err := s.read(ctx, ws, func(sess db.Session) (err error) {
		it, ok, err = s.d.Registries.GetItem(ctx, sess, id)
		return err
	})
	if !ok || !it.Visible(ws.ID()) {
		return domain.Item{}, false, err
	}
	return it, true, err
}

// PlainJSON decodes raw into plain maps and slices for facet derivation.
func PlainJSON(raw []byte) any {
	v, err := wirejson.Unmarshal(raw)
	if err != nil {
		return nil
	}
	return plain(v)
}

func plain(v any) any {
	switch t := v.(type) {
	case wirejson.Object:
		m := make(map[string]any, len(t))
		for _, kv := range t {
			m[kv.Key] = plain(kv.Value)
		}
		return m
	case []any:
		out := make([]any, len(t))
		for i, e := range t {
			out[i] = plain(e)
		}
		return out
	}
	return v
}

func (s *Service) facets(ctx context.Context, registryType, name string, spec, tags []byte) domain.Facets {
	f, err := domain.DeriveFacets(registryType, name, PlainJSON(spec), PlainJSON(tags))
	if err != nil {
		s.d.Log.WarnContext(ctx, "Catalog entry declares malformed payers", slog.String("name", name), slog.Any("error", err))
	}
	return f
}

func managed(r domain.Registry) error {
	if r.SourceType != "managed" {
		return valueErr("Catalog items can only be written to a managed registry")
	}
	return nil
}

// CreateCatalogItem is create_catalog_item.
func (s *Service) CreateCatalogItem(ctx context.Context, ws scope.Workspace, registryID string, n domain.NewItem) (domain.Item, error) {
	var out domain.Item
	err := s.d.DB.Write(ctx, ws, func(ctx context.Context, sess db.Session) error {
		st := s.d.Registries
		r, ok, err := st.Get(ctx, sess, registryID)
		if err != nil {
			return err
		}
		if !ok {
			return &NotFoundError{Detail: "Registry " + registryID + " not found"}
		}
		if err := managed(r); err != nil {
			return err
		}
		if _, exists, err := st.ItemByExternalID(ctx, sess, registryID, n.ExternalID); err != nil {
			return err
		} else if exists {
			return &ConflictError{Detail: fmt.Sprintf("Catalog item %s already exists in registry %s", PyRepr(n.ExternalID), registryID)}
		}
		rank := 0
		if n.RecommendationRank != nil {
			rank = *n.RecommendationRank
		} else if rank, err = st.NextRank(ctx, sess, registryID); err != nil {
			return err
		}
		f := s.facets(ctx, r.RegistryType, n.Name, n.Spec, n.Tags)
		now := s.d.Now()
		if out, err = st.CreateItem(ctx, sess, registryID, n, rank, f, now); err != nil {
			return err
		}
		return st.SetItemCount(ctx, sess, registryID, now)
	})
	return out, err
}

// UpdateCatalogItem is update_catalog_item.
func (s *Service) UpdateCatalogItem(ctx context.Context, ws scope.Workspace, id string, p domain.ItemPatch) (domain.Item, error) {
	var out domain.Item
	err := s.d.DB.Write(ctx, ws, func(ctx context.Context, sess db.Session) error {
		st := s.d.Registries
		it, ok, err := st.GetItem(ctx, sess, id)
		if err != nil {
			return err
		}
		if !ok {
			return &NotFoundError{Detail: "Catalog item " + id + " not found"}
		}
		r, ok, err := st.Get(ctx, sess, it.RegistryID)
		if err != nil {
			return err
		}
		if !ok {
			return &NotFoundError{Detail: "Registry " + it.RegistryID + " not found"}
		}
		if r.SourceType != "managed" {
			return valueErr("Catalog items can only be written to a managed registry")
		}
		if p.ExternalID.Set && strOr(p.ExternalID.Value) != it.ExternalID {
			ext := strOr(p.ExternalID.Value)
			if _, exists, err := st.ItemByExternalID(ctx, sess, it.RegistryID, ext); err != nil {
				return err
			} else if exists {
				return &ConflictError{Detail: fmt.Sprintf("Catalog item %s already exists in registry %s", PyRepr(ext), it.RegistryID)}
			}
		}
		name, spec, tags := it.Name, []byte(it.Spec), []byte(it.Tags)
		if p.Name.Set {
			name = strOr(p.Name.Value)
		}
		if p.Spec.Set {
			spec = p.Spec.Value
		}
		if p.Tags.Set {
			tags = p.Tags.Value
		}
		f := s.facets(ctx, r.RegistryType, name, spec, tags)
		updated, ok, err := st.UpdateItem(ctx, sess, id, p, f, s.d.Now())
		if err != nil {
			return err
		}
		if !ok {
			return &NotFoundError{Detail: "Catalog item " + id + " not found"}
		}
		out = updated
		return nil
	})
	return out, err
}

// DeleteCatalogItem is delete_catalog_item.
func (s *Service) DeleteCatalogItem(ctx context.Context, ws scope.Workspace, id string) error {
	return s.d.DB.Write(ctx, ws, func(ctx context.Context, sess db.Session) error {
		st := s.d.Registries
		it, ok, err := st.GetItem(ctx, sess, id)
		if err != nil {
			return err
		}
		if !ok {
			return &NotFoundError{Detail: "Catalog item " + id + " not found"}
		}
		r, ok, err := st.Get(ctx, sess, it.RegistryID)
		if err != nil {
			return err
		}
		if !ok {
			return &NotFoundError{Detail: "Registry " + it.RegistryID + " not found"}
		}
		if r.SourceType != "managed" {
			return valueErr("Catalog items can only be written to a managed registry")
		}
		if deleted, err := st.DeleteItem(ctx, sess, id); err != nil {
			return err
		} else if !deleted {
			return &NotFoundError{Detail: "Catalog item " + id + " not found"}
		}
		return st.SetItemCount(ctx, sess, r.ID, s.d.Now())
	})
}
