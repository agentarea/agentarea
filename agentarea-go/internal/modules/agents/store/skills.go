package store

import (
	"context"
	"encoding/json"
	"errors"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgtype"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/agents/domain"
)

// Skills reads and writes skills, their versions and bundle members inside the session's workspace.
type Skills struct{}

// SkillFilter is list_paginated's filters; IDs narrows to what the caller may read.
type SkillFilter struct {
	IDs          []uuid.UUID
	Search       *string
	SourceType   *string
	NetworkScope *string
	FromRegistry *bool
	Offset       int
	Limit        int
}

// SkillNew is a row to insert.
type SkillNew struct {
	ID          uuid.UUID
	Name        string
	Slug        string
	Description *string
	SourceType  string
	SourceURL   *string
	CreatedBy   string
}

// SkillRef is a skill's id and workspace, for the jobs that span workspaces.
type SkillRef struct {
	ID          uuid.UUID
	WorkspaceID string
}

func skillTime(t pgtype.Timestamp) time.Time { return t.Time }

func skillRow(id uuid.UUID, name, slug string, description pgtype.Text, sourceType string, sourceURL pgtype.Text,
	scope, ws, createdBy string, created, updated pgtype.Timestamp, item uuid.NullUUID, s3 pgtype.Text) domain.Skill {
	return domain.Skill{
		ID: id.String(), Name: name, Slug: slug, Description: fromText(description), SourceType: sourceType,
		SourceURL: fromText(sourceURL), NetworkScope: scope, WorkspaceID: ws, CreatedBy: createdBy,
		CreatedAt: skillTime(created), UpdatedAt: skillTime(updated), RegistryItemID: fromNullUUID(item), S3Path: fromText(s3),
	}
}

// Get is the skill with its row body, false when the workspace has none.
func (Skills) Get(ctx context.Context, s db.Session, id uuid.UUID) (domain.Skill, bool, error) {
	r, err := New(s.Q()).SkillGet(ctx, SkillGetParams{WorkspaceID: s.Workspace().ID(), ID: id})
	if errors.Is(err, pgx.ErrNoRows) {
		return domain.Skill{}, false, nil
	}
	if err != nil {
		return domain.Skill{}, false, err
	}
	sk := skillRow(r.ID, r.Name, r.Slug, r.Description, r.SourceType, r.SourceUrl, r.NetworkScope, r.WorkspaceID, r.CreatedBy,
		r.CreatedAt, r.UpdatedAt, r.RegistryItemID, r.S3Path)
	sk.Content = fromText(r.Content)
	return sk, true, nil
}

// Lock is Get under FOR UPDATE.
func (Skills) Lock(ctx context.Context, s db.Session, id uuid.UUID) (domain.Skill, bool, error) {
	r, err := New(s.Q()).SkillGetForUpdate(ctx, SkillGetForUpdateParams{WorkspaceID: s.Workspace().ID(), ID: id})
	if errors.Is(err, pgx.ErrNoRows) {
		return domain.Skill{}, false, nil
	}
	if err != nil {
		return domain.Skill{}, false, err
	}
	sk := skillRow(r.ID, r.Name, r.Slug, r.Description, r.SourceType, r.SourceUrl, r.NetworkScope, r.WorkspaceID, r.CreatedBy,
		r.CreatedAt, r.UpdatedAt, r.RegistryItemID, r.S3Path)
	sk.Content = fromText(r.Content)
	return sk, true, nil
}

// SlugTaken reports whether the workspace has a skill with this slug.
func (Skills) SlugTaken(ctx context.Context, s db.Session, slug string) (bool, error) {
	return New(s.Q()).SkillSlugTaken(ctx, SkillSlugTakenParams{WorkspaceID: s.Workspace().ID(), Slug: slug})
}

// Insert writes a new row with no package yet.
func (Skills) Insert(ctx context.Context, s db.Session, n SkillNew, now time.Time) error {
	return New(s.Q()).SkillInsert(ctx, SkillInsertParams{ID: n.ID, Name: n.Name, Slug: n.Slug, Description: text(n.Description),
		SourceType: n.SourceType, SourceUrl: text(n.SourceURL), WorkspaceID: s.Workspace().ID(), CreatedBy: n.CreatedBy, Now: naive(now)})
}

// UpdateMeta sets the non-nil fields.
func (Skills) UpdateMeta(ctx context.Context, s db.Session, id uuid.UUID, name, description, sourceURL *string, now time.Time) error {
	return New(s.Q()).SkillUpdateMeta(ctx, SkillUpdateMetaParams{Name: text(name), Description: text(description), SourceUrl: text(sourceURL),
		Now: naive(now), WorkspaceID: s.Workspace().ID(), ID: id})
}

// SetPackage points the skill at s3Path and clears its row body.
func (Skills) SetPackage(ctx context.Context, s db.Session, id uuid.UUID, s3Path string, now time.Time) error {
	return New(s.Q()).SkillSetPackage(ctx, SkillSetPackageParams{S3Path: pgtype.Text{String: s3Path, Valid: true}, Now: naive(now),
		WorkspaceID: s.Workspace().ID(), ID: id})
}

// SwapPackage is the compare-and-set move: false when the skill no longer points at expect.
func (Skills) SwapPackage(ctx context.Context, s db.Session, id uuid.UUID, s3Path string, expect *string, now time.Time) (bool, error) {
	_, err := New(s.Q()).SkillSwapPackage(ctx, SkillSwapPackageParams{S3Path: pgtype.Text{String: s3Path, Valid: true}, Now: naive(now),
		WorkspaceID: s.Workspace().ID(), ID: id, Expect: text(expect)})
	if errors.Is(err, pgx.ErrNoRows) {
		return false, nil
	}
	return err == nil, err
}

// ClearContent drops the row body.
func (Skills) ClearContent(ctx context.Context, s db.Session, id uuid.UUID, now time.Time) error {
	return New(s.Q()).SkillClearContent(ctx, SkillClearContentParams{Now: naive(now), WorkspaceID: s.Workspace().ID(), ID: id})
}

// Delete removes the row; false when there was none.
func (Skills) Delete(ctx context.Context, s db.Session, id uuid.UUID) (bool, error) {
	n, err := New(s.Q()).SkillDelete(ctx, SkillDeleteParams{WorkspaceID: s.Workspace().ID(), ID: id})
	return n > 0, err
}

func skillSearch(f SkillFilter) pgtype.Text {
	if f.Search == nil || *f.Search == "" {
		return pgtype.Text{}
	}
	return pgtype.Text{String: "%" + domain.SkillPyStrip(*f.Search) + "%", Valid: true}
}

func skillNonEmpty(p *string) pgtype.Text {
	if p == nil || *p == "" {
		return pgtype.Text{}
	}
	return pgtype.Text{String: *p, Valid: true}
}

func skillBool(p *bool) pgtype.Bool {
	if p == nil {
		return pgtype.Bool{}
	}
	return pgtype.Bool{Bool: *p, Valid: true}
}

// Page is one page of the filtered skills, newest first, and the filtered total.
func (Skills) Page(ctx context.Context, s db.Session, f SkillFilter) ([]domain.Skill, int, error) {
	q := New(s.Q())
	ids := f.IDs
	if ids == nil {
		ids = []uuid.UUID{}
	}
	total, err := q.SkillCount(ctx, SkillCountParams{WorkspaceID: s.Workspace().ID(), Ids: ids, Search: skillSearch(f),
		SourceType: skillNonEmpty(f.SourceType), NetworkScope: skillNonEmpty(f.NetworkScope), FromRegistry: skillBool(f.FromRegistry)})
	if err != nil {
		return nil, 0, err
	}
	rows, err := q.SkillListPage(ctx, SkillListPageParams{WorkspaceID: s.Workspace().ID(), Ids: ids, Search: skillSearch(f),
		SourceType: skillNonEmpty(f.SourceType), NetworkScope: skillNonEmpty(f.NetworkScope), FromRegistry: skillBool(f.FromRegistry),
		RowOffset: int32(f.Offset), RowLimit: int32(f.Limit)}) //nolint:gosec // paging is bounded by httpx.MaxPage*MaxPageSize
	if err != nil {
		return nil, 0, err
	}
	out := make([]domain.Skill, len(rows))
	for i, r := range rows {
		out[i] = skillRow(r.ID, r.Name, r.Slug, r.Description, r.SourceType, r.SourceUrl, r.NetworkScope, r.WorkspaceID, r.CreatedBy,
			r.CreatedAt, r.UpdatedAt, r.RegistryItemID, r.S3Path)
	}
	return out, int(total), nil
}

// All is every skill of the workspace, without row bodies.
func (Skills) All(ctx context.Context, s db.Session) ([]domain.Skill, error) {
	rows, err := New(s.Q()).SkillListAll(ctx, s.Workspace().ID())
	if err != nil {
		return nil, err
	}
	out := make([]domain.Skill, len(rows))
	for i, r := range rows {
		out[i] = skillRow(r.ID, r.Name, r.Slug, r.Description, r.SourceType, r.SourceUrl, r.NetworkScope, r.WorkspaceID, r.CreatedBy,
			r.CreatedAt, r.UpdatedAt, r.RegistryItemID, r.S3Path)
	}
	return out, nil
}

func skillVersion(id, skill uuid.UUID, s3 string, digest pgtype.Text, reason string, cat pgtype.Text, by string, at pgtype.Timestamp) domain.SkillVersion {
	return domain.SkillVersion{ID: id.String(), SkillID: skill.String(), S3Path: s3, Digest: fromText(digest), Reason: reason,
		CatalogVersion: fromText(cat), CreatedBy: by, CreatedAt: skillTime(at)}
}

// LatestVersion is the skill's newest version, false when it has none.
func (Skills) LatestVersion(ctx context.Context, s db.Session, skill uuid.UUID) (domain.SkillVersion, bool, error) {
	r, err := New(s.Q()).SkillLatestVersion(ctx, SkillLatestVersionParams{WorkspaceID: s.Workspace().ID(), SkillID: skill})
	if errors.Is(err, pgx.ErrNoRows) {
		return domain.SkillVersion{}, false, nil
	}
	if err != nil {
		return domain.SkillVersion{}, false, err
	}
	return skillVersion(r.ID, r.SkillID, r.S3Path, r.Digest, r.Reason, r.CatalogVersion, r.CreatedBy, r.CreatedAt), true, nil
}

// Versions is the skill's versions, oldest first.
func (Skills) Versions(ctx context.Context, s db.Session, skill uuid.UUID) ([]domain.SkillVersion, error) {
	rows, err := New(s.Q()).SkillVersions(ctx, SkillVersionsParams{WorkspaceID: s.Workspace().ID(), SkillID: skill})
	if err != nil {
		return nil, err
	}
	out := make([]domain.SkillVersion, len(rows))
	for i, r := range rows {
		out[i] = skillVersion(r.ID, r.SkillID, r.S3Path, r.Digest, r.Reason, r.CatalogVersion, r.CreatedBy, r.CreatedAt)
	}
	return out, nil
}

// Version is one version of the skill, false when it has no such version.
func (Skills) Version(ctx context.Context, s db.Session, skill, id uuid.UUID) (domain.SkillVersion, bool, error) {
	r, err := New(s.Q()).SkillVersionGet(ctx, SkillVersionGetParams{WorkspaceID: s.Workspace().ID(), SkillID: skill, ID: id})
	if errors.Is(err, pgx.ErrNoRows) {
		return domain.SkillVersion{}, false, nil
	}
	if err != nil {
		return domain.SkillVersion{}, false, err
	}
	return skillVersion(r.ID, r.SkillID, r.S3Path, r.Digest, r.Reason, r.CatalogVersion, r.CreatedBy, r.CreatedAt), true, nil
}

// AddVersion records a version row.
func (Skills) AddVersion(ctx context.Context, s db.Session, v domain.SkillVersion, now time.Time) error {
	id, err := uuid.Parse(v.ID)
	if err != nil {
		return err
	}
	skill, err := uuid.Parse(v.SkillID)
	if err != nil {
		return err
	}
	return New(s.Q()).SkillVersionInsert(ctx, SkillVersionInsertParams{ID: id, SkillID: skill, S3Path: v.S3Path, Digest: text(v.Digest),
		Reason: v.Reason, CatalogVersion: text(v.CatalogVersion), WorkspaceID: s.Workspace().ID(), CreatedBy: v.CreatedBy, Now: naive(now)})
}

// Members is the parent's children inside the workspace, by order.
func (Skills) Members(ctx context.Context, s db.Session, parent uuid.UUID) ([]domain.SkillMember, error) {
	rows, err := New(s.Q()).SkillMembers(ctx, SkillMembersParams{ParentSkillID: parent, WorkspaceID: s.Workspace().ID()})
	if err != nil {
		return nil, err
	}
	out := make([]domain.SkillMember, len(rows))
	for i, r := range rows {
		deps := []string{}
		if len(r.Dependencies) > 0 {
			var raw []any
			if err := json.Unmarshal(r.Dependencies, &raw); err == nil {
				for _, d := range raw {
					if str, ok := d.(string); ok {
						deps = append(deps, str)
					}
				}
			}
		}
		out[i] = domain.SkillMember{ParentSkillID: r.ParentSkillID.String(), ChildSkillID: r.ChildSkillID.String(), Order: r.Order,
			IsRequired: r.IsRequired, Dependencies: deps}
	}
	return out, nil
}

// PutMember inserts the edge or updates the one there.
func (Skills) PutMember(ctx context.Context, s db.Session, m domain.SkillMember) error {
	parent, err := uuid.Parse(m.ParentSkillID)
	if err != nil {
		return err
	}
	child, err := uuid.Parse(m.ChildSkillID)
	if err != nil {
		return err
	}
	deps := m.Dependencies
	if deps == nil {
		deps = []string{}
	}
	raw, err := json.Marshal(deps)
	if err != nil {
		return err
	}
	q := New(s.Q())
	exists, err := q.SkillMemberExists(ctx, SkillMemberExistsParams{ParentSkillID: parent, ChildSkillID: child})
	if err != nil {
		return err
	}
	if exists {
		return q.SkillMemberUpdate(ctx, SkillMemberUpdateParams{MemberOrder: m.Order, IsRequired: m.IsRequired, Dependencies: raw,
			ParentSkillID: parent, ChildSkillID: child})
	}
	return q.SkillMemberInsert(ctx, SkillMemberInsertParams{ParentSkillID: parent, ChildSkillID: child, MemberOrder: m.Order,
		IsRequired: m.IsRequired, Dependencies: raw})
}

// RemoveMember deletes the edge; false when there was none.
func (Skills) RemoveMember(ctx context.Context, s db.Session, parent, child uuid.UUID) (bool, error) {
	n, err := New(s.Q()).SkillMemberDelete(ctx, SkillMemberDeleteParams{ParentSkillID: parent, ChildSkillID: child})
	return n > 0, err
}

// WithBodies is every skill outside the platform workspace that still holds its body in its row.
func (Skills) WithBodies(ctx context.Context, q db.Querier, platformWorkspace string) ([]SkillRef, error) {
	rows, err := New(q).SkillsWithBodies(ctx, platformWorkspace)
	if err != nil {
		return nil, err
	}
	out := make([]SkillRef, len(rows))
	for i, r := range rows {
		out[i] = SkillRef(r)
	}
	return out, nil
}

// AtOwnCopies is every skill still pointing at its pre-package copy.
func (Skills) AtOwnCopies(ctx context.Context, q db.Querier) ([]SkillRef, error) {
	rows, err := New(q).SkillsAtOwnCopies(ctx)
	if err != nil {
		return nil, err
	}
	out := make([]SkillRef, len(rows))
	for i, r := range rows {
		out[i] = SkillRef(r)
	}
	return out, nil
}

// MovedOwnCopies is the pre-package prefix of every skill moved off it before movedBefore.
func (Skills) MovedOwnCopies(ctx context.Context, q db.Querier, movedBefore time.Time) ([]string, error) {
	return New(q).SkillMovedOwnCopies(ctx, naive(movedBefore))
}

// SkillFork is a workspace skill forked from a catalog item.
type SkillFork struct {
	SkillNew
	S3Path         string
	NetworkScope   string
	RegistryItemID uuid.UUID
}

// InsertFork is SkillRepository.create of _fork_catalog_skill.
func (Skills) InsertFork(ctx context.Context, s db.Session, n SkillFork, now time.Time) error {
	return New(s.Q()).SkillInsertFromCatalog(ctx, SkillInsertFromCatalogParams{ID: n.ID, Name: n.Name, Slug: n.Slug,
		Description: text(n.Description), SourceType: n.SourceType, SourceUrl: text(n.SourceURL), S3Path: text(&n.S3Path),
		NetworkScope: n.NetworkScope, RegistryItemID: uuid.NullUUID{UUID: n.RegistryItemID, Valid: true},
		WorkspaceID: s.Workspace().ID(), CreatedBy: n.CreatedBy, Now: naive(now)})
}

// ByRegistryItem is get_by_registry_item_id.
func (Skills) ByRegistryItem(ctx context.Context, s db.Session, item uuid.UUID) (domain.Skill, bool, error) {
	r, err := New(s.Q()).SkillGetByRegistryItem(ctx, SkillGetByRegistryItemParams{WorkspaceID: s.Workspace().ID(),
		RegistryItemID: uuid.NullUUID{UUID: item, Valid: true}})
	if errors.Is(err, pgx.ErrNoRows) {
		return domain.Skill{}, false, nil
	}
	if err != nil {
		return domain.Skill{}, false, err
	}
	return skillRow(r.ID, r.Name, r.Slug, r.Description, r.SourceType, r.SourceUrl, r.NetworkScope, r.WorkspaceID, r.CreatedBy,
		r.CreatedAt, r.UpdatedAt, r.RegistryItemID, r.S3Path), true, nil
}

// FromCatalog is list_from_catalog: the workspace's skills installed from a catalog item, with their row bodies.
func (Skills) FromCatalog(ctx context.Context, s db.Session) ([]domain.Skill, error) {
	rows, err := New(s.Q()).SkillsFromCatalog(ctx, s.Workspace().ID())
	if err != nil {
		return nil, err
	}
	out := make([]domain.Skill, len(rows))
	for i, r := range rows {
		out[i] = skillRow(r.ID, r.Name, r.Slug, r.Description, r.SourceType, r.SourceUrl, r.NetworkScope, r.WorkspaceID, r.CreatedBy,
			r.CreatedAt, r.UpdatedAt, r.RegistryItemID, r.S3Path)
		out[i].Content = fromText(r.Content)
	}
	return out, nil
}

// SkillSource is where a skill came from; a nil Description keeps the one it has.
type SkillSource struct {
	SourceURL      *string
	SourceType     string
	RegistryItemID uuid.NullUUID
	Description    *string
}

// SetSource writes the skill's source columns.
func (Skills) SetSource(ctx context.Context, s db.Session, id uuid.UUID, src SkillSource, now time.Time) error {
	return New(s.Q()).SkillSetSource(ctx, SkillSetSourceParams{SourceUrl: text(src.SourceURL), SourceType: src.SourceType,
		RegistryItemID: src.RegistryItemID, Description: text(src.Description), Now: naive(now), WorkspaceID: s.Workspace().ID(), ID: id})
}

// CatalogInstalls is list_catalog_installs: every skill outside the platform workspace installed from a catalog item.
func (Skills) CatalogInstalls(ctx context.Context, q db.Querier, platformWorkspace string) ([]SkillRef, error) {
	rows, err := New(q).SkillsInstalledFromCatalog(ctx, platformWorkspace)
	if err != nil {
		return nil, err
	}
	out := make([]SkillRef, len(rows))
	for i, r := range rows {
		out[i] = SkillRef(r)
	}
	return out, nil
}

// OutsidePlatform is list_workspace_skills: every skill outside the platform workspace.
func (Skills) OutsidePlatform(ctx context.Context, q db.Querier, platformWorkspace string) ([]SkillRef, error) {
	rows, err := New(q).SkillsOutsidePlatform(ctx, platformWorkspace)
	if err != nil {
		return nil, err
	}
	out := make([]SkillRef, len(rows))
	for i, r := range rows {
		out[i] = SkillRef(r)
	}
	return out, nil
}
