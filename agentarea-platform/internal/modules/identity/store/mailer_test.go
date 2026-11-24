package store

import (
	"strings"
	"testing"
	"time"

	kmail "github.com/agentarea/agentarea/agentarea-platform/internal/kernel/mail"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/identity/domain"
)

func TestDiscreteSettingsAsComposeSetsThem(t *testing.T) {
	s := SMTPSettings{Host: " mailpit ", Port: 1025, Username: "user", Password: "pass", Protocol: "smtp",
		DisableSTARTTLS: true, SkipSSLVerify: true, FromEmail: "noreply@x.test", FromName: "AgentArea"}
	m, err := NewSMTPMailer(s, nil)
	if err != nil || m == nil {
		t.Fatal(m, err)
	}
	srv := m.Server
	if srv.Host != "mailpit" || srv.Port != 1025 || srv.Username != "user" || srv.ImplicitTLS || srv.StartTLS != kmail.StartTLSNever ||
		srv.TLS == nil || !srv.TLS.InsecureSkipVerify || m.From != `"AgentArea" <noreply@x.test>` || m.Address != "noreply@x.test" {
		t.Fatalf("%+v %q", srv, m.From)
	}
	s.Protocol, s.DisableSTARTTLS, s.SkipSSLVerify, s.FromName = "smtps", false, false, ""
	m, _ = NewSMTPMailer(s, nil)
	if !m.Server.ImplicitTLS || m.Server.TLS != nil || m.From != "noreply@x.test" {
		t.Fatalf("%+v %q", m.Server, m.From)
	}
}

func TestConnectionURIWinsAsTheChartSetsIt(t *testing.T) {
	s := SMTPSettings{Host: "ignored", ConnectionURI: "smtp://u%40x:p%2Fw@smtp.example.test:587/?skip_ssl_verify=false", FromEmail: "a@x.test"}
	srv, ok, err := s.SMTPServer()
	if err != nil || !ok || srv.Host != "smtp.example.test" || srv.Port != 587 || srv.Username != "u@x" || srv.Password != "p/w" ||
		srv.StartTLS != kmail.StartTLSRequired || srv.TLS != nil {
		t.Fatalf("%+v %v", srv, err)
	}
	for uri, port := range map[string]int{"smtps://h": 465, "smtp://h/?disable_starttls=true": 25} {
		srv, _, _ := SMTPSettings{ConnectionURI: uri}.SMTPServer()
		if srv.Port != port {
			t.Errorf("%s: %d", uri, srv.Port)
		}
	}
	if srv, _, _ := (SMTPSettings{ConnectionURI: "smtp://h/?disable_starttls=true"}).SMTPServer(); srv.StartTLS != kmail.StartTLSNever {
		t.Fatal("disable_starttls ignored")
	}
}

func TestNoServerIsNoMailAndAServerNeedsASender(t *testing.T) {
	if m, err := NewSMTPMailer(SMTPSettings{FromEmail: "a@x.test"}, nil); m != nil || err != nil {
		t.Fatal(m, err)
	}
	if _, err := NewSMTPMailer(SMTPSettings{Host: "h"}, nil); err == nil {
		t.Fatal("a server without SMTP_FROM_EMAIL passed")
	}
	if _, err := NewSMTPMailer(SMTPSettings{ConnectionURI: "smtp:///nohost", FromEmail: "a@x.test"}, nil); err == nil {
		t.Fatal("a URI without a host passed")
	}
}

func TestBuildEmailIsTextWithAnHTMLAlternative(t *testing.T) {
	raw, err := BuildEmail("AgentArea <a@x.test>", domain.Email{To: "b@y.test", Subject: "Invité\nnow", TextBody: "line1\nline2", HTMLBody: "<p>hi</p>"},
		time.Date(2026, 11, 17, 10, 0, 0, 0, time.UTC))
	if err != nil {
		t.Fatal(err)
	}
	msg := string(raw)
	for _, want := range []string{"From: AgentArea <a@x.test>\r\n", "To: b@y.test\r\n", "Subject: =?utf-8?q?Invit=C3=A9_now?=\r\n",
		"Date: Tue, 17 Nov 2026 10:00:00 +0000\r\n", "multipart/alternative", "text/plain", "line1\r\nline2", "text/html", "<p>hi</p>"} {
		if !strings.Contains(msg, want) {
			t.Errorf("missing %q in\n%s", want, msg)
		}
	}
	if _, err := BuildEmail("a@x.test", domain.Email{To: "b@y.test\r\nBcc: c@z.test"}, time.Now()); err == nil {
		t.Fatal("a header injection passed")
	}
}
