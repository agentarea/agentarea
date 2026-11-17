// Package mail sends one message over one SMTP session: dial, TLS (implicit or
// STARTTLS), AUTH PLAIN, then MAIL, RCPT and DATA. The reply channel's email
// sender and the platform's own transactional mail both send through it.
package mail

import (
	"context"
	"crypto/tls"
	"errors"
	"fmt"
	"net"
	"net/smtp"
	"strconv"
)

// StartTLS is whether a session without implicit TLS upgrades with STARTTLS.
type StartTLS int

const (
	// StartTLSIfOffered upgrades when the server offers STARTTLS.
	StartTLSIfOffered StartTLS = iota
	// StartTLSRequired upgrades, and fails when the server does not offer it.
	StartTLSRequired
	// StartTLSNever stays in cleartext.
	StartTLSNever
)

// Server is one SMTP server and how to talk to it.
type Server struct {
	Host string
	Port int
	// Username empty sends no AUTH.
	Username string
	Password string
	// ImplicitTLS speaks TLS from the first byte (smtps); StartTLS is then ignored.
	ImplicitTLS bool
	StartTLS    StartTLS
	// TLS is the client TLS configuration; nil verifies against the system roots.
	TLS *tls.Config
}

// Dialer opens the TCP connection to the server.
type Dialer interface {
	DialContext(ctx context.Context, network, address string) (net.Conn, error)
}

// Stage is the step of a session a send failed at.
type Stage string

const (
	StageDial     Stage = "dial"
	StageGreeting Stage = "greeting"
	StageStartTLS Stage = "starttls"
	StageAuth     Stage = "auth"
	StageSend     Stage = "send"
	StageQuit     Stage = "quit"
)

// Error is a failed send and the stage it failed at.
type Error struct {
	Stage Stage
	Err   error
}

func (e *Error) Error() string { return fmt.Sprintf("smtp %s: %v", e.Stage, e.Err) }

func (e *Error) Unwrap() error { return e.Err }

func failed(stage Stage, err error) error { return &Error{Stage: stage, Err: err} }

// Send delivers raw, a complete RFC 5322 message, from from to to. ctx bounds
// the whole session.
func Send(ctx context.Context, d Dialer, s Server, from, to string, raw []byte) error {
	conn, err := d.DialContext(ctx, "tcp", net.JoinHostPort(s.Host, strconv.Itoa(s.Port)))
	if err != nil {
		return failed(StageDial, err)
	}
	defer func() { _ = conn.Close() }()
	if dl, ok := ctx.Deadline(); ok {
		_ = conn.SetDeadline(dl)
	}
	cfg := &tls.Config{ServerName: s.Host, MinVersion: tls.VersionTLS12}
	if s.TLS != nil {
		cfg = s.TLS.Clone()
		cfg.ServerName = s.Host
	}
	if s.ImplicitTLS {
		conn = tls.Client(conn, cfg)
	}
	c, err := smtp.NewClient(conn, s.Host)
	if err != nil {
		return failed(StageGreeting, err)
	}
	defer func() { _ = c.Close() }()
	if !s.ImplicitTLS && s.StartTLS != StartTLSNever {
		offered, _ := c.Extension("STARTTLS")
		switch {
		case offered:
			if err := c.StartTLS(cfg); err != nil {
				return failed(StageStartTLS, err)
			}
		case s.StartTLS == StartTLSRequired:
			return failed(StageStartTLS, errors.New("the server does not offer STARTTLS"))
		}
	}
	if s.Username != "" {
		if err := c.Auth(plainAuth{user: s.Username, password: s.Password}); err != nil {
			return failed(StageAuth, err)
		}
	}
	if err := c.Mail(from); err != nil {
		return failed(StageSend, err)
	}
	if err := c.Rcpt(to); err != nil {
		return failed(StageSend, err)
	}
	w, err := c.Data()
	if err != nil {
		return failed(StageSend, err)
	}
	if _, err := w.Write(raw); err != nil {
		return failed(StageSend, err)
	}
	if err := w.Close(); err != nil {
		return failed(StageSend, err)
	}
	if err := c.Quit(); err != nil {
		return failed(StageQuit, err)
	}
	return nil
}

// plainAuth is AUTH PLAIN on any connection, as aiosmtplib logs in: net/smtp's PlainAuth refuses
// a cleartext connection to anything but localhost.
type plainAuth struct{ user, password string }

func (a plainAuth) Start(*smtp.ServerInfo) (string, []byte, error) {
	return "PLAIN", []byte("\x00" + a.user + "\x00" + a.password), nil
}

func (a plainAuth) Next(_ []byte, more bool) ([]byte, error) {
	if more {
		return nil, errors.New("unexpected server challenge")
	}
	return nil, nil
}
