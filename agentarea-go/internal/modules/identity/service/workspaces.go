package service

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"slices"
	"strings"
	"time"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authz"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/blob"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/identity/domain"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/identity/store"
)

// LogoURLTTL is how long a presigned logo URL lives (presigned_url expires_in).
const LogoURLTTL = 3600 * time.Second

// LogoPrefix is where logos live in the artifacts bucket.
const LogoPrefix = "workspace-logos"

// WorkspaceView is WorkspaceResponse: a workspace as one caller sees it.
type WorkspaceView struct {
	domain.Workspace
	CanAdminister bool
	LogoURL       *string
}

// errPersonalUnnamed is PersonalWorkspaceIdentityError.
type errPersonalUnnamed struct{ msg string }

func (e *errPersonalUnnamed) Error() string { return e.msg }

// ListWorkspaces is list_reachable_workspaces then describe_workspaces: the
// personal workspace is provisioned for a credential that may join
// workspaces, and any other credential sees only what it was narrowed to.
func (s *Service) ListWorkspaces(ctx context.Context, p authn.Principal) ([]WorkspaceView, error) {
	var memberIDs []string
	if s.d.Reader != nil {
		var err error
		if memberIDs, err = authz.MemberWorkspaceIDs(ctx, s.d.Reader, p.UserID); err != nil {
			return nil, err
		}
	}
	provision := p.Credential != nil && p.Credential.Grants(authn.ScopeWorkspaces)
	if provision {
		if err := s.ensurePersonal(ctx, p); err != nil {
			var unnamed *errPersonalUnnamed
			if !errors.As(err, &unnamed) {
				return nil, err
			}
			s.log.ErrorContext(ctx, "Listing workspaces of user without their personal one", "user_id", p.UserID, "error", err)
		}
	}
	q, release, err := s.d.DB.Global().Read(ctx)
	if err != nil {
		return nil, err
	}
	rows, err := s.d.Store.ListWorkspacesForUser(ctx, q, p.UserID, memberIDs)
	release()
	if err != nil {
		return nil, err
	}
	if !provision {
		rows = slices.DeleteFunc(rows, func(w domain.Workspace) bool { return !slices.Contains(p.AccessibleWorkspaces, w.ID) })
	}
	admin := p.AdminWorkspaces
	if admin == nil {
		if admin, err = s.OwnedWorkspaceIDs(ctx, p.UserID); err != nil {
			s.log.ErrorContext(ctx, "Failed to resolve administered workspaces", "user_id", p.UserID, "error", err)
			admin = []string{}
		}
	}
	out := make([]WorkspaceView, 0, len(rows))
	for _, w := range rows {
		v, err := s.describe(ctx, p, admin, w)
		if err != nil {
			return nil, err
		}
		out = append(out, v)
	}
	return out, nil
}

// describe is describe_workspace for a caller administering admin.
func (s *Service) describe(ctx context.Context, p authn.Principal, admin []string, w domain.Workspace) (WorkspaceView, error) {
	v := WorkspaceView{Workspace: w, CanAdminister: !p.ActsAsAgent() && (w.ID == p.UserID || slices.Contains(admin, w.ID))}
	if w.LogoKey == nil {
		return v, nil
	}
	if s.d.Logos == nil {
		return WorkspaceView{}, fmt.Errorf("workspace %s: %w", w.ID, domain.ErrNoLogoStore)
	}
	u, err := s.d.Logos.PresignGet(ctx, *w.LogoKey, LogoURLTTL)
	if err != nil {
		return WorkspaceView{}, err
	}
	v.LogoURL = &u.URL
	return v, nil
}

// ensurePersonal is ensure_personal: the workspace whose id is the user's,
// named after their email's local part.
func (s *Service) ensurePersonal(ctx context.Context, p authn.Principal) error {
	q, release, err := s.d.DB.Global().Read(ctx)
	if err != nil {
		return err
	}
	_, found, err := s.d.Store.GetWorkspace(ctx, q, p.UserID)
	release()
	if err != nil || found {
		return err
	}
	email := p.Email
	if email == "" {
		if email, err = s.emailOf(ctx, p.UserID); err != nil {
			return err
		}
	}
	local, _, _ := strings.Cut(email, "@")
	base := scope.SlugifyWorkspace(local, "user")
	for range insertAttempts {
		err := s.d.DB.Global().Write(ctx, func(ctx context.Context, q db.Querier) error {
			slug, err := s.nextFreeSlug(ctx, q, base)
			if err != nil {
				return err
			}
			w := domain.Workspace{ID: p.UserID, Slug: slug, Name: "Personal", OwnerUserID: p.UserID}
			if err := s.seed(ctx, w.ID, p.UserID); err != nil {
				return err
			}
			created, err := s.d.Store.InsertWorkspace(ctx, q, w)
			if err != nil {
				return err
			}
			return s.created(ctx, q, created, p.UserID)
		})
		if !isUniqueViolation(err) {
			return err
		}
		q, release, rerr := s.d.DB.Global().Read(ctx)
		if rerr != nil {
			return rerr
		}
		_, found, rerr := s.d.Store.GetWorkspace(ctx, q, p.UserID)
		release()
		if rerr != nil || found {
			return rerr
		}
	}
	return fmt.Errorf("%w from base %q", domain.ErrSlugsExhausted, base)
}

// seed is the before_insert hook: the graph tuples first, a failure a 503.
func (s *Service) seed(ctx context.Context, workspaceID, ownerUserID string) error {
	err := authz.SeedWorkspace(ctx, s.d.Graph, workspaceID, ownerUserID)
	if own, ok := errors.AsType[*authz.OwnershipError](err); ok {
		return &domain.Refusal{Status: 503, Detail: own.Msg}
	}
	return err
}

func (s *Service) created(ctx context.Context, q db.Querier, w domain.Workspace, ownerUserID string) error {
	if s.d.OnWorkspaceCreated == nil {
		return nil
	}
	ws, err := scope.NewWorkspace(w.ID, w.Slug)
	if err != nil {
		return err
	}
	if err := s.d.OnWorkspaceCreated(ctx, q, ws, ownerUserID); err != nil {
		s.log.ErrorContext(ctx, "workspace not created: admission failed", "workspace_id", w.ID, "error", err)
		return err
	}
	return nil
}

// emailOf is WorkspaceService._email_of.
func (s *Service) emailOf(ctx context.Context, userID string) (string, error) {
	if s.d.Directory == nil {
		return "", &errPersonalUnnamed{msg: "User " + userID + " has no email on their credential and KRATOS_ADMIN_URL is unset, so their personal workspace cannot be named"}
	}
	rec, err := s.d.Directory.Lookup(ctx, userID)
	if errors.Is(err, store.ErrDirectoryUnavailable) {
		return "", &errPersonalUnnamed{msg: "The identity provider is unavailable, so the personal workspace of user " + userID + " cannot be named yet: " + err.Error()}
	}
	if err != nil {
		return "", err
	}
	if rec == nil || rec.Email == nil || *rec.Email == "" {
		return "", &errPersonalUnnamed{msg: "The identity provider returned no email for user " + userID + "; their personal workspace cannot be named"}
	}
	return *rec.Email, nil
}

// SetLogo is WorkspaceLogoService.set for an admin of the caller's workspace.
func (s *Service) SetLogo(ctx context.Context, c authn.Caller, data []byte) (WorkspaceView, error) {
	if err := s.requireAdmin(ctx, &c); err != nil {
		return WorkspaceView{}, err
	}
	if s.d.Logos == nil {
		return WorkspaceView{}, domain.ErrNoLogoStore
	}
	if len(data) > domain.LogoMaxBytes {
		return WorkspaceView{}, domain.ErrLogoTooLarge
	}
	contentType, ok := domain.LogoContentType(data)
	if !ok {
		return WorkspaceView{}, domain.ErrLogoType
	}
	w, err := s.workspace(ctx, c.Workspace.ID())
	if err != nil {
		return WorkspaceView{}, err
	}
	sum := sha256.Sum256(data)
	key := LogoPrefix + "/" + w.ID + "/" + hex.EncodeToString(sum[:])
	if err := s.d.Logos.Put(ctx, key, bytes.NewReader(data), int64(len(data)), blob.PutOptions{ContentType: contentType}); err != nil {
		return WorkspaceView{}, err
	}
	previous := w.LogoKey
	if err := s.setLogoKey(ctx, w.ID, &key); err != nil {
		return WorkspaceView{}, err
	}
	w.LogoKey = &key
	if previous != nil && *previous != key {
		if err := s.d.Logos.Delete(ctx, *previous); err != nil {
			return WorkspaceView{}, err
		}
	}
	return s.describe(ctx, c.Principal, c.AdminWorkspaces, w)
}

// RemoveLogo is WorkspaceLogoService.remove for an admin of the caller's workspace.
func (s *Service) RemoveLogo(ctx context.Context, c authn.Caller) (WorkspaceView, error) {
	if err := s.requireAdmin(ctx, &c); err != nil {
		return WorkspaceView{}, err
	}
	w, err := s.workspace(ctx, c.Workspace.ID())
	if err != nil {
		return WorkspaceView{}, err
	}
	if previous := w.LogoKey; previous != nil {
		if s.d.Logos == nil {
			return WorkspaceView{}, domain.ErrNoLogoStore
		}
		if err := s.setLogoKey(ctx, w.ID, nil); err != nil {
			return WorkspaceView{}, err
		}
		w.LogoKey = nil
		if err := s.d.Logos.Delete(ctx, *previous); err != nil {
			return WorkspaceView{}, err
		}
	}
	return s.describe(ctx, c.Principal, c.AdminWorkspaces, w)
}

func (s *Service) workspace(ctx context.Context, id string) (domain.Workspace, error) {
	q, release, err := s.d.DB.Global().Read(ctx)
	if err != nil {
		return domain.Workspace{}, err
	}
	defer release()
	w, ok, err := s.d.Store.GetWorkspace(ctx, q, id)
	if err != nil {
		return domain.Workspace{}, err
	}
	if !ok {
		return domain.Workspace{}, domain.ErrWorkspaceNotFound
	}
	return w, nil
}

func (s *Service) setLogoKey(ctx context.Context, id string, key *string) error {
	return s.d.DB.Global().Write(ctx, func(ctx context.Context, q db.Querier) error {
		return s.d.Store.SetLogoKey(ctx, q, id, key, s.local())
	})
}

// requireAdmin is assert_workspace_admin_of(actor, actor.workspace_id): a
// run never administers, and a caller minted off the edge has its owned
// workspaces resolved first.
func (s *Service) requireAdmin(ctx context.Context, c *authn.Caller) error {
	return authz.NewAdmins(authz.WorkspaceScoped{}, s, s.log).RequireOf(ctx, c, c.Workspace.ID())
}
