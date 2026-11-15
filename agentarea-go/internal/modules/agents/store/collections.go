package store

import (
	"context"
	"errors"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
)

// Collection is a skill collection row.
type Collection struct {
	ID          string
	Name        string
	Slug        string
	Description *string
}

// CollectionSkill is a skill of a collection.
type CollectionSkill struct{ ID, Name string }

// Collections reads and writes skill collections inside the session's workspace.
type Collections struct{}

// Insert writes a new collection.
func (Collections) Insert(ctx context.Context, s db.Session, id uuid.UUID, createdBy, name, slug string, description *string, now time.Time) error {
	return New(s.Q()).InsertCollection(ctx, InsertCollectionParams{ID: id, Now: naive(now), WorkspaceID: s.Workspace().ID(),
		CreatedBy: createdBy, Name: name, Slug: slug, Description: text(description)})
}

// Get is the collection, false when the workspace has none.
func (Collections) Get(ctx context.Context, s db.Session, id uuid.UUID) (Collection, bool, error) {
	r, err := New(s.Q()).GetCollection(ctx, GetCollectionParams{WorkspaceID: s.Workspace().ID(), ID: id})
	if errors.Is(err, pgx.ErrNoRows) {
		return Collection{}, false, nil
	}
	if err != nil {
		return Collection{}, false, err
	}
	return Collection{ID: r.ID.String(), Name: r.Name, Slug: r.Slug, Description: fromText(r.Description)}, true, nil
}

// SlugTaken reports whether the workspace has a collection with this slug.
func (Collections) SlugTaken(ctx context.Context, s db.Session, slug string) (bool, error) {
	return New(s.Q()).CollectionSlugTaken(ctx, CollectionSlugTakenParams{WorkspaceID: s.Workspace().ID(), Slug: slug})
}

// List is the workspace's collections, newest first.
func (Collections) List(ctx context.Context, s db.Session) ([]Collection, error) {
	rows, err := New(s.Q()).ListCollections(ctx, s.Workspace().ID())
	if err != nil {
		return nil, err
	}
	out := make([]Collection, len(rows))
	for i, r := range rows {
		out[i] = Collection{ID: r.ID.String(), Name: r.Name, Slug: r.Slug, Description: fromText(r.Description)}
	}
	return out, nil
}

// Counts are the skill counts of the collections that have skills.
func (Collections) Counts(ctx context.Context, s db.Session) (map[string]int64, error) {
	rows, err := New(s.Q()).CollectionSkillCounts(ctx, s.Workspace().ID())
	if err != nil {
		return nil, err
	}
	out := map[string]int64{}
	for _, r := range rows {
		out[r.CollectionID.String()] = r.N
	}
	return out, nil
}

// Count is one collection's skill count.
func (Collections) Count(ctx context.Context, s db.Session, id uuid.UUID) (int64, error) {
	return New(s.Q()).CollectionSkillCount(ctx, id)
}

// Skills are the collection's skills of this workspace.
func (Collections) Skills(ctx context.Context, s db.Session, id uuid.UUID) ([]CollectionSkill, error) {
	rows, err := New(s.Q()).CollectionSkills(ctx, CollectionSkillsParams{CollectionID: id, WorkspaceID: s.Workspace().ID()})
	if err != nil {
		return nil, err
	}
	out := make([]CollectionSkill, len(rows))
	for i, r := range rows {
		out[i] = CollectionSkill{ID: r.ID.String(), Name: r.Name}
	}
	return out, nil
}

// Update writes the fields sent.
func (Collections) Update(ctx context.Context, s db.Session, id uuid.UUID, name *string, setDescription bool, description *string, now time.Time) error {
	arg := UpdateCollectionParams{SetDescription: setDescription, Description: text(description), SetName: name != nil,
		Now: naive(now), WorkspaceID: s.Workspace().ID(), ID: id}
	if name != nil {
		arg.Name = *name
	}
	return New(s.Q()).UpdateCollection(ctx, arg)
}

// Delete removes the collection; the link rows go with it.
func (Collections) Delete(ctx context.Context, s db.Session, id uuid.UUID) (bool, error) {
	n, err := New(s.Q()).DeleteCollection(ctx, DeleteCollectionParams{WorkspaceID: s.Workspace().ID(), ID: id})
	return n > 0, err
}

// AddSkill is an idempotent insert.
func (Collections) AddSkill(ctx context.Context, s db.Session, collection, skill uuid.UUID, now time.Time) error {
	q := New(s.Q())
	has, err := q.CollectionHasSkill(ctx, CollectionHasSkillParams{CollectionID: collection, SkillID: skill})
	if err != nil || has {
		return err
	}
	return q.InsertCollectionSkill(ctx, InsertCollectionSkillParams{CollectionID: collection, SkillID: skill, Now: naive(now)})
}

// RemoveSkill deletes the link; a missing one is a no-op.
func (Collections) RemoveSkill(ctx context.Context, s db.Session, collection, skill uuid.UUID) error {
	return New(s.Q()).DeleteCollectionSkill(ctx, DeleteCollectionSkillParams{CollectionID: collection, SkillID: skill})
}
