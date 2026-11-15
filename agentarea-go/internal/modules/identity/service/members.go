package service

import (
	"context"
	"errors"
	"fmt"
	"slices"
	"strings"
	"time"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authz"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/events"
	governanceapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/governance/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/identity/domain"
)

// MembershipEndedEvent is the outbox event a removal queues; its handler
// finishes the removal in the graph.
const (
	MembershipEndedEvent = "workspace.membership.ended"
	MembershipAggregate  = "workspace_membership"
)

// MemberView is MemberResponse.
type MemberView struct {
	ID           string
	WorkspaceID  string
	UserID       string
	Email        *string
	DisplayName  *string
	JoinedAt     *time.Time
	InvitationID *string
	IsOwner      bool
}

// InvitationView is an invitation with its inviter's display name.
type InvitationView struct {
	domain.Invitation
	InviterDisplayName *string
}

// MemberResponseID is _stable_member_response_id: the user id when Python's
// UUID() reads it as one, else uuid5 over the workspace and the user.
func MemberResponseID(workspaceID, userID string) string {
	if id, ok := PyUUID(userID); ok {
		return id
	}
	return uuid.NewSHA1(uuid.NameSpaceURL, []byte("agentarea:workspace-member:"+workspaceID+":"+userID)).String()
}

// PyUUID is uuid.UUID(s) for a str: "urn:" and "uuid:" removed, braces
// stripped, hyphens dropped wherever they are, then 32 hex digits.
func PyUUID(s string) (string, bool) {
	h := strings.ReplaceAll(strings.ReplaceAll(s, "urn:", ""), "uuid:", "")
	h = strings.ReplaceAll(strings.Trim(h, "{}"), "-", "")
	if len(h) != 32 {
		return "", false
	}
	for i := range len(h) {
		c := h[i]
		if (c < '0' || c > '9') && (c < 'a' || c > 'f') && (c < 'A' || c > 'F') {
			return "", false
		}
	}
	id, err := uuid.Parse(h)
	if err != nil {
		return "", false
	}
	return id.String(), true
}

func (s *Service) identities(ctx context.Context, ids []string) (map[string]domain.Identity, error) {
	if s.d.Directory == nil {
		return map[string]domain.Identity{}, nil
	}
	return s.d.Directory.Resolve(ctx, ids)
}

func (s *Service) memberIDs(ctx context.Context, workspaceID string) ([]string, error) {
	if s.d.Reader == nil {
		return nil, fmt.Errorf("%w: no graph reader", domain.ErrMembershipGraphDown)
	}
	ids, err := authz.WorkspaceMemberIDs(ctx, s.d.Reader, workspaceID)
	if err != nil {
		return nil, s.listDown(ctx, err)
	}
	return ids, nil
}

func (s *Service) listDown(ctx context.Context, err error) error {
	s.log.ErrorContext(ctx, "Failed to list workspace memberships", "error", err)
	return fmt.Errorf("%w: %w", domain.ErrMembershipGraphDown, err)
}

// ownerUserID is owner_user_id: the row's owner, else the id itself.
func (s *Service) ownerUserID(ctx context.Context, q db.Querier, workspaceID string) (string, error) {
	w, ok, err := s.d.Store.GetWorkspace(ctx, q, workspaceID)
	if err != nil || !ok {
		return workspaceID, err
	}
	return w.OwnerUserID, nil
}

// record is WorkspaceMembershipService.record with no invitation.
func (s *Service) record(ctx context.Context, workspaceID, userID string) error {
	if err := authz.GrantWorkspaceMembership(ctx, s.d.Graph, workspaceID, userID); err != nil {
		return s.listDown(ctx, err)
	}
	return s.d.DB.Global().Write(ctx, func(ctx context.Context, q db.Querier) error {
		ok, err := s.d.Store.MembershipExists(ctx, q, workspaceID, userID)
		if err != nil || ok {
			return err
		}
		return s.d.Store.AddMembership(ctx, q, workspaceID, userID, s.local())
	})
}

// ListMembers is list_members: any member of the workspace may list it; the
// personal workspace's owner is recorded as its member on the way.
func (s *Service) ListMembers(ctx context.Context, c authn.Caller) ([]MemberView, error) {
	ws := c.Workspace.ID()
	if ws == c.UserID {
		if err := s.record(ctx, ws, c.UserID); err != nil {
			return nil, err
		}
	}
	ids, err := s.memberIDs(ctx, ws)
	if err != nil {
		return nil, err
	}
	q, release, err := s.d.DB.Global().Read(ctx)
	if err != nil {
		return nil, err
	}
	rows, err := s.d.Store.ListMemberships(ctx, q, ws)
	var owner string
	if err == nil {
		owner, err = s.ownerUserID(ctx, q, ws)
	}
	release()
	if err != nil {
		return nil, err
	}
	members := domain.Members(ids, rows)
	userIDs := make([]string, 0, len(members))
	for _, m := range members {
		userIDs = append(userIDs, m.UserID)
	}
	known, err := s.identities(ctx, userIDs)
	if err != nil {
		return nil, err
	}
	var email *string
	if c.Email != "" {
		email = &c.Email
	}
	out := make([]MemberView, 0, len(members))
	for _, m := range members {
		id := domain.IdentityFor(m.UserID, known, c.UserID, email)
		out = append(out, MemberView{
			ID: MemberResponseID(ws, m.UserID), WorkspaceID: ws, UserID: m.UserID,
			Email: id.Email, DisplayName: id.DisplayName, JoinedAt: m.JoinedAt, InvitationID: m.InvitationID,
			IsOwner: m.UserID == owner,
		})
	}
	return out, nil
}

// ListInvitations is list_pending for an admin, with inviters resolved.
func (s *Service) ListInvitations(ctx context.Context, c authn.Caller) ([]InvitationView, error) {
	if err := s.requireAdmin(ctx, &c); err != nil {
		return nil, err
	}
	sess, release, err := s.d.DB.Read(ctx, c.Workspace)
	if err != nil {
		return nil, err
	}
	invs, err := s.d.Store.ListPendingInvitations(ctx, sess)
	release()
	if err != nil {
		return nil, err
	}
	by := make([]string, 0, len(invs))
	for _, i := range invs {
		by = append(by, i.InvitedBy)
	}
	known, err := s.identities(ctx, by)
	if err != nil {
		return nil, err
	}
	out := make([]InvitationView, 0, len(invs))
	for _, i := range invs {
		v := InvitationView{Invitation: i}
		if rec, ok := known[i.InvitedBy]; ok {
			v.InviterDisplayName = rec.DisplayName
		}
		out = append(out, v)
	}
	return out, nil
}

// RevokeInvitation is revoke: an admin's; a resolved invitation is returned
// as it is. Audited whenever the result is revoked, as the route does.
func (s *Service) RevokeInvitation(ctx context.Context, c authn.Caller, id uuid.UUID) (domain.Invitation, error) {
	if err := s.requireAdmin(ctx, &c); err != nil {
		return domain.Invitation{}, err
	}
	var inv domain.Invitation
	err := s.d.DB.Write(ctx, c.Workspace, func(ctx context.Context, sess db.Session) error {
		found, ok, err := s.d.Store.InvitationByID(ctx, sess.Q(), id)
		if err != nil {
			return err
		}
		if !ok || found.WorkspaceID != c.Workspace.ID() {
			return domain.ErrInvitationIDNotFound
		}
		inv = found
		if found.Status != domain.StatusPending {
			return nil
		}
		if err := s.d.Store.RevokeInvitation(ctx, sess, id, s.local()); err != nil {
			return err
		}
		inv.Status = domain.StatusRevoked
		return nil
	})
	if err != nil {
		return domain.Invitation{}, err
	}
	if inv.Status == domain.StatusRevoked {
		var email any
		if inv.Email != nil {
			email = *inv.Email
		}
		if err := s.audit(ctx, c, "member.invitation_revoke", "invitation", inv.ID, map[string]any{"resource_name": email}); err != nil {
			return domain.Invitation{}, err
		}
	}
	return inv, nil
}

// InvitationPreview is InvitationPreviewResponse.
type InvitationPreview struct {
	WorkspaceName      string
	InviterDisplayName *string
	InviterEmail       *string
	Invitation         domain.Invitation
}

// PreviewInvitation is preview: what accept would check, without accepting.
func (s *Service) PreviewInvitation(ctx context.Context, p authn.Principal, token string) (InvitationPreview, error) {
	var email *string
	if p.Email != "" {
		email = &p.Email
	}
	q, release, err := s.d.DB.Global().Read(ctx)
	if err != nil {
		return InvitationPreview{}, err
	}
	inv, err := s.redeemable(ctx, q, token, p.UserID, email)
	var w domain.Workspace
	var found bool
	if err == nil {
		w, found, err = s.d.Store.GetWorkspace(ctx, q, inv.WorkspaceID)
	}
	release()
	if err != nil {
		return InvitationPreview{}, err
	}
	if !found {
		s.log.ErrorContext(ctx, "Invitation points at missing workspace", "invitation_id", inv.ID, "workspace_id", inv.WorkspaceID)
		return InvitationPreview{}, domain.ErrInvitationWorkspace
	}
	known, err := s.identities(ctx, []string{inv.InvitedBy})
	if err != nil {
		return InvitationPreview{}, err
	}
	out := InvitationPreview{WorkspaceName: w.Name, Invitation: inv}
	if rec, ok := known[inv.InvitedBy]; ok {
		out.InviterDisplayName, out.InviterEmail = rec.DisplayName, rec.Email
	}
	return out, nil
}

// redeemable is _redeemable.
func (s *Service) redeemable(ctx context.Context, q db.Querier, token, userID string, email *string) (domain.Invitation, error) {
	found, ok, err := s.d.Store.InvitationByTokenHash(ctx, q, hashToken(token))
	if err != nil {
		return domain.Invitation{}, err
	}
	if !ok {
		return domain.Invitation{}, domain.ErrInvitationNotFound
	}
	if !domain.AddressedTo(found, email, fold) {
		return domain.Invitation{}, domain.ErrAddressedElsewhere
	}
	switch {
	case found.Status == domain.StatusRevoked:
		return domain.Invitation{}, domain.ErrInvitationRevoked
	case found.Status == domain.StatusAccepted:
		if found.AcceptedByUserID != nil && *found.AcceptedByUserID == userID {
			return found, nil
		}
		return domain.Invitation{}, domain.ErrInvitationAccepted
	case !s.utc().Before(found.ExpiresAt):
		return domain.Invitation{}, domain.ErrInvitationExpired
	}
	return found, nil
}

// RemoveMember is remove then the route's audit: false means the
// membership ended but the graph still grants it until the outbox relay
// finishes the revocation (202).
func (s *Service) RemoveMember(ctx context.Context, c authn.Caller, target string) (bool, error) {
	if c.ActsAsAgent() {
		return false, domain.ErrAgentMembership
	}
	ws := c.Workspace.ID()
	q, release, err := s.d.DB.Global().Read(ctx)
	if err != nil {
		return false, err
	}
	owner, err := s.ownerUserID(ctx, q, ws)
	release()
	if err != nil {
		return false, err
	}
	if target == owner {
		return false, domain.ErrOwnerRemoval
	}
	if c.UserID != owner && c.UserID != target {
		return false, domain.ErrRemovalOwner
	}
	ids, err := s.memberIDs(ctx, ws)
	if err != nil {
		return false, err
	}
	inGraph := slices.Contains(ids, target)
	if !inGraph {
		q, release, err := s.d.DB.Global().Read(ctx)
		if err != nil {
			return false, err
		}
		row, err := s.d.Store.MembershipExists(ctx, q, ws, target)
		release()
		if err != nil {
			return false, err
		}
		if !row {
			return false, domain.ErrMemberGone
		}
	}
	if inGraph && len(ids) <= 1 {
		return false, domain.ErrLastMember
	}
	emails, err := s.emailsOf(ctx, target)
	if err != nil {
		return false, err
	}
	err = s.d.DB.Write(ctx, c.Workspace, func(ctx context.Context, sess db.Session) error {
		if err := s.d.Store.EndMembership(ctx, sess, target, emails, fold, s.local()); err != nil {
			return err
		}
		return s.d.Outbox(ctx, sess, c.UserID, events.NewEnvelope(MembershipEndedEvent, map[string]any{
			"workspace_id": ws, "user_id": target, "aggregate_id": target, "aggregate_type": MembershipAggregate,
		}))
	})
	if err != nil {
		return false, err
	}
	revoked := true
	if err := s.FinishRemoval(ctx, ws, target); err != nil {
		var resp *authz.ResponseError
		var down *authz.UnavailableError
		if !errors.As(err, &resp) && !errors.As(err, &down) {
			return false, err
		}
		s.log.WarnContext(ctx, "graph revocation failed; the outbox relay retries it", "user_id", target, "workspace_id", ws, "error", err)
		revoked = false
	}
	return revoked, s.audit(ctx, c, "member.remove", "member", target, map[string]any{"self_removal": target == c.UserID, "access_revoked": revoked})
}

// emailsOf is _emails_of: where a removed member's invitations may have been sent.
func (s *Service) emailsOf(ctx context.Context, userID string) ([]string, error) {
	if s.d.Directory == nil {
		s.log.ErrorContext(ctx, "Refusing to remove a member: no identity directory to find the invitations addressed to them", "user_id", userID)
		return nil, domain.ErrRemovalNeedsDirectory
	}
	known, err := s.identities(ctx, []string{userID})
	if err != nil {
		return nil, err
	}
	if rec, ok := known[userID]; ok && rec.Email != nil && *rec.Email != "" {
		return []string{*rec.Email}, nil
	}
	s.log.WarnContext(ctx, "no email resolved; only invitations they joined through are matched when revoking the pending ones addressed to them", "user_id", userID)
	return []string{}, nil
}

// FinishRemoval is finish_removal: take an ended membership out of the
// graph unless the user was admitted again or owns the workspace.
func (s *Service) FinishRemoval(ctx context.Context, workspaceID, userID string) error {
	q, release, err := s.d.DB.Global().Read(ctx)
	if err != nil {
		return err
	}
	row, err := s.d.Store.MembershipExists(ctx, q, workspaceID, userID)
	var owner string
	if err == nil && !row {
		owner, err = s.ownerUserID(ctx, q, workspaceID)
	}
	release()
	if err != nil || row || userID == owner {
		return err
	}
	return authz.RevokeWorkspaceMembership(ctx, s.d.Graph, workspaceID, userID)
}

// MembershipRemovalHandler is membership_removal_handler: the outbox relay's
// side of a removal.
func (s *Service) MembershipRemovalHandler() events.OutboxHandler {
	return func(ctx context.Context, _ db.Session, e events.Envelope) error {
		ws, _ := e.Data["workspace_id"].(string)
		user, _ := e.Data["user_id"].(string)
		if ws == "" || user == "" {
			return fmt.Errorf("%s %s: workspace_id and user_id are required", MembershipEndedEvent, e.EventID)
		}
		return s.FinishRemoval(ctx, ws, user)
	}
}

// audit is AuditService.record as the caller; nothing is written until
// governance's writer is wired.
func (s *Service) audit(ctx context.Context, c authn.Caller, action, resourceType, resourceID string, meta map[string]any) error {
	if s.d.Audit == nil {
		return nil
	}
	return s.d.DB.Write(ctx, c.Workspace, func(ctx context.Context, sess db.Session) error {
		return s.d.Audit.RecordOnce(ctx, sess, governanceapi.AuditRecord{
			EventID: uuid.NewString(), Action: action, ResourceType: resourceType, ResourceID: resourceID,
			ActorType: "user", ActorID: c.UserID, Metadata: meta,
		})
	})
}
