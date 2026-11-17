package service

import (
	"context"
	"time"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/agents/domain"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/agents/store"
)

// SkillMovedCopyMinAge is delete_moved_own_copies' default min_age.
const SkillMovedCopyMinAge = 7 * 24 * time.Hour

func (k *Skills) globalRefs(ctx context.Context, fn func(q db.Querier) ([]store.SkillRef, error)) ([]store.SkillRef, error) {
	q, release, err := k.s.d.DB.Global().Read(ctx)
	if err != nil {
		return nil, err
	}
	defer release()
	return fn(q)
}

// eachRef runs move on every skill in its own write session under its own
// workspace; a failure is logged and counted, and leaves the rest to go on.
func (k *Skills) eachRef(ctx context.Context, refs []store.SkillRef, failMsg string,
	move func(ctx context.Context, sess db.Session, sk *domain.Skill) (bool, error)) (moved, failed int) {
	for _, r := range refs {
		ws, err := scope.NewWorkspace(r.WorkspaceID, "")
		if err == nil {
			err = k.s.write(ctx, ws, func(sess db.Session) error {
				sk, ok, err := skills().Get(ctx, sess, r.ID)
				if err != nil || !ok {
					return err
				}
				did, err := move(ctx, sess, &sk)
				if did {
					moved++
				}
				return err
			})
		}
		if err != nil {
			k.warn(ctx, failMsg, "skill_id", r.ID.String(), "error", err.Error())
			failed++
		}
	}
	return moved, failed
}

// MoveBodiesToPackages is `skills move-bodies-to-packages` (move_all_bodies_to_packages).
func (k *Skills) MoveBodiesToPackages(ctx context.Context) (moved, failed int, err error) {
	if _, err := k.store(); err != nil {
		return 0, 0, err
	}
	refs, err := k.globalRefs(ctx, func(q db.Querier) ([]store.SkillRef, error) {
		return skills().WithBodies(ctx, q, SkillPlatformWorkspace)
	})
	if err != nil {
		return 0, 0, err
	}
	moved, failed = k.eachRef(ctx, refs, "Failed to move the body of skill into its package",
		func(ctx context.Context, sess db.Session, sk *domain.Skill) (bool, error) {
			if sk.Content == nil {
				return false, nil
			}
			_, err := k.moveBody(ctx, sess, SkillPlatformPrincipal, sk)
			return err == nil, err
		})
	return moved, failed, nil
}

// MoveOwnCopiesToPackages is `skills move-own-copies-to-packages` (move_all_own_copies_to_packages).
func (k *Skills) MoveOwnCopiesToPackages(ctx context.Context) (moved, failed int, err error) {
	if _, err := k.store(); err != nil {
		return 0, 0, err
	}
	refs, err := k.globalRefs(ctx, func(q db.Querier) ([]store.SkillRef, error) { return skills().AtOwnCopies(ctx, q) })
	if err != nil {
		return 0, 0, err
	}
	moved, failed = k.eachRef(ctx, refs, "Failed to move the copy of skill into a package",
		func(ctx context.Context, sess db.Session, sk *domain.Skill) (bool, error) {
			if !domain.SkillIsOwnCopy(*sk) {
				return false, nil
			}
			_, err := k.moveOwnCopy(ctx, sess, SkillPlatformPrincipal, sk)
			return err == nil, err
		})
	return moved, failed, nil
}

// DeleteMovedOwnCopies is `skills delete-moved-own-copies` (delete_moved_own_copies):
// the pre-package copies no skill has pointed at for minAge; (prefixes, objects).
func (k *Skills) DeleteMovedOwnCopies(ctx context.Context, dryRun bool, minAge time.Duration) (prefixes, objects int, err error) {
	if _, err := k.store(); err != nil {
		return 0, 0, err
	}
	q, release, err := k.s.d.DB.Global().Read(ctx)
	if err != nil {
		return 0, 0, err
	}
	list, err := skills().MovedOwnCopies(ctx, q, k.s.d.Now().Add(-minAge))
	release()
	if err != nil {
		return 0, 0, err
	}
	for _, prefix := range list {
		files, err := k.listFiles(ctx, prefix)
		if err != nil {
			return prefixes, objects, err
		}
		if len(files) == 0 {
			continue
		}
		prefixes++
		if dryRun {
			objects += len(files)
			continue
		}
		n, err := k.deletePackage(ctx, prefix)
		objects += n
		if err != nil {
			return prefixes, objects, err
		}
	}
	return prefixes, objects, nil
}

// RepinCatalogInstalls is `skills repin-catalog-installs`; the catalog does the work.
func (k *Skills) RepinCatalogInstalls(ctx context.Context, dryRun bool) ([]SkillJobResult, error) {
	if k.catalog == nil {
		return nil, k.unwiredCatalog()
	}
	return k.catalog.RepinAll(ctx, dryRun)
}

// RefreshStubInstalls is `skills refresh-stub-installs`; the catalog does the work.
func (k *Skills) RefreshStubInstalls(ctx context.Context, dryRun bool) ([]SkillJobResult, error) {
	if k.catalog == nil {
		return nil, k.unwiredCatalog()
	}
	return k.catalog.RefreshStubs(ctx, dryRun)
}
