package service

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log/slog"
	"math"
	"reflect"
	"slices"
	"strings"
	"time"

	"crypto/sha256"
	"encoding/hex"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/money"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/catalog/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/catalog/domain"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/catalog/store"
)

// SyncFormat is part of the stored ETag: bump it when parsing or facets
// change, so the next sync re-applies every source.
const SyncFormat = "9"

// Sync budgets (service.py).
const (
	maxSkippedDetails    = 50
	maxPointerChecks     = 50
	workspaceSyncTimeout = 120 * time.Second
	pointerCheckTimeout  = 120 * time.Second
)

// SyncStore is store.Sync.
type SyncStore interface {
	PlatformByName(ctx context.Context, s db.Session, name string) (domain.Registry, bool, error)
	ActiveOfType(ctx context.Context, s db.Session, registryType string) ([]domain.Registry, error)
	ActiveWorkspaceRegistries(ctx context.Context, s db.Session) ([]domain.Registry, error)
	InsertItem(ctx context.Context, s db.Session, it store.SyncedItem, now time.Time) (domain.Item, error)
	SetItem(ctx context.Context, s db.Session, it store.SyncedItem, now time.Time) error
	SetInstalled(ctx context.Context, s db.Session, itemID string, entityID, version *string, now time.Time) error
	SetVersion(ctx context.Context, s db.Session, itemID, version string, now time.Time) error
	MarkInSource(ctx context.Context, s db.Session, registryID string, externalIDs []string) (int, error)
	Moves(ctx context.Context, s db.Session, registryID string, replacements []string) ([]api.ItemMove, error)
	MoveOwn(ctx context.Context, s db.Session, moves []api.ItemMove) (int, error)
	ReplacedCopies(ctx context.Context, s db.Session, registryID string, replacements []string) ([]store.ReplacedCopy, error)
	DeletePlatformServer(ctx context.Context, s db.Session, id uuid.UUID) error
	DroppedProviders(ctx context.Context, s db.Session, registryID string) ([]uuid.UUID, error)
	ProviderModels(ctx context.Context, s db.Session, providers []uuid.UUID) ([]store.ProviderModel, error)
	DroppedModels(ctx context.Context, s db.Session, registryID string) ([]uuid.UUID, error)
	DeleteProviders(ctx context.Context, s db.Session, registryID string, ids []uuid.UUID) (int, error)
	DeleteModels(ctx context.Context, s db.Session, registryID string, ids []uuid.UUID) (int, error)
	UnheldOutOfSource(ctx context.Context, s db.Session, registryID string) ([]uuid.UUID, error)
	DeleteItems(ctx context.Context, s db.Session, registryID string, ids []uuid.UUID) (int, error)
	RecordSync(ctx context.Context, s db.Session, registryID string, itemCount int, etag *string, now time.Time) error
	TouchSync(ctx context.Context, s db.Session, registryID string, now time.Time) error
	RecordSyncError(ctx context.Context, s db.Session, registryID, msg string, now time.Time) error
	InstalledItems(ctx context.Context, s db.Session, registryID string) ([]domain.Item, error)
	UpsertProvider(ctx context.Context, s db.Session, p store.ProviderRow, now time.Time) (uuid.UUID, error)
	ProviderIDByKey(ctx context.Context, s db.Session, key string) (uuid.UUID, bool, error)
	UpsertModel(ctx context.Context, s db.Session, m store.ModelRow, now time.Time) (uuid.UUID, error)
	ResyncCachePrices(ctx context.Context, s db.Session, provider uuid.UUID, model string, oldCached, newCached, oldCreation, newCreation *money.Decimal) (int, error)
	InsertMirror(ctx context.Context, s db.Session, itemID uuid.UUID, name, slug string, m store.MirroredServer, now time.Time) (uuid.UUID, error)
	MirrorSlugTaken(ctx context.Context, s db.Session, slug string) (bool, error)
	BackfillMirror(ctx context.Context, s db.Session, id uuid.UUID, jsonSpec, envSchema []byte, remoteURL, registryURL *string) error
	UpdateMirror(ctx context.Context, s db.Session, id uuid.UUID, m store.MirroredServer, now time.Time) error
	CountItems(ctx context.Context, s db.Session, registryID string) (int, error)
}

// SyncError is RegistrySyncError: Msg is the classified reason a failed
// sync records and answers (sync_error_message), never the source's text.
type SyncError struct {
	Msg string
	Err error
}

func (e *SyncError) Error() string { return e.Msg }
func (e *SyncError) Unwrap() error { return e.Err }

// ConfigurationError is RegistryConfigurationError.
type ConfigurationError struct{ Msg string }

func (e *ConfigurationError) Error() string { return e.Msg }

// SyncStats is sync_registry's stats.
type SyncStats struct {
	NewSpecs, UpdatesFlagged, Applied, Unchanged, Total, Skipped int
	SkippedItems                                                 []SkippedItem
	OutOfSource                                                  *int
	Deleted                                                      int
	SourceUnchanged                                              bool
	PointersChecked                                              int
}

// SkippedItem is one item a sync skipped and why.
type SkippedItem struct{ ExternalID, Reason string }

// SyncErrorMessage is sync_error_message.
func SyncErrorMessage(err error) string {
	var (
		se  *SourceError
		ie  *IndexError
		ce  *ConfigurationError
		sy  *SyncError
		ge  *GitHubError
		hs  *httpStatus
		un  *unreachable
		ve  *ValueError
		ent *entryError
	)
	switch {
	case errors.As(err, &sy):
		return sy.Msg
	case errors.As(err, &se):
		return se.Msg
	case errors.As(err, &ie):
		return ie.Msg
	case errors.As(err, &ce):
		return ce.Msg
	case errors.As(err, &ge):
		if ge.Status == 0 {
			return "GitHub returned something this sync cannot read"
		}
		return fmt.Sprintf("GitHub answered %d", ge.Status)
	case errors.As(err, &hs):
		return hs.Error()
	case errors.As(err, &un):
		return un.Error()
	case errors.As(err, &ve):
		return ve.Msg
	case errors.As(err, &ent):
		return ent.msg
	}
	return "the sync failed; the server log has the cause"
}

// entryError is a ValueError naming what an index published.
type entryError struct{ msg string }

func (e *entryError) Error() string { return e.msg }

func entryErr(format string, a ...any) error { return &entryError{msg: fmt.Sprintf(format, a...)} }

func platformWorkspace() scope.Workspace {
	ws, _ := scope.NewWorkspace(PlatformWorkspaceID, PlatformWorkspaceID)
	return ws
}

func registryWorkspace(r domain.Registry) scope.Workspace {
	if r.WorkspaceID == nil {
		return platformWorkspace()
	}
	ws, err := scope.NewWorkspace(*r.WorkspaceID, *r.WorkspaceID)
	if err != nil {
		return platformWorkspace()
	}
	return ws
}

// HasSync is whether sync has every port it needs.
func (s *Service) HasSync() bool { return s.d.Uses != nil && s.d.Fetch.Net != nil }

// ErrNoSync: a sync was reached without its ports.
var ErrNoSync = errors.New("catalog: sync needs the item-use and outbound ports")

// SyncRegistry is sync_registry: fetch, upsert, retire what the source
// dropped, then check unpinned pointers within their own budget.
func (s *Service) SyncRegistry(ctx context.Context, id string, force bool) (SyncStats, error) {
	if !s.HasSync() {
		return SyncStats{}, ErrNoSync
	}
	var r domain.Registry
	var found bool
	if err := s.read(ctx, platformWorkspace(), func(sess db.Session) (err error) {
		r, found, err = s.d.Registries.Get(ctx, sess, id)
		return err
	}); err != nil {
		return SyncStats{}, err
	}
	if !found {
		return SyncStats{}, &NotFoundError{Detail: "Registry " + id + " not found"}
	}
	if r.SourceType == "managed" {
		return SyncStats{}, valueErr("Managed registry items are changed through the catalog item API")
	}
	sctx, cancel := ctx, context.CancelFunc(func() {})
	if r.Scope == "workspace" {
		sctx, cancel = context.WithTimeout(ctx, workspaceSyncTimeout)
	}
	stats, err := s.sync(sctx, r, force)
	timedOut := r.Scope == "workspace" && errors.Is(sctx.Err(), context.DeadlineExceeded)
	cancel()
	if err != nil {
		if timedOut {
			err = &SyncError{Msg: fmt.Sprintf("the sync took longer than %g s", workspaceSyncTimeout.Seconds()), Err: err}
		}
		msg := SyncErrorMessage(err)
		s.d.Log.ErrorContext(ctx, "Registry sync failed", slog.String("registry_id", id), slog.Any("error", err))
		if werr := s.d.DB.Write(ctx, registryWorkspace(r), func(ctx context.Context, sess db.Session) error {
			return s.d.Sync.RecordSyncError(ctx, sess, r.ID, msg, s.d.Now())
		}); werr != nil {
			s.d.Log.ErrorContext(ctx, "Could not record why the registry failed to sync", slog.String("registry_id", id), slog.Any("error", werr))
		}
		return SyncStats{}, &SyncError{Msg: msg, Err: err}
	}
	stats.PointersChecked = s.checkPointers(ctx, r)
	return stats, nil
}

func (s *Service) credentials(ctx context.Context, r domain.Registry) (string, error) {
	if r.CredentialsSecretRef == nil {
		return "", nil
	}
	if s.d.Credentials == nil {
		return "", &ConfigurationError{Msg: fmt.Sprintf("Registry %s has credentials but this sync has no way to resolve them", r.ID)}
	}
	ws := PlatformWorkspaceID
	if r.WorkspaceID != nil {
		ws = *r.WorkspaceID
	}
	return s.d.Credentials(ctx, ws, *r.CredentialsSecretRef)
}

func (s *Service) sync(ctx context.Context, r domain.Registry, force bool) (SyncStats, error) {
	mirrors := r.RegistryType == domain.TypeSkills && r.Mode == "mirror"
	if mirrors && s.d.Mirror == nil {
		return SyncStats{}, &ConfigurationError{Msg: fmt.Sprintf("Registry %s mirrors its content but this sync has no store for it", r.ID)}
	}
	token := ""
	if r.SourceType == "github" || mirrors {
		t, err := s.credentials(ctx, r)
		if err != nil {
			return SyncStats{}, err
		}
		token = t
	}
	var gh GitHubSource
	var head string
	var sourceEtag *string
	switch {
	case r.SourceType == "github":
		gh = s.d.Fetch.Repo(token)
		h, err := gh.Head(ctx, r.SourceURL, r.SourceRef)
		if err != nil {
			return SyncStats{}, err
		}
		head, sourceEtag = h, &h
	case r.Scope == "workspace":
		e, err := s.d.Fetch.WorkspaceEtag(ctx, r.SourceURL)
		if err != nil {
			return SyncStats{}, err
		}
		sourceEtag = e
	default:
		sourceEtag = s.d.Fetch.PlatformEtag(ctx, r.SourceURL)
	}
	var etag *string
	if sourceEtag != nil {
		e := SyncFormat + ":" + *sourceEtag
		etag = &e
	}
	ws := registryWorkspace(r)
	if !force && etag != nil && r.SourceEtag != nil && *etag == *r.SourceEtag {
		err := s.d.DB.Write(ctx, ws, func(ctx context.Context, sess db.Session) error {
			return s.d.Sync.TouchSync(ctx, sess, r.ID, s.d.Now())
		})
		return SyncStats{Unchanged: r.ItemCount, Total: r.ItemCount, SkippedItems: []SkippedItem{}, SourceUnchanged: true}, err
	}

	var parsed []Entry
	if gh != nil {
		limit := 0
		if r.Scope == "workspace" {
			limit = maxWorkspaceGitHubSkills
		}
		items, err := BuildGitHubSkillIndex(ctx, gh, r.SourceURL, head, r.SourcePath, limit)
		if err != nil {
			return SyncStats{}, err
		}
		parsed = items
	} else {
		var raw any
		var err error
		if r.Scope == "workspace" {
			raw, err = s.d.Fetch.WorkspaceSource(ctx, r.SourceURL)
		} else {
			raw, err = s.d.Fetch.PlatformSource(ctx, r.SourceURL)
		}
		if err != nil {
			return SyncStats{}, err
		}
		if parsed, err = ParseSource(r.RegistryType, raw); err != nil {
			var ve *ValueError
			if errors.As(err, &ve) {
				return SyncStats{}, &SourceError{Msg: "the source is not a valid index: " + ve.Msg}
			}
			return SyncStats{}, &SourceError{Msg: "the source is not a valid index"}
		}
	}
	if r.Scope == "workspace" && len(parsed) > MaxSourceItems {
		return SyncStats{}, &SourceError{Msg: fmt.Sprintf("the source lists more than %d items", MaxSourceItems)}
	}
	if n := len(parsed); true {
		parsed = Dedupe(parsed)
		if len(parsed) < n {
			s.d.Log.WarnContext(ctx, "Source published duplicate catalog entries; kept the last of each", slog.Int("duplicates", n-len(parsed)))
		}
	}
	var mirror api.ItemMirror
	if mirrors {
		m, err := s.d.Mirror.Open(ctx, r.ID, r.WorkspaceID, token)
		if err != nil {
			return SyncStats{}, err
		}
		mirror = m
	}

	existing, err := s.itemsByExternalID(ctx, ws, r.ID)
	if err != nil {
		return SyncStats{}, err
	}
	st := SyncStats{SkippedItems: []SkippedItem{}}
	for _, e := range parsed {
		res, err := s.syncItem(ctx, ws, r, e, existing[e.ExternalID], mirror)
		if err != nil {
			if ctx.Err() != nil {
				return SyncStats{}, ctx.Err()
			}
			s.d.Log.WarnContext(ctx, "Skipping catalog item", slog.String("external_id", e.ExternalID), slog.String("registry_id", r.ID), slog.Any("error", err))
			st.Skipped++
			if len(st.SkippedItems) < maxSkippedDetails {
				st.SkippedItems = append(st.SkippedItems, SkippedItem{ExternalID: e.ExternalID, Reason: SyncErrorMessage(err)})
			}
			continue
		}
		existing[e.ExternalID] = res.item
		switch res.outcome {
		case outcomeNew:
			st.NewSpecs++
		case outcomeApplied:
			st.Applied++
		case outcomeFlagged:
			st.UpdatesFlagged++
		case outcomeUnchanged:
			st.Unchanged++
		}
	}

	if len(parsed) > 0 {
		published := make([]string, len(parsed))
		for i, e := range parsed {
			published[i] = e.ExternalID
		}
		err := s.d.DB.Write(ctx, ws, func(ctx context.Context, sess db.Session) error {
			out, err := s.d.Sync.MarkInSource(ctx, sess, r.ID, published)
			if err != nil || out == 0 {
				st.OutOfSource = &out
				return err
			}
			if r.RegistryType == domain.TypeSkills {
				var dropped []domain.Item
				for _, it := range existing {
					if !slices.Contains(published, it.ExternalID) {
						dropped = append(dropped, it)
					}
				}
				if err := s.dropPlatformSkills(ctx, sess, dropped); err != nil {
					return err
				}
			}
			siblings, err := s.siblings(ctx, sess, r)
			if err != nil {
				return err
			}
			deleted, err := s.retireDropped(ctx, sess, r, siblings)
			if err != nil {
				return err
			}
			out -= deleted
			st.OutOfSource, st.Deleted = &out, deleted
			return nil
		})
		if err != nil {
			return SyncStats{}, err
		}
	}
	st.Total = len(parsed)
	count := st.NewSpecs + st.UpdatesFlagged + st.Applied + st.Unchanged
	stored := etag
	if st.Skipped > 0 {
		stored = nil
	}
	err = s.d.DB.Write(ctx, ws, func(ctx context.Context, sess db.Session) error {
		return s.d.Sync.RecordSync(ctx, sess, r.ID, count, stored, s.d.Now())
	})
	return st, err
}

func (s *Service) itemsByExternalID(ctx context.Context, ws scope.Workspace, registryID string) (map[string]domain.Item, error) {
	out := map[string]domain.Item{}
	err := s.read(ctx, ws, func(sess db.Session) error {
		all, err := s.d.Registries.AllItems(ctx, sess, registryID)
		for _, it := range all {
			out[it.ExternalID] = it
		}
		return err
	})
	return out, err
}

func (s *Service) siblings(ctx context.Context, sess db.Session, r domain.Registry) ([]string, error) {
	if r.Scope != "platform" {
		return nil, nil
	}
	rs, err := s.d.Sync.ActiveOfType(ctx, sess, r.RegistryType)
	var out []string
	for _, o := range rs {
		if o.Scope == "platform" && o.ID != r.ID {
			out = append(out, o.ID)
		}
	}
	return out, err
}

type outcome int

const (
	outcomeUnchanged outcome = iota
	outcomeNew
	outcomeApplied
	outcomeFlagged
)

type itemResult struct {
	item    domain.Item
	outcome outcome
}

// plainSpec decodes a stored spec as the parser's maps.
func plainSpec(raw []byte) map[string]any {
	v, err := DecodeJSON(raw)
	if err != nil {
		return map[string]any{}
	}
	m, _ := v.(map[string]any)
	if m == nil {
		return map[string]any{}
	}
	return m
}

// canonical round-trips a value through JSON so stored and parsed specs compare alike.
func canonical(v any) any {
	b, err := json.Marshal(v)
	if err != nil {
		return v
	}
	out, err := DecodeJSON(b)
	if err != nil {
		return v
	}
	return out
}

func sameJSON(a, b any) bool { return reflect.DeepEqual(canonical(a), canonical(b)) }

// unpinnedPointer is _unpinned_pointer: repo, path, ref of a GitHub pointer
// with no tree SHA.
func unpinnedPointer(spec map[string]any) (string, bool) {
	src, ok := spec["source"].(map[string]any)
	if !ok || src["type"] != "github" || PyTruthy(src["tree_sha"]) {
		return "", false
	}
	return fmt.Sprint(src["repo"], "\x00", or(src["path"], ""), "\x00", src["ref"]), true
}

// keepReplacedBody is _keep_replaced_body.
func keepReplacedBody(spec, previous map[string]any) {
	if _, ok := spec["source"].(map[string]any); !ok || PyTruthy(spec["content"]) {
		return
	}
	if body, ok := previous["content"].(string); ok && body != "" {
		sum := sha256.Sum256([]byte(body))
		spec["replaced_body_sha256"] = hex.EncodeToString(sum[:])
	} else if d, ok := previous["replaced_body_sha256"].(string); ok {
		spec["replaced_body_sha256"] = d
	}
}

func mirroredSpec(ctx context.Context, mirror api.ItemMirror, spec map[string]any, existing *domain.Item) (map[string]any, error) {
	if existing != nil {
		kept := plainSpec(existing.Spec)
		pkg, has := kept["package"]
		delete(kept, "package")
		if has && PyTruthy(pkg) && sameJSON(kept, spec) {
			return copyWith(spec, "package", pkg), nil
		}
	}
	pkg, err := mirror(ctx, spec)
	if err != nil {
		return nil, err
	}
	return copyWith(spec, "package", pkg), nil
}

func (s *Service) syncedRow(r domain.Registry, e Entry) (store.SyncedItem, error) {
	spec, err := json.Marshal(e.Spec)
	if err != nil {
		return store.SyncedItem{}, err
	}
	tags := e.Tags
	if tags == nil {
		tags = []any{}
	}
	tb, err := json.Marshal(tags)
	if err != nil {
		return store.SyncedItem{}, err
	}
	f, ferr := domain.DeriveFacets(r.RegistryType, e.Name, canonical(e.Spec), canonical(tags))
	if ferr != nil {
		s.d.Log.Warn("Catalog entry declares malformed payers", slog.String("name", e.Name), slog.Any("error", ferr))
	}
	rank := 0
	if e.Rank != nil {
		rank = *e.Rank
	}
	return store.SyncedItem{RegistryID: r.ID, ExternalID: e.ExternalID, Name: e.Name, Description: e.Description,
		Version: e.Version, Spec: spec, Tags: tb, Rank: rank, Facets: f}, nil
}

func versionOr(v *string) string {
	if v == nil || *v == "" {
		return "latest"
	}
	return *v
}

func (s *Service) syncItem(ctx context.Context, ws scope.Workspace, r domain.Registry, e Entry, prior domain.Item, mirror api.ItemMirror) (itemResult, error) {
	var existing *domain.Item
	if prior.ID != "" {
		existing = &prior
	}
	if e.Spec == nil {
		e.Spec = map[string]any{}
	}
	if r.RegistryType == domain.TypeSkills && existing != nil {
		keepReplacedBody(e.Spec, plainSpec(existing.Spec))
	}
	if mirror != nil {
		spec, err := mirroredSpec(ctx, mirror, e.Spec, existing)
		if err != nil {
			return itemResult{}, err
		}
		e.Spec = spec
		if tree, ok := mapping(spec["package"])["tree_sha"].(string); ok && tree != "" && versionOr(e.Version) == unpinnedVersion {
			e.Version = &tree
		}
	}
	row, err := s.syncedRow(r, e)
	if err != nil {
		return itemResult{}, err
	}
	var res itemResult
	err = s.d.DB.Write(ctx, ws, func(ctx context.Context, sess db.Session) error {
		if existing == nil {
			return s.syncNew(ctx, sess, r, e, row, &res)
		}
		return s.syncExisting(ctx, sess, r, e, row, *existing, &res)
	})
	if err != nil {
		return itemResult{}, err
	}
	if res.outcome != outcomeNew && r.RegistryType == domain.TypeLLMModels {
		if err := s.d.DB.Write(ctx, ws, func(ctx context.Context, sess db.Session) error {
			return s.resyncCachePrices(ctx, sess, plainSpec(prior.Spec), e.Spec)
		}); err != nil {
			return itemResult{}, err
		}
	}
	return res, nil
}

func (s *Service) syncNew(ctx context.Context, sess db.Session, r domain.Registry, e Entry, row store.SyncedItem, res *itemResult) error {
	now := s.d.Now()
	it, err := s.d.Sync.InsertItem(ctx, sess, row, now)
	if err != nil {
		return err
	}
	entity, err := s.createEntity(ctx, sess, r, it, e)
	if err != nil {
		return err
	}
	version := versionOr(it.Version)
	if err := s.d.Sync.SetInstalled(ctx, sess, it.ID, entity, &version, now); err != nil {
		return err
	}
	it.InstalledEntityID, it.InstalledVersion = entity, &version
	res.item, res.outcome = it, outcomeNew
	return nil
}

func (s *Service) syncExisting(ctx context.Context, sess db.Session, r domain.Registry, e Entry, row store.SyncedItem, it domain.Item, res *itemResult) error {
	previous := plainSpec(it.Spec)
	newVersion := versionOr(e.Version)
	if p, ok := unpinnedPointer(e.Spec); ok && newVersion == unpinnedVersion {
		if q, ok := unpinnedPointer(previous); ok && p == q && it.Version != nil && *it.Version != "" {
			newVersion = *it.Version
		}
	}
	row.ID, row.Version = it.ID, &newVersion
	changed := !sameJSON(previous, e.Spec) || it.Name != e.Name || !reflect.DeepEqual(it.Description, e.Description)
	applyNow := (r.RegistryType == domain.TypeLLMProviders || r.RegistryType == domain.TypeLLMModels) &&
		it.InstalledEntityID != nil && changed
	row.UpdateAvailable, row.InstalledEntityID, row.InstalledVersion = it.UpdateAvailable, it.InstalledEntityID, it.InstalledVersion
	switch {
	case applyNow:
		res.outcome = outcomeApplied
	case it.InstalledVersion != nil && *it.InstalledVersion != "" && *it.InstalledVersion != newVersion:
		row.UpdateAvailable, res.outcome = true, outcomeFlagged
	default:
		res.outcome = outcomeUnchanged
	}
	if r.RegistryType == domain.TypeSkills && it.InstalledEntityID != nil {
		if err := s.dropPlatformSkills(ctx, sess, []domain.Item{it}); err != nil {
			return err
		}
		row.InstalledEntityID, row.InstalledVersion = nil, nil
	}
	now := s.d.Now()
	if err := s.d.Sync.SetItem(ctx, sess, row, now); err != nil {
		return err
	}
	it.Name, it.Description, it.Version, it.Spec, it.Tags = e.Name, e.Description, &newVersion, row.Spec, row.Tags
	it.UpdateAvailable, it.InstalledEntityID, it.InstalledVersion = row.UpdateAvailable, row.InstalledEntityID, row.InstalledVersion
	if applyNow {
		if _, err := s.materialize(ctx, sess, r, it, e, false); err != nil {
			return err
		}
	}
	if r.RegistryType == domain.TypeMCPServers && it.InstalledEntityID != nil && e.Spec["raw_spec"] != nil && e.Spec["connection_type"] != "openapi" {
		s.backfill(ctx, sess, r, it, e)
	}
	res.item = it
	return nil
}

func (s *Service) dropPlatformSkills(ctx context.Context, sess db.Session, items []domain.Item) error {
	var ids []uuid.UUID
	for _, it := range items {
		if it.InstalledEntityID == nil {
			continue
		}
		if u, err := uuid.Parse(*it.InstalledEntityID); err == nil {
			ids = append(ids, u)
		}
		if err := s.d.Sync.SetInstalled(ctx, sess, it.ID, nil, nil, s.d.Now()); err != nil {
			return err
		}
	}
	if len(ids) == 0 {
		return nil
	}
	return s.d.Uses.DropPlatformSkills(ctx, sess, ids)
}

// createEntity is _create_entity: the id of what the item materialized, or nil.
func (s *Service) createEntity(ctx context.Context, sess db.Session, r domain.Registry, it domain.Item, e Entry) (*string, error) {
	switch r.RegistryType {
	case domain.TypeMCPServers:
		if e.Spec["connection_type"] == "openapi" {
			return nil, nil
		}
		return s.materialize(ctx, sess, r, it, e, true)
	case domain.TypeLLMProviders, domain.TypeLLMModels:
		return s.materialize(ctx, sess, r, it, e, true)
	case domain.TypeSkills, domain.TypeAgents, domain.TypeBundles, domain.TypeSourceTypes:
		return nil, nil
	}
	return nil, valueErr("Unknown registry_type: %s", r.RegistryType)
}

func (s *Service) mirrorRow(r domain.Registry, it domain.Item, e Entry) (store.MirroredServer, error) {
	raw, err := json.Marshal(e.Spec)
	if err != nil {
		return store.MirroredServer{}, err
	}
	m, err := MirrorOf(specObject(raw))
	if err != nil {
		return store.MirroredServer{}, err
	}
	row := store.MirroredServer{RemoteURL: m.RemoteURL, DockerImageURL: m.DockerImageURL, RegistryURL: r.SourceURL, Version: versionOr(it.Version)}
	if it.Description != nil {
		row.Description = *it.Description
	}
	if row.Tags, err = dumps(m.Tags); err != nil {
		return row, err
	}
	if row.EnvSchema, err = dumps(m.EnvSchema); err != nil {
		return row, err
	}
	var cmd any
	if m.Cmd != nil {
		cmd = m.Cmd
	}
	if row.Cmd, err = dumps(cmd); err != nil {
		return row, err
	}
	row.JSONSpec, err = dumps(m.JSONSpec)
	return row, err
}

// materialize is _create_* (create) or _update_* for MCP servers, providers and models.
func (s *Service) materialize(ctx context.Context, sess db.Session, r domain.Registry, it domain.Item, e Entry, create bool) (*string, error) {
	now := s.d.Now()
	switch r.RegistryType {
	case domain.TypeMCPServers:
		row, err := s.mirrorRow(r, it, e)
		if err != nil {
			return nil, err
		}
		if !create {
			id, err := uuid.Parse(*it.InstalledEntityID)
			if err != nil {
				return nil, err
			}
			return it.InstalledEntityID, s.d.Sync.UpdateMirror(ctx, sess, id, row, now)
		}
		base := scope.EntitySlug(it.Name)
		var readErr error
		slug, err := scope.UniqueSlug(base, func(c string) (bool, error) {
			taken, err := s.d.Sync.MirrorSlugTaken(ctx, sess, c)
			readErr = err
			return taken, err
		})
		if err != nil {
			if readErr != nil {
				return nil, readErr
			}
			return nil, valueErr("Exhausted collision suffixes (-2..-999) for slug base '%s'", base)
		}
		itemID, _ := uuid.Parse(it.ID)
		id, err := s.d.Sync.InsertMirror(ctx, sess, itemID, it.Name, slug, row, now)
		if err != nil {
			return nil, err
		}
		out := id.String()
		return &out, nil
	case domain.TypeLLMProviders:
		p, err := providerRow(it, e.Spec)
		if err != nil {
			return nil, err
		}
		id, err := s.d.Sync.UpsertProvider(ctx, sess, p, now)
		if err != nil {
			return nil, err
		}
		out := id.String()
		return &out, nil
	case domain.TypeLLMModels:
		key := sget(e.Spec, "provider_key")
		provider, ok, err := s.d.Sync.ProviderIDByKey(ctx, sess, key)
		if err != nil {
			return nil, err
		}
		if !ok {
			return nil, entryErr("Provider '%s' not found; sync llm_providers registry first", key)
		}
		m, err := modelRow(it, e.Spec, provider)
		if err != nil {
			return nil, err
		}
		id, err := s.d.Sync.UpsertModel(ctx, sess, m, now)
		if err != nil {
			return nil, err
		}
		out := id.String()
		return &out, nil
	}
	return nil, nil
}

func (s *Service) backfill(ctx context.Context, sess db.Session, r domain.Registry, it domain.Item, e Entry) {
	id, err := uuid.Parse(*it.InstalledEntityID)
	if err != nil {
		return
	}
	js, err1 := dumps(canonicalWire(e.Spec["raw_spec"]))
	env, err2 := json.Marshal(DeriveMCPEnvSchema(canonical(e.Spec)))
	if err1 != nil || err2 != nil {
		return
	}
	var remote *string
	if or(e.Spec["connection_type"], "url") == "url" {
		remote = optStr(e.Spec["url"])
	}
	url := r.SourceURL
	if err := s.d.Sync.BackfillMirror(ctx, sess, id, js, env, remote, &url); err != nil {
		s.d.Log.DebugContext(ctx, "Backfill failed", slog.String("entity_id", id.String()), slog.Any("error", err))
	}
}

func canonicalWire(v any) any { return canonical(v) }

func transports() []string          { return []string{"openai", "anthropic"} }
func auths() []string               { return []string{"bearer", "api_key_header", "none"} }
func listShapes() []string          { return []string{"data_id", "models_name"} }
func reasoningParams() []string     { return []string{"reasoning_effort", "reasoning"} }
func pricedPerTokenKinds() []string { return []string{"chat", "embedding"} }

func contractText(spec map[string]any, field string, allowed []string) (*store.Opt[string], error) {
	v, has := spec[field]
	if !has {
		return nil, nil
	}
	if !PyTruthy(v) {
		if allowed != nil {
			return &store.Opt[string]{Value: allowed[0]}, nil
		}
		return &store.Opt[string]{Null: true}, nil
	}
	s, ok := v.(string)
	if !ok || (allowed != nil && !slices.Contains(allowed, s)) {
		return nil, entryErr("%s %v is not one of %s", field, v, strings.Join(allowed, ", "))
	}
	return &store.Opt[string]{Value: s}, nil
}

// providerRow is _create_llm_provider with _provider_contract's checks.
func providerRow(it domain.Item, spec map[string]any) (store.ProviderRow, error) {
	key := sget(spec, "provider_key")
	if key == "" {
		return store.ProviderRow{}, entryErr("provider_key is required")
	}
	p := store.ProviderRow{Key: key, Name: it.Name, Description: it.Description, Type: truthyStr(spec["provider_type"], key),
		Icon: optStr(spec["icon"]), IsBuiltin: PyTruthy(or(spec["is_builtin"], true)), IsFirstParty: PyTruthy(spec["first_party"])}
	var err error
	c := &p.Contract
	for _, f := range []struct {
		name    string
		allowed []string
		dst     **store.Opt[string]
	}{{"base_url", nil, &c.BaseURL}, {"transport", transports(), &c.Transport}, {"auth", auths(), &c.Auth},
		{"models_path", nil, &c.ModelsPath}, {"list_shape", listShapes(), &c.ListShape}, {"models_query", nil, &c.ModelsQuery},
		{"reasoning_param", reasoningParams(), &c.ReasoningParam}} {
		if *f.dst, err = contractText(spec, f.name, f.allowed); err != nil {
			return p, err
		}
	}
	if v, has := spec["reasoning_efforts"]; has {
		if v == nil {
			c.ReasoningEfforts = &store.Opt[[]byte]{Null: true}
		} else {
			levels, ok := v.([]any)
			for _, l := range levels {
				if s, isStr := l.(string); !isStr || s == "" {
					ok = false
				}
			}
			if !ok {
				return p, entryErr("reasoning_efforts must be a list of level names")
			}
			b, _ := json.Marshal(levels)
			c.ReasoningEfforts = &store.Opt[[]byte]{Value: b}
		}
	}
	for _, f := range []struct {
		name string
		dst  **store.Opt[bool]
	}{{"cache_breakpoints", &c.CacheBreakpoints}, {"pdf_input", &c.PDFInput}} {
		v, has := spec[f.name]
		if !has {
			continue
		}
		switch b := v.(type) {
		case nil:
			*f.dst = &store.Opt[bool]{Value: false}
		case bool:
			*f.dst = &store.Opt[bool]{Value: b}
		default:
			return p, entryErr("%s must be true or false", f.name)
		}
	}
	for _, f := range []struct {
		name string
		dst  **store.Opt[int]
	}{{"max_image_bytes", &c.MaxImageBytes}, {"max_image_edge", &c.MaxImageEdge}} {
		v, has := spec[f.name]
		if !has {
			continue
		}
		n, err := optInt(v)
		if err != nil || (n != nil && *n <= 0) {
			return p, entryErr("%s must be a positive integer or null", f.name)
		}
		if n == nil {
			*f.dst = &store.Opt[int]{Null: true}
		} else {
			*f.dst = &store.Opt[int]{Value: *n}
		}
	}
	return p, nil
}

func optMoney(v any) (*money.Decimal, error) {
	if v == nil {
		return nil, nil
	}
	d, err := money.Parse(fmt.Sprint(v))
	if err != nil {
		return nil, entryErr("%v is not a price", v)
	}
	return &d, nil
}

func optInt(v any) (*int, error) {
	if v == nil {
		return nil, nil
	}
	n, ok := v.(json.Number)
	if !ok {
		return nil, entryErr("%v is not an integer", v)
	}
	i64, err := n.Int64()
	if err != nil {
		return nil, entryErr("%v is not an integer", v)
	}
	if i64 < math.MinInt32 || i64 > math.MaxInt32 {
		return nil, entryErr("%v is out of range for a 32-bit integer", v)
	}
	i := int(i64)
	return &i, nil
}

// modelRow is _create_llm_model's checks and values.
func modelRow(it domain.Item, spec map[string]any, provider uuid.UUID) (store.ModelRow, error) {
	name := sget(spec, "model_name")
	kind := truthyStr(spec["kind"], "chat")
	if !slices.Contains(ModelKinds(), kind) {
		return store.ModelRow{}, entryErr("'%s' is not a valid ModelKind", kind)
	}
	cw, cwErr := optInt(spec["context_window"])
	if slices.Contains(pricedPerTokenKinds(), kind) {
		if cwErr != nil || cw == nil || *cw <= 0 {
			return store.ModelRow{}, entryErr("Model '%s' has no explicit positive context_window", name)
		}
		for _, f := range []string{"input_cost_per_token", "output_cost_per_token"} {
			if spec[f] == nil {
				return store.ModelRow{}, entryErr("Model '%s' has no explicit %s", name, f)
			}
		}
	} else if cwErr != nil {
		return store.ModelRow{}, cwErr
	}
	m := store.ModelRow{Provider: provider, Name: name, DisplayName: it.Name, Kind: kind, Description: it.Description,
		ContextWindow: cw, FunctionCalling: PyTruthy(spec["supports_function_calling"]), Vision: PyTruthy(spec["supports_vision"]),
		Reasoning: PyTruthy(spec["supports_reasoning"]), Active: PyTruthy(or(spec["is_active"], true))}
	var err error
	if m.MaxOutputTokens, err = optInt(spec["max_output_tokens"]); err != nil {
		return m, err
	}
	for _, f := range []struct {
		key string
		dst **money.Decimal
	}{{"input_cost_per_token", &m.InputCost}, {"output_cost_per_token", &m.OutputCost},
		{"cached_input_cost_per_token", &m.CachedCost}, {"cache_creation_input_cost_per_token", &m.CacheCreationCost}} {
		if *f.dst, err = optMoney(spec[f.key]); err != nil {
			return m, err
		}
	}
	if v := spec["reasoning_efforts"]; v != nil {
		m.ReasoningEfforts, _ = json.Marshal(v)
	}
	return m, nil
}

// resyncCachePrices is _resync_model_cache_prices.
func (s *Service) resyncCachePrices(ctx context.Context, sess db.Session, previous, current map[string]any) error {
	provider, ok, err := s.d.Sync.ProviderIDByKey(ctx, sess, sget(current, "provider_key"))
	if err != nil || !ok || sget(current, "model_name") == "" {
		return err
	}
	vals := make([]*money.Decimal, 4)
	for i, v := range []any{previous["cached_input_cost_per_token"], current["cached_input_cost_per_token"],
		previous["cache_creation_input_cost_per_token"], current["cache_creation_input_cost_per_token"]} {
		if vals[i], err = optMoney(v); err != nil {
			return err
		}
	}
	n, err := s.d.Sync.ResyncCachePrices(ctx, sess, provider, sget(current, "model_name"), vals[0], vals[1], vals[2], vals[3])
	if n > 0 {
		s.d.Log.InfoContext(ctx, "Catalog cache prices reached workspace copies", slog.String("model", sget(current, "model_name")), slog.Int("changed", n))
	}
	return err
}

// retireDropped is _move_uses, _delete_unused_llm_entities and
// delete_unreferenced_out_of_source, in the caller's transaction.
func (s *Service) retireDropped(ctx context.Context, sess db.Session, r domain.Registry, replacements []string) (int, error) {
	moves, err := s.d.Sync.Moves(ctx, sess, r.ID, replacements)
	if err != nil {
		return 0, err
	}
	if len(moves) > 0 {
		own, err := s.d.Sync.MoveOwn(ctx, sess, moves)
		if err != nil {
			return 0, err
		}
		foreign, err := s.d.Uses.MoveItemUses(ctx, sess, moves)
		if err != nil {
			return 0, err
		}
		if own+foreign > 0 {
			s.d.Log.InfoContext(ctx, "Moved uses of items the registry dropped", slog.String("registry_id", r.ID), slog.Int("moved", own+foreign))
		}
	}
	if r.RegistryType == domain.TypeMCPServers {
		copies, err := s.d.Sync.ReplacedCopies(ctx, sess, r.ID, replacements)
		if err != nil {
			return 0, err
		}
		for _, c := range copies {
			if err := s.d.Sync.DeletePlatformServer(ctx, sess, c.Copy); err != nil {
				return 0, err
			}
			if err := s.d.Sync.SetInstalled(ctx, sess, c.Item.String(), nil, nil, s.d.Now()); err != nil {
				return 0, err
			}
		}
	}
	deleted, err := s.deleteUnusedLLM(ctx, sess, r)
	if err != nil {
		return 0, err
	}
	unheld, err := s.d.Sync.UnheldOutOfSource(ctx, sess, r.ID)
	if err != nil {
		return 0, err
	}
	var free []uuid.UUID
	if len(unheld) > 0 {
		refs, err := s.d.Uses.ReferencedItems(ctx, sess, unheld)
		if err != nil {
			return 0, err
		}
		for _, id := range unheld {
			if !refs[id] {
				free = append(free, id)
			}
		}
	}
	n, err := s.d.Sync.DeleteItems(ctx, sess, r.ID, free)
	return deleted + n, err
}

func (s *Service) deleteUnusedLLM(ctx context.Context, sess db.Session, r domain.Registry) (int, error) {
	switch r.RegistryType {
	case domain.TypeLLMProviders:
		candidates, err := s.d.Sync.DroppedProviders(ctx, sess, r.ID)
		if err != nil || len(candidates) == 0 {
			return 0, err
		}
		models, err := s.d.Sync.ProviderModels(ctx, sess, candidates)
		if err != nil {
			return 0, err
		}
		used, err := s.d.Uses.UsedProviderSpecs(ctx, sess, candidates)
		if err != nil {
			return 0, err
		}
		ids := make([]uuid.UUID, len(models))
		for i, m := range models {
			ids[i] = m.ID
		}
		run := map[uuid.UUID]bool{}
		if len(ids) > 0 {
			if run, err = s.d.Uses.UsedModelSpecs(ctx, sess, ids); err != nil {
				return 0, err
			}
		}
		for _, m := range models {
			if m.Copy || run[m.ID] {
				used[m.Provider] = true
			}
		}
		var unused []uuid.UUID
		for _, c := range candidates {
			if !used[c] {
				unused = append(unused, c)
			}
		}
		return s.d.Sync.DeleteProviders(ctx, sess, r.ID, unused)
	case domain.TypeLLMModels:
		candidates, err := s.d.Sync.DroppedModels(ctx, sess, r.ID)
		if err != nil || len(candidates) == 0 {
			return 0, err
		}
		run, err := s.d.Uses.UsedModelSpecs(ctx, sess, candidates)
		if err != nil {
			return 0, err
		}
		var unused []uuid.UUID
		for _, c := range candidates {
			if !run[c] {
				unused = append(unused, c)
			}
		}
		return s.d.Sync.DeleteModels(ctx, sess, r.ID, unused)
	}
	return 0, nil
}

// checkPointers is _check_pointers_within_budget.
func (s *Service) checkPointers(ctx context.Context, r domain.Registry) int {
	if r.RegistryType != domain.TypeSkills || r.Mode != "upstream" {
		return 0
	}
	ctx, cancel := context.WithTimeout(ctx, pointerCheckTimeout)
	defer cancel()
	ws := registryWorkspace(r)
	var installed []domain.Item
	if err := s.read(ctx, ws, func(sess db.Session) (err error) {
		installed, err = s.d.Sync.InstalledItems(ctx, sess, r.ID)
		return err
	}); err != nil {
		s.d.Log.ErrorContext(ctx, "Pointer checks failed", slog.String("registry_id", r.ID), slog.Any("error", err))
		return 0
	}
	trees := s.d.Fetch.NewPointerTrees()
	checked := 0
	for _, it := range installed {
		spec := plainSpec(it.Spec)
		if _, ok := unpinnedPointer(spec); !ok {
			continue
		}
		if checked >= maxPointerChecks || ctx.Err() != nil {
			break
		}
		checked++
		current, err := trees.Tree(ctx, mapping(spec["source"]))
		var ge *GitHubError
		if errors.As(err, &ge) && ge.RateLimit {
			s.d.Log.WarnContext(ctx, "GitHub throttled the check of a catalog skill; the rest wait for the next sync", slog.String("item_id", it.ID))
			break
		}
		if err != nil {
			s.d.Log.WarnContext(ctx, "Could not check the current tree of a catalog skill", slog.String("item_id", it.ID), slog.Any("error", err))
			continue
		}
		if it.Version != nil && *it.Version == current {
			continue
		}
		if err := s.d.DB.Write(ctx, ws, func(ctx context.Context, sess db.Session) error {
			return s.d.Sync.SetVersion(ctx, sess, it.ID, current, s.d.Now())
		}); err != nil {
			s.d.Log.WarnContext(ctx, "Could not record a catalog skill's tree", slog.String("item_id", it.ID), slog.Any("error", err))
		}
	}
	return checked
}

// RetireRegistry is retire_registry: deactivate, everything out of source,
// uses moved onto replacements, what nothing uses deleted.
func (s *Service) RetireRegistry(ctx context.Context, id string, replacements []string) (int, error) {
	if !s.HasSync() {
		return 0, ErrNoSync
	}
	var deleted int
	err := s.d.DB.Write(ctx, platformWorkspace(), func(ctx context.Context, sess db.Session) error {
		r, ok, err := s.d.Registries.Get(ctx, sess, id)
		if err != nil {
			return err
		}
		if !ok {
			return &NotFoundError{Detail: "Registry " + id + " not found"}
		}
		if r.IsActive {
			off := false
			if _, _, err := s.d.Registries.Update(ctx, sess, id, domain.RegistryPatch{IsActive: domain.Field[*bool]{Set: true, Value: &off}}, false, s.d.Now()); err != nil {
				return err
			}
		}
		if _, err := s.d.Sync.MarkInSource(ctx, sess, id, nil); err != nil {
			return err
		}
		if r.RegistryType == domain.TypeSkills {
			all, err := s.d.Registries.AllItems(ctx, sess, id)
			if err != nil {
				return err
			}
			if err := s.dropPlatformSkills(ctx, sess, all); err != nil {
				return err
			}
		}
		deleted, err = s.retireDropped(ctx, sess, r, replacements)
		return err
	})
	return deleted, err
}

// RemoveWorkspaceRegistry is delete_workspace_registry: retire, then delete
// the row when no item stayed. Status "deleted" or "retired" and the items kept.
func (s *Service) RemoveWorkspaceRegistry(ctx context.Context, c authn.Caller, id string) (string, int, error) {
	sec, err := s.secrets(c)
	if err != nil {
		return "", 0, err
	}
	ws := c.Workspace
	if _, err := s.RetireRegistry(ctx, id, nil); err != nil {
		return "", 0, err
	}
	var kept int
	if err := s.read(ctx, ws, func(sess db.Session) (err error) {
		kept, err = s.d.Sync.CountItems(ctx, sess, id)
		return err
	}); err != nil {
		return "", 0, err
	}
	if kept > 0 {
		return "retired", kept, nil
	}
	if err := sec.ClearReferences(ctx, RegistrySecretConsumer, id); err != nil {
		return "", 0, err
	}
	if _, err := s.DeleteRegistry(ctx, ws, id); err != nil {
		return "", 0, err
	}
	return "deleted", 0, nil
}
