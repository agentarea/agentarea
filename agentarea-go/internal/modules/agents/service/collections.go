package service

import (
	"context"
	"errors"
	"fmt"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authz"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/agents/domain"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/agents/store"
)

// ErrCollectionNotFound is "Collection not found".
var ErrCollectionNotFound = errors.New("collection not found")

// ErrSkillNotFound is "Skill not found".
var ErrSkillNotFound = errors.New("skill not found")

// CollectionSummary is a collection with its skill count.
type CollectionSummary struct {
	store.Collection
	SkillCount int64
}

// CollectionDetail is a collection with its skills.
type CollectionDetail struct {
	store.Collection
	Skills []store.CollectionSkill
}

// ListCollections is list_cols().
func (s *Service) ListCollections(ctx context.Context, c authn.Caller) ([]CollectionSummary, error) {
	var out []CollectionSummary
	err := s.read(ctx, c.Workspace, func(sess db.Session) error {
		cs, err := cols().List(ctx, sess)
		if err != nil {
			return err
		}
		counts, err := cols().Counts(ctx, sess)
		if err != nil {
			return err
		}
		for _, x := range cs {
			out = append(out, CollectionSummary{Collection: x, SkillCount: counts[x.ID]})
		}
		return nil
	})
	return out, err
}

// CreateCollection is create plus the owner grant, before the commit.
func (s *Service) CreateCollection(ctx context.Context, c authn.Caller, name string, description *string) (CollectionSummary, error) {
	id := uuid.New()
	var slug string
	err := retrySlug(func() error {
		return s.write(ctx, c.Workspace, func(sess db.Session) error { return s.insertCollection(ctx, sess, c, id, name, description, &slug) })
	})
	return CollectionSummary{Collection: store.Collection{ID: id.String(), Name: name, Slug: slug, Description: description}}, err
}

func (s *Service) insertCollection(ctx context.Context, sess db.Session, c authn.Caller, id uuid.UUID, name string, description *string, out *string) error {
	var slug string
	base := domain.Slug(name)
	for i := 1; i <= domain.MaxSlugSuffix+1; i++ {
		if i > domain.MaxSlugSuffix {
			return fmt.Errorf("exhausted collision suffixes (-2..-999) for slug base '%s'", base)
		}
		cand := base
		if i > 1 {
			cand = fmt.Sprintf("%s-%d", base, i)
		}
		taken, err := cols().SlugTaken(ctx, sess, cand)
		if err != nil {
			return err
		}
		if !taken {
			slug = cand
			break
		}
	}
	if err := cols().Insert(ctx, sess, id, c.UserID, name, slug, description, s.d.Now()); err != nil {
		return err
	}
	*out = slug
	return authz.GrantResourceOwner(ctx, s.d.Graph, id.String(), c.Workspace.ID(), authz.UserSubject(c.UserID), authz.OwnerRelations())
}

func (s *Service) requireOn(ctx context.Context, c authn.Caller, permission string, id uuid.UUID) error {
	return s.Require(ctx, c, permission, id)
}

// GetCollection is get_collection.
func (s *Service) GetCollection(ctx context.Context, c authn.Caller, id uuid.UUID) (CollectionDetail, error) {
	var out CollectionDetail
	err := s.read(ctx, c.Workspace, func(sess db.Session) error {
		col, ok, err := cols().Get(ctx, sess, id)
		if err != nil {
			return err
		}
		if !ok {
			return ErrCollectionNotFound
		}
		skills, err := cols().Skills(ctx, sess, id)
		out = CollectionDetail{Collection: col, Skills: skills}
		return err
	})
	return out, err
}

// UpdateCollection is update_collection after the edit check.
// A description sent as null clears it.
func (s *Service) UpdateCollection(ctx context.Context, c authn.Caller, id uuid.UUID, name *string, description Set[string]) (CollectionSummary, error) {
	if err := s.requireOn(ctx, c, "edit", id); err != nil {
		return CollectionSummary{}, err
	}
	if name != nil || description.Set {
		now := s.d.Now()
		var found bool
		err := s.write(ctx, c.Workspace, func(sess db.Session) error {
			_, ok, err := cols().Get(ctx, sess, id)
			found = ok
			if err != nil || !ok {
				return err
			}
			return cols().Update(ctx, sess, id, name, description.Set, description.Value, now)
		})
		if err != nil {
			return CollectionSummary{}, err
		}
		if !found {
			return CollectionSummary{}, ErrCollectionNotFound
		}
	}
	var out CollectionSummary
	err := s.read(ctx, c.Workspace, func(sess db.Session) error {
		col, ok, err := cols().Get(ctx, sess, id)
		if err != nil {
			return err
		}
		if !ok {
			return ErrCollectionNotFound
		}
		n, err := cols().Count(ctx, sess, id)
		out = CollectionSummary{Collection: col, SkillCount: n}
		return err
	})
	return out, err
}

// DeleteCollection is delete_collection after the delete check; the graph tuples go after the commit.
func (s *Service) DeleteCollection(ctx context.Context, c authn.Caller, id uuid.UUID) error {
	if err := s.requireOn(ctx, c, "delete", id); err != nil {
		return err
	}
	var deleted bool
	err := s.write(ctx, c.Workspace, func(sess db.Session) error {
		var err error
		deleted, err = cols().Delete(ctx, sess, id)
		return err
	})
	if err != nil {
		return err
	}
	if !deleted {
		return ErrCollectionNotFound
	}
	if rw, ok := s.d.Graph.(authz.ReadWriter); ok {
		if err := authz.RevokeResource(ctx, rw, id.String()); err != nil && s.d.Log != nil {
			s.d.Log.WarnContext(ctx, "revoking a deleted collection's tuples failed", "collection_id", id.String(), "error", err.Error())
		}
	}
	return nil
}

// AddCollectionSkill is add_skill_to_collection after the edit check.
func (s *Service) AddCollectionSkill(ctx context.Context, c authn.Caller, collection, skill uuid.UUID) error {
	if err := s.requireOn(ctx, c, "edit", collection); err != nil {
		return err
	}
	return s.write(ctx, c.Workspace, func(sess db.Session) error {
		if _, ok, err := cols().Get(ctx, sess, collection); err != nil || !ok {
			if err == nil {
				err = ErrCollectionNotFound
			}
			return err
		}
		if ok, err := (store.Lookup{}).SkillExists(ctx, sess, skill); err != nil || !ok {
			if err == nil {
				err = ErrSkillNotFound
			}
			return err
		}
		return cols().AddSkill(ctx, sess, collection, skill, s.d.Now())
	})
}

// RemoveCollectionSkill is remove_skill_from_collection after the edit check.
func (s *Service) RemoveCollectionSkill(ctx context.Context, c authn.Caller, collection, skill uuid.UUID) error {
	if err := s.requireOn(ctx, c, "edit", collection); err != nil {
		return err
	}
	return s.write(ctx, c.Workspace, func(sess db.Session) error {
		if _, ok, err := cols().Get(ctx, sess, collection); err != nil || !ok {
			if err == nil {
				err = ErrCollectionNotFound
			}
			return err
		}
		return cols().RemoveSkill(ctx, sess, collection, skill)
	})
}

func cols() store.Collections { return store.Collections{} }
