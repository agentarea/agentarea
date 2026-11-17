package service

import (
	"context"
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"errors"
	"fmt"
	"log/slog"
	"strings"
	"time"
	"unicode"

	"github.com/google/uuid"
	"golang.org/x/text/cases"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authz"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/events"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/identity/domain"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/identity/store"
)

// Service is WorkspaceService.create_shared, WorkspaceInvitationService,
// WorkspaceMembershipService.admit and AccessTokenService.create_token.
type Service struct {
	d   Deps
	log *slog.Logger
}

// New builds the service.
func New(d Deps, log *slog.Logger) *Service {
	if d.Now == nil {
		d.Now = time.Now
	}
	if d.Outbox == nil {
		d.Outbox = events.Publish
	}
	if log == nil {
		log = slog.Default()
	}
	return &Service{d: d, log: log}
}

// insertAttempts is _insert_with_unique_slug's retry bound.
const insertAttempts = 5

// DefaultExpiryDays and TokenBytes are the invitation service's constants.
const (
	DefaultExpiryDays = 7
	TokenBytes        = 32
)

func (s *Service) local() time.Time { return s.d.Now() }

func (s *Service) utc() time.Time {
	t := s.d.Now().UTC()
	return time.Date(t.Year(), t.Month(), t.Day(), t.Hour(), t.Minute(), t.Second(), t.Nanosecond(), time.UTC)
}

func isUniqueViolation(err error) bool {
	var st interface{ SQLState() string }
	return errors.As(err, &st) && st.SQLState() == "23505"
}

// CreateWorkspace is create_workspace after the name check: the graph is
// seeded before the row, the row and the creation hook commit together,
// a slug race retries, and the graph is re-seeded after.
func (s *Service) CreateWorkspace(ctx context.Context, ownerUserID, name string) (domain.Workspace, error) {
	base := scope.SlugifyWorkspace(name, "workspace")
	for range insertAttempts {
		var created domain.Workspace
		err := s.d.DB.Global().Write(ctx, func(ctx context.Context, q db.Querier) error {
			slug, err := s.nextFreeSlug(ctx, q, base)
			if err != nil {
				return err
			}
			w := domain.Workspace{ID: uuid.NewString(), Slug: slug, Name: name, OwnerUserID: ownerUserID}
			if err := s.seed(ctx, w.ID, ownerUserID); err != nil {
				return err
			}
			created, err = s.d.Store.InsertWorkspace(ctx, q, w)
			if err != nil {
				return err
			}
			return s.created(ctx, q, created, ownerUserID)
		})
		if isUniqueViolation(err) {
			continue
		}
		if err != nil {
			return domain.Workspace{}, err
		}
		if err := authz.SeedWorkspace(ctx, s.d.Graph, created.ID, ownerUserID); err != nil {
			s.log.ErrorContext(ctx, "Failed to seed authorization graph for workspace", "workspace_id", created.ID, "error", err)
			return domain.Workspace{}, fmt.Errorf("%w: %w", domain.ErrGraphSeedFailed, err)
		}
		return created, nil
	}
	return domain.Workspace{}, fmt.Errorf("%w from base %q", domain.ErrSlugsExhausted, base)
}

// nextFreeSlug is _next_free_slug: base, then base-2, base-3, ... unbounded.
func (s *Service) nextFreeSlug(ctx context.Context, q db.Querier, base string) (string, error) {
	candidate := base
	for suffix := 2; ; suffix++ {
		taken, err := s.d.Store.SlugTaken(ctx, q, candidate)
		if err != nil || !taken {
			return candidate, err
		}
		candidate = fmt.Sprintf("%s-%d", base, suffix)
	}
}

// OwnedWorkspaceIDs implements authz.OwnedWorkspaces.
func (s *Service) OwnedWorkspaceIDs(ctx context.Context, userID string) ([]string, error) {
	q, release, err := s.d.DB.Global().Read(ctx)
	if err != nil {
		return nil, err
	}
	defer release()
	return s.d.Store.OwnedWorkspaceIDs(ctx, q, userID)
}

func hashToken(token string) string {
	sum := sha256.Sum256([]byte(token))
	return hex.EncodeToString(sum[:])
}

// CreatedInvitation is an invitation with its plaintext token.
type CreatedInvitation struct {
	domain.Invitation
	Token         string
	EmailDelivery domain.EmailDelivery
	// InviterDisplayName is nil: no identity directory is wired.
	InviterDisplayName *string
}

// CreateInvitation is create_invitation; the caller is a workspace admin
// (requires_workspace_admin ran at the edge). An addressed invitation is then
// mailed when the deployment has transactional mail.
func (s *Service) CreateInvitation(ctx context.Context, c authn.Caller, email *string, expiresInDays *int) (CreatedInvitation, error) {
	days := DefaultExpiryDays
	if expiresInDays != nil {
		days = *expiresInDays
	}
	raw := make([]byte, TokenBytes)
	if _, err := rand.Read(raw); err != nil {
		return CreatedInvitation{}, err
	}
	token := base64.RawURLEncoding.EncodeToString(raw)
	var inv domain.Invitation
	err := s.d.DB.Write(ctx, c.Workspace, func(ctx context.Context, sess db.Session) error {
		var err error
		inv, err = s.d.Store.InsertInvitation(ctx, sess, uuid.New(), email, hashToken(token), c.UserID,
			s.utc().AddDate(0, 0, days), s.local())
		return err
	})
	if err != nil {
		return CreatedInvitation{}, err
	}
	var recipient any
	if inv.Email != nil {
		recipient = *inv.Email
	}
	if err := s.audit(ctx, c, "member.invite", "invitation", inv.ID, map[string]any{"resource_name": recipient}); err != nil {
		return CreatedInvitation{}, err
	}
	delivery := s.deliverInvitation(ctx, c, email, token)
	return CreatedInvitation{Invitation: inv, Token: token, EmailDelivery: delivery}, nil
}

func pyStrip(s string) string {
	return strings.TrimFunc(s, func(r rune) bool { return unicode.IsSpace(r) || (r >= 0x1c && r <= 0x1f) })
}

func fold(s string) string { return cases.Fold().String(pyStrip(s)) }

// AcceptInvitation is accept, then admit.
func (s *Service) AcceptInvitation(ctx context.Context, p authn.Principal, token string) (domain.Invitation, error) {
	var email *string
	if p.Email != "" {
		email = &p.Email
	}
	var inv domain.Invitation
	err := s.d.DB.Global().Write(ctx, func(ctx context.Context, q db.Querier) error {
		found, ok, err := s.d.Store.InvitationByTokenHash(ctx, q, hashToken(token))
		if err != nil {
			return err
		}
		if !ok {
			return domain.ErrInvitationNotFound
		}
		if !domain.AddressedTo(found, email, fold) {
			return domain.ErrAddressedElsewhere
		}
		switch {
		case found.Status == domain.StatusRevoked:
			return domain.ErrInvitationRevoked
		case found.Status == domain.StatusAccepted:
			if found.AcceptedByUserID != nil && *found.AcceptedByUserID == p.UserID {
				inv = found
				return nil
			}
			return domain.ErrInvitationAccepted
		case !s.utc().Before(found.ExpiresAt):
			return domain.ErrInvitationExpired
		}
		at := s.utc()
		if err := s.d.Store.MarkAccepted(ctx, q, uuid.MustParse(found.ID), p.UserID, at, s.local()); err != nil {
			return err
		}
		found.Status, found.AcceptedAt, found.AcceptedByUserID = domain.StatusAccepted, &at, &p.UserID
		inv = found
		return nil
	})
	if err != nil {
		return domain.Invitation{}, err
	}
	return inv, s.admit(ctx, inv, p.UserID)
}

// admit grants the membership an accepted invitation promised, once.
func (s *Service) admit(ctx context.Context, inv domain.Invitation, userID string) error {
	if inv.MembershipGrantedAt != nil {
		return nil
	}
	if err := authz.GrantWorkspaceMembership(ctx, s.d.Graph, inv.WorkspaceID, userID); err != nil {
		return s.graphDown(ctx, err)
	}
	var granted, member bool
	err := s.d.DB.Global().Write(ctx, func(ctx context.Context, q db.Querier) error {
		var err error
		granted, err = s.d.Store.AddForInvitation(ctx, q, uuid.MustParse(inv.ID), inv.WorkspaceID, userID, s.utc(), s.local())
		if err != nil || granted {
			return err
		}
		member, err = s.d.Store.MembershipExists(ctx, q, inv.WorkspaceID, userID)
		return err
	})
	if err != nil || granted {
		return err
	}
	if !member {
		if err := authz.RevokeWorkspaceMembership(ctx, s.d.Graph, inv.WorkspaceID, userID); err != nil {
			return s.graphDown(ctx, err)
		}
	}
	return domain.ErrInvitationRevoked
}

func (s *Service) graphDown(ctx context.Context, err error) error {
	var resp *authz.ResponseError
	var unavailable *authz.UnavailableError
	if errors.As(err, &resp) || errors.As(err, &unavailable) {
		s.log.ErrorContext(ctx, "Failed to grant workspace membership", "error", err)
		return fmt.Errorf("%w: %w", domain.ErrMembershipGraphDown, err)
	}
	return err
}

// CreatedAPIKey is a key with its plaintext token.
type CreatedAPIKey struct {
	domain.APIKey
	Token string
}

// CreateAPIKey is create_api_key after the scope check: a bound agent must
// be one of the workspace's.
func (s *Service) CreateAPIKey(ctx context.Context, c authn.Caller, name string, expiresInDays *int, agentID *string) (CreatedAPIKey, error) {
	var agent *uuid.UUID
	if agentID != nil {
		ok, err := s.d.Agents.AgentExists(ctx, c.Workspace, *agentID)
		if err != nil {
			return CreatedAPIKey{}, err
		}
		if !ok {
			return CreatedAPIKey{}, domain.ErrAgentNotFound
		}
		u := uuid.MustParse(*agentID)
		agent = &u
	}
	token, prefix, hash, err := authn.NewAPIKey()
	if err != nil {
		return CreatedAPIKey{}, s.keyFailed(ctx, err)
	}
	k := store.NewAPIKey{ID: uuid.New(), CreatedBy: c.UserID, Name: name, TokenHash: hash, TokenPrefix: prefix, AgentID: agent}
	if expiresInDays != nil && *expiresInDays != 0 {
		at := s.utc().AddDate(0, 0, *expiresInDays)
		k.ExpiresAt = &at
	}
	var created domain.APIKey
	err = s.d.DB.Write(ctx, c.Workspace, func(ctx context.Context, sess db.Session) error {
		var err error
		created, err = s.d.Store.InsertAPIKey(ctx, sess, k, s.local())
		return err
	})
	if err != nil {
		return CreatedAPIKey{}, s.keyFailed(ctx, err)
	}
	var agentMeta, expiresMeta any
	if created.AgentID != nil {
		agentMeta = *created.AgentID
	}
	if created.ExpiresAt != nil {
		expiresMeta = pyIsoformat(*created.ExpiresAt)
	}
	if err := s.audit(ctx, c, "api_key.create", "api_key", created.ID, map[string]any{
		"resource_name": created.Name, "token_prefix": created.TokenPrefix, "agent_id": agentMeta, "expires_at": expiresMeta,
	}); err != nil {
		return CreatedAPIKey{}, err
	}
	return CreatedAPIKey{APIKey: created, Token: token}, nil
}

// pyIsoformat is datetime.isoformat() of a naive UTC timestamp.
func pyIsoformat(t time.Time) string {
	t = t.UTC()
	out := t.Format("2006-01-02T15:04:05")
	if us := t.Nanosecond() / 1000; us != 0 {
		out += fmt.Sprintf(".%06d", us)
	}
	return out
}

func (s *Service) keyFailed(ctx context.Context, err error) error {
	s.log.ErrorContext(ctx, "Failed to create API key", "error", err)
	return fmt.Errorf("%w: %w", domain.ErrAPIKeyCreateFailed, err)
}
