package service

import (
	"context"
	"html"
	"net/url"
	"strings"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/identity/domain"
)

// Mailer sends the platform's own mail (infrastructure/email.py SmtpMailer); nil when the
// deployment configures none, and an addressed invitation is then link-only.
type Mailer interface {
	Send(ctx context.Context, e domain.Email) error
}

// InvitationURL is where an invitation is accepted: {app}/invite?token=<token>.
func InvitationURL(appURL, token string) string {
	return strings.TrimRight(appURL, "/") + "/invite?token=" + url.QueryEscape(token)
}

// InvitationEmail is build_invitation_email.
func InvitationEmail(recipient, inviteURL, workspaceName string) domain.Email {
	name, link := html.EscapeString(workspaceName), html.EscapeString(inviteURL)
	return domain.Email{
		To:      recipient,
		Subject: "You have been invited to " + workspaceName + " on AgentArea",
		TextBody: "You have been invited to join " + workspaceName + " on AgentArea.\n\n" +
			"Open this link to accept:\n" + inviteURL + "\n\n" +
			"If you were not expecting this invitation, ignore this email — " +
			"the link only works for whoever opens it first, and it expires.",
		HTMLBody: "<p>You have been invited to join <strong>" + name + "</strong> on AgentArea.</p>" +
			`<p><a href="` + link + `">Accept the invitation</a></p>` +
			`<p style="color:#666;font-size:12px">Or paste this link into your browser:<br>` + link + "</p>" +
			`<p style="color:#666;font-size:12px">If you were not expecting this invitation, ignore this email ` +
			"— the link only works for whoever opens it first, and it expires.</p>",
	}
}

// deliverInvitation is deliver_invitation_for_workspace: best effort, every outcome reported,
// the token never logged.
func (s *Service) deliverInvitation(ctx context.Context, c authn.Caller, recipient *string, token string) domain.EmailDelivery {
	if recipient == nil || *recipient == "" {
		return domain.DeliveryNotRequested
	}
	if s.d.Mailer == nil {
		s.log.InfoContext(ctx, "No transactional mail configured; invitation is link-only", "recipient", *recipient)
		return domain.DeliveryNotConfigured
	}
	name := "a workspace"
	if ws, ok, err := s.workspaceForMail(ctx, c.Workspace.ID()); err != nil {
		s.log.ErrorContext(ctx, "Failed to read the workspace an invitation is mailed for", "recipient", *recipient, "error", err)
		return domain.DeliveryFailed
	} else if ok {
		name = ws.Name
	}
	if err := s.d.Mailer.Send(ctx, InvitationEmail(*recipient, InvitationURL(s.d.AppURL, token), name)); err != nil {
		s.log.ErrorContext(ctx, "Failed to send workspace invitation email", "recipient", *recipient, "error", err)
		return domain.DeliveryFailed
	}
	return domain.DeliverySent
}

func (s *Service) workspaceForMail(ctx context.Context, id string) (domain.Workspace, bool, error) {
	q, release, err := s.d.DB.Global().Read(ctx)
	if err != nil {
		return domain.Workspace{}, false, err
	}
	defer release()
	return s.d.Store.GetWorkspace(ctx, q, id)
}
