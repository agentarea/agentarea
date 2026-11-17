package service

import (
	"context"
	"errors"
	"strings"
	"testing"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/identity/domain"
)

type mailbox struct {
	sent []domain.Email
	fail error
}

func (m *mailbox) Send(_ context.Context, e domain.Email) error {
	if m.fail != nil {
		return m.fail
	}
	m.sent = append(m.sent, e)
	return nil
}

func mailed(t *testing.T, box *mailbox, name string) (*Service, authn.Caller) {
	t.Helper()
	svc, st, _ := setup("")
	svc.d.Mailer, svc.d.AppURL = box, "https://app.example.test/"
	ws, _ := scope.NewWorkspace(uuid.NewString(), "acme")
	if name != "" {
		st.workspaces[ws.ID()] = domain.Workspace{ID: ws.ID(), Name: name}
	}
	return svc, authn.Caller{Principal: authn.Principal{UserID: "owner"}, Workspace: ws}
}

func TestAddressedInvitationIsMailedWithItsLink(t *testing.T) {
	box := &mailbox{}
	svc, c := mailed(t, box, `Acme <R&D>`)
	got, err := svc.CreateInvitation(context.Background(), c, ptr("a@b.co"), nil)
	if err != nil || got.EmailDelivery != domain.DeliverySent || len(box.sent) != 1 {
		t.Fatalf("%+v %v %d", got, err, len(box.sent))
	}
	e := box.sent[0]
	link := "https://app.example.test/invite?token=" + got.Token
	if e.To != "a@b.co" || e.Subject != "You have been invited to Acme <R&D> on AgentArea" || !strings.Contains(e.TextBody, link) {
		t.Fatalf("%+v", e)
	}
	if !strings.Contains(e.HTMLBody, "<strong>Acme &lt;R&amp;D&gt;</strong>") || !strings.Contains(e.HTMLBody, `href="`+link+`"`) {
		t.Fatalf("html %s", e.HTMLBody)
	}
	if got, _ := svc.CreateInvitation(context.Background(), c, nil, nil); got.EmailDelivery != domain.DeliveryNotRequested || len(box.sent) != 1 {
		t.Fatalf("unaddressed invitation %+v", got)
	}
}

func TestInvitationOfAnUnknownWorkspaceNamesNone(t *testing.T) {
	box := &mailbox{}
	svc, c := mailed(t, box, "")
	if got, err := svc.CreateInvitation(context.Background(), c, ptr("a@b.co"), nil); err != nil || got.EmailDelivery != domain.DeliverySent {
		t.Fatalf("%+v %v", got, err)
	}
	if !strings.Contains(box.sent[0].Subject, "invited to a workspace on") {
		t.Fatal(box.sent[0].Subject)
	}
}

func TestMailThatFailsStillReturnsTheInvitation(t *testing.T) {
	svc, c := mailed(t, &mailbox{fail: errors.New("connection refused")}, "Acme")
	got, err := svc.CreateInvitation(context.Background(), c, ptr("a@b.co"), nil)
	if err != nil || got.EmailDelivery != domain.DeliveryFailed || got.Token == "" {
		t.Fatalf("%+v %v", got, err)
	}
}

func TestInvitationURLEscapesTheToken(t *testing.T) {
	if got := InvitationURL("http://x/", "a+b/c"); got != "http://x/invite?token=a%2Bb%2Fc" {
		t.Fatal(got)
	}
}
