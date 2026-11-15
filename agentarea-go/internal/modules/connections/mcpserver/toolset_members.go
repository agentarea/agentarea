package mcpserver

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"strings"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
	identityapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/identity/api"
	sandboxapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/sandbox/api"
)

// logoMaxBytes is LOGO_MAX_BYTES.
const logoMaxBytes = 1024 * 1024

func invitationOutput(i identityapi.Invitation) map[string]any {
	return map[string]any{
		"id": i.ID, "email": i.Email, "invited_by": i.InvitedBy, "status": i.Status,
		"expires_at": i.ExpiresAt, "created_at": i.CreatedAt,
	}
}

// memberTools is tools/members_toolset.py.
func memberTools(m identityapi.Members) map[string]toolDef {
	return map[string]toolDef{
		"list": {title: "List members", effect: effectRead, call: func(ctx context.Context, c authn.Caller, _ json.RawMessage) (any, error) {
			members, err := m.ListMembers(ctx, c)
			if err != nil {
				return nil, err
			}
			out := make([]map[string]any, len(members))
			for i, mb := range members {
				out[i] = map[string]any{
					"user_id": mb.UserID, "email": mb.Email, "display_name": mb.DisplayName,
					"joined_at": mb.JoinedAt, "is_owner": mb.IsOwner, "is_you": mb.IsYou,
				}
			}
			return out, nil
		}},
		"invite": {title: "Invite member", effect: effectPrivileged, openWorld: true, call: func(ctx context.Context, c authn.Caller, args json.RawMessage) (any, error) {
			in, err := decodeArgs[struct {
				Email         *string `json:"email"`
				ExpiresInDays *int    `json:"expires_in_days"`
			}](args)
			if err != nil {
				return nil, err
			}
			inv, err := m.Invite(ctx, c, in.Email, in.ExpiresInDays)
			if err != nil {
				return nil, err
			}
			out := invitationOutput(inv.Invitation)
			out["token"], out["email_delivery"] = inv.Token, inv.EmailDelivery
			return out, nil
		}},
		"list_invitations": {title: "List invitations", effect: effectRead, call: func(ctx context.Context, c authn.Caller, _ json.RawMessage) (any, error) {
			invs, err := m.ListInvitations(ctx, c)
			if err != nil {
				return nil, err
			}
			out := make([]map[string]any, len(invs))
			for i, inv := range invs {
				out[i] = invitationOutput(inv)
			}
			return out, nil
		}},
		"revoke_invitation": {title: "Revoke invitation", effect: effectPrivileged, idempotent: true, call: func(ctx context.Context, c authn.Caller, args json.RawMessage) (any, error) {
			in, err := decodeArgs[struct {
				InvitationID string `json:"invitation_id"`
			}](args)
			if err != nil {
				return nil, err
			}
			if err := m.RevokeInvitation(ctx, c, in.InvitationID); err != nil {
				return nil, err
			}
			return map[string]any{"revoked": true}, nil
		}},
		"remove": {title: "Remove member", effect: effectPrivileged, idempotent: true, call: func(ctx context.Context, c authn.Caller, args json.RawMessage) (any, error) {
			in, err := decodeArgs[struct {
				UserID string `json:"user_id"`
			}](args)
			if err != nil {
				return nil, err
			}
			revoked, err := m.RemoveMember(ctx, c, in.UserID)
			if err != nil {
				return nil, err
			}
			if !revoked {
				return map[string]any{"status": "revocation_pending", "user_id": in.UserID,
					"detail": "The membership has ended; its access is still being revoked."}, nil
			}
			return map[string]any{"removed": true, "user_id": in.UserID}, nil
		}},
	}
}

func describeWorkspace(w identityapi.Workspace, apiURL string) map[string]any {
	return map[string]any{
		"id": w.ID, "slug": w.Slug, "name": w.Name, "owner_user_id": w.OwnerUserID,
		"can_administer": w.CanAdminister, "logo_url": w.LogoURL,
		"mcp_url": strings.TrimRight(apiURL, "/") + "/mcp/w/" + w.Slug,
	}
}

// workspaceTools is tools/workspaces_toolset.py: it acts on no single
// workspace, so it is served on /mcp only and c carries no workspace.
// files is the workspace file store a logo is read from; nil refuses logo_path.
func workspaceTools(m identityapi.Members, files sandboxapi.Files, apiURL string) map[string]toolDef {
	return map[string]toolDef{
		"list": {title: "List workspaces", effect: effectRead, call: func(ctx context.Context, c authn.Caller, args json.RawMessage) (any, error) {
			in, err := decodeArgs[struct {
				Query *string `json:"query"`
			}](args)
			if err != nil {
				return nil, err
			}
			all, err := m.ListWorkspaces(ctx, c.Principal)
			if err != nil {
				return nil, err
			}
			needle := ""
			if in.Query != nil {
				needle = strings.ToLower(strings.TrimSpace(*in.Query))
			}
			out := []map[string]any{}
			for _, w := range all {
				if needle == "" || strings.Contains(strings.ToLower(w.Slug), needle) || strings.Contains(strings.ToLower(w.Name), needle) {
					out = append(out, describeWorkspace(w, apiURL))
				}
			}
			return out, nil
		}},
		"create": {title: "Create workspace", effect: effectWrite, call: func(ctx context.Context, c authn.Caller, args json.RawMessage) (any, error) {
			in, err := decodeArgs[struct {
				Name string `json:"name"`
			}](args)
			if err != nil {
				return nil, err
			}
			name := strings.TrimSpace(in.Name)
			if name == "" {
				return nil, &toolError{"Workspace name must not be empty"}
			}
			if len([]rune(name)) > 255 {
				return nil, &toolError{"Workspace name must be at most 255 characters"}
			}
			w, err := m.CreateWorkspace(ctx, c.Principal, name)
			if err != nil {
				return nil, err
			}
			return describeWorkspace(w, apiURL), nil
		}},
		"update": {title: "Update workspace settings", effect: effectWrite, idempotent: true, call: func(ctx context.Context, c authn.Caller, args json.RawMessage) (any, error) {
			in, err := decodeArgs[struct {
				Workspace string  `json:"workspace"`
				LogoPath  *string `json:"logo_path"`
				ClearLogo bool    `json:"clear_logo"`
			}](args)
			if err != nil {
				return nil, err
			}
			switch {
			case in.LogoPath != nil && in.ClearLogo:
				return nil, &toolError{"Pass either logo_path or clear_logo, not both"}
			case in.LogoPath == nil && !in.ClearLogo:
				return nil, &toolError{"Nothing to update: pass logo_path or clear_logo"}
			case in.LogoPath != nil && files == nil:
				return nil, &toolError{"logo_path is not served: the workspace file store is not wired"}
			}
			reachable, err := m.ListWorkspaces(ctx, c.Principal)
			if err != nil {
				return nil, err
			}
			for _, w := range reachable {
				if in.Workspace != w.Slug && in.Workspace != w.ID {
					continue
				}
				ws, err := scope.NewWorkspace(w.ID, w.Slug)
				if err != nil {
					return nil, err
				}
				p := c.Principal
				p.AccessibleWorkspaces = append(append([]string(nil), p.AccessibleWorkspaces...), w.ID)
				target := authn.Caller{Principal: p, Workspace: ws}
				var updated identityapi.Workspace
				if in.LogoPath == nil {
					updated, err = m.RemoveLogo(ctx, target)
				} else {
					updated, err = setLogoFromFile(ctx, m, files, target, *in.LogoPath)
				}
				if err != nil {
					return nil, err
				}
				return describeWorkspace(updated, apiURL), nil
			}
			return nil, &toolError{"No accessible workspace '" + in.Workspace + "'"}
		}},
	}
}

// setLogoFromFile reads the logo from the target workspace's files. The admin
// check is SetLogo's, as assert_workspace_admin precedes the read in Python.
func setLogoFromFile(ctx context.Context, m identityapi.Members, files sandboxapi.Files, c authn.Caller, logoPath string) (identityapi.Workspace, error) {
	head, ok, err := files.Head(ctx, c.Workspace, logoPath)
	if errors.Is(err, sandboxapi.ErrInvalidPath) {
		return identityapi.Workspace{}, &toolError{err.Error()}
	}
	if err != nil {
		return identityapi.Workspace{}, err
	}
	if !ok {
		return identityapi.Workspace{}, &toolError{"File not found"}
	}
	if head.Size > logoMaxBytes {
		return identityapi.Workspace{}, &toolError{fmt.Sprintf("Logo exceeds the %d-byte limit", logoMaxBytes)}
	}
	f, err := files.Get(ctx, c.Workspace, logoPath)
	if err != nil {
		return identityapi.Workspace{}, err
	}
	return m.SetLogo(ctx, c, f.Data)
}
