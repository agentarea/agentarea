package domain

import (
	"cmp"
	"errors"
	"slices"
	"time"
)

// Member is WorkspaceMemberView: a graph member with what its membership row
// adds. JoinedAt is nil for members granted before rows were written.
type Member struct {
	UserID       string
	JoinedAt     *time.Time
	InvitationID *string
}

// MembershipRow is a workspace_memberships row.
type MembershipRow struct {
	UserID       string
	CreatedAt    time.Time
	InvitationID *string
}

// Members joins the graph's member ids with the rows and orders them as
// _member_order does: known join dates first, by date, then by user id.
func Members(memberIDs []string, rows []MembershipRow) []Member {
	byUser := make(map[string]MembershipRow, len(rows))
	for _, r := range rows {
		byUser[r.UserID] = r
	}
	out := make([]Member, 0, len(memberIDs))
	for _, id := range memberIDs {
		m := Member{UserID: id}
		if r, ok := byUser[id]; ok {
			at := r.CreatedAt
			m.JoinedAt, m.InvitationID = &at, r.InvitationID
		}
		out = append(out, m)
	}
	slices.SortStableFunc(out, func(a, b Member) int {
		switch {
		case a.JoinedAt == nil && b.JoinedAt != nil:
			return 1
		case a.JoinedAt != nil && b.JoinedAt == nil:
			return -1
		case a.JoinedAt != nil && !a.JoinedAt.Equal(*b.JoinedAt):
			return a.JoinedAt.Compare(*b.JoinedAt)
		}
		return cmp.Compare(a.UserID, b.UserID)
	})
	return out
}

// Identity is IdentityRecord: what the identity provider knows of a user.
type Identity struct {
	UserID      string
	Email       *string
	DisplayName *string
}

// IdentityFor is identity_for: the directory's answer, and for the caller
// alone the email of their own verified token.
func IdentityFor(userID string, identities map[string]Identity, currentUserID string, currentEmail *string) Identity {
	out := Identity{UserID: userID}
	if id, ok := identities[userID]; ok {
		out.Email, out.DisplayName = id.Email, id.DisplayName
	}
	if userID == currentUserID {
		if out.Email == nil {
			out.Email = currentEmail
		}
		if out.DisplayName == nil {
			out.DisplayName = out.Email
		}
	}
	return out
}

// Membership refusals (workspaces/service.py), with the route's status.
var (
	ErrOwnerRemoval    = &Refusal{Status: 409, Detail: "The workspace owner cannot be removed; transfer ownership first."}
	ErrLastMember      = &Refusal{Status: 409, Detail: "The last member cannot leave; the workspace would be unreachable."}
	ErrRemovalOwner    = &Refusal{Status: 403, Detail: "Only the workspace owner can remove other members."}
	ErrMemberGone      = &Refusal{Status: 404, Detail: "Member not found"}
	ErrAgentMembership = &Refusal{Status: 403, Detail: "An agent cannot change who is a member of the workspace."}
)

// Refusal is an HTTPException the module raises: status and detail.
type Refusal struct {
	Status int
	Detail string
}

func (e *Refusal) Error() string { return e.Detail }

// OwnershipUnavailableError is a ResourceOwnershipError that reached the app's
// handler (503 resource_ownership_unavailable).
type OwnershipUnavailableError struct{ Err error }

func (e *OwnershipUnavailableError) Error() string { return e.Err.Error() }

func (e *OwnershipUnavailableError) Unwrap() error { return e.Err }

// More refusals of the module's routes.
var (
	ErrInvitationIDNotFound   = &Refusal{Status: 404, Detail: "Invitation not found"}
	ErrInvitationWorkspace    = &Refusal{Status: 404, Detail: "invitation workspace not found"}
	ErrAPIKeyNotFound         = &Refusal{Status: 404, Detail: "API key not found"}
	ErrLinkNotFound           = &Refusal{Status: 404, Detail: "No such linked account"}
	ErrLinkingNeedsRedis      = &Refusal{Status: 503, Detail: "Account linking needs the Redis broker"}
	ErrRemovalNeedsDirectory  = &Refusal{Status: 500, Detail: "Member removal needs the identity directory"}
	ErrLogoTooLarge           = &Refusal{Status: 413, Detail: "Logo exceeds the 1048576-byte limit"}
	ErrLogoType               = &Refusal{Status: 422, Detail: "Logo must be a PNG, JPEG or WebP image"}
	ErrWorkspaceNotFound      = &Refusal{Status: 404, Detail: "Workspace not found"}
	ErrNoLogoStore            = errors.New("workspace logos need the object store, which is not wired")
	ErrPersonalWorkspaceNamed = errors.New("personal workspace cannot be named")
)

// LogoMaxBytes is LOGO_MAX_BYTES.
const LogoMaxBytes = 1024 * 1024

// LogoContentType is logo_content_type: the image type by magic bytes.
func LogoContentType(data []byte) (string, bool) {
	switch {
	case len(data) >= 8 && string(data[:8]) == "\x89PNG\r\n\x1a\n":
		return "image/png", true
	case len(data) >= 3 && string(data[:3]) == "\xff\xd8\xff":
		return "image/jpeg", true
	case len(data) >= 12 && string(data[:4]) == "RIFF" && string(data[8:12]) == "WEBP":
		return "image/webp", true
	}
	return "", false
}

// ExternalIdentity is a live user_external_identities row.
type ExternalIdentity struct {
	ID         string
	Provider   string
	ExternalID string
	CreatedAt  time.Time
}

// LinkTTLSeconds is LINK_TTL_SECONDS.
const LinkTTLSeconds = 600
