package store

import (
	"bytes"
	"context"
	"crypto/tls"
	"errors"
	"fmt"
	"mime"
	"mime/multipart"
	"net/mail"
	"net/textproto"
	"net/url"
	"strconv"
	"strings"
	"time"

	kmail "github.com/agentarea/agentarea/agentarea-platform/internal/kernel/mail"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/identity/domain"
)

// smtpTimeout bounds one send, as aiosmtplib's default timeout did.
const smtpTimeout = 60 * time.Second

// SMTPSettings are the deployment's SMTP_* values (config/email.py EmailSettings): the
// discrete ones compose sets, or the one URI the chart shares with Kratos' courier.
type SMTPSettings struct {
	Host            string
	Port            int
	Username        string
	Password        string
	Protocol        string
	DisableSTARTTLS bool
	SkipSSLVerify   bool
	ConnectionURI   string
	FromEmail       string
	FromName        string
}

// SMTPServer is the connection the settings describe; false when they name no server.
func (s SMTPSettings) SMTPServer() (kmail.Server, bool, error) {
	if uri := strings.TrimSpace(s.ConnectionURI); uri != "" {
		return serverFromURI(uri)
	}
	host := strings.TrimSpace(s.Host)
	if host == "" {
		return kmail.Server{}, false, nil
	}
	implicit := strings.ToLower(strings.TrimSpace(s.Protocol)) == "smtps"
	return server(host, s.Port, s.Username, s.Password, implicit, !s.DisableSTARTTLS, s.SkipSSLVerify), true, nil
}

func serverFromURI(uri string) (kmail.Server, bool, error) {
	u, err := url.Parse(uri)
	if err != nil {
		return kmail.Server{}, false, fmt.Errorf("SMTP_CONNECTION_URI: %w", err)
	}
	if u.Hostname() == "" {
		return kmail.Server{}, false, errors.New("SMTP_CONNECTION_URI names no host")
	}
	implicit := strings.EqualFold(u.Scheme, "smtps")
	port := 25
	if implicit {
		port = 465
	}
	if p := u.Port(); p != "" {
		if port, err = strconv.Atoi(p); err != nil || port < 1 || port > 65535 {
			return kmail.Server{}, false, fmt.Errorf("SMTP_CONNECTION_URI: port %q is not a port", p)
		}
	}
	password, _ := u.User.Password()
	q := u.Query()
	return server(u.Hostname(), port, u.User.Username(), password, implicit, !isTrue(q.Get("disable_starttls")), isTrue(q.Get("skip_ssl_verify"))), true, nil
}

func isTrue(v string) bool {
	switch strings.ToLower(v) {
	case "1", "true", "yes":
		return true
	}
	return false
}

func server(host string, port int, user, password string, implicit, startTLS, skipVerify bool) kmail.Server {
	s := kmail.Server{Host: host, Port: port, Username: user, Password: password, ImplicitTLS: implicit, StartTLS: kmail.StartTLSNever}
	if startTLS {
		s.StartTLS = kmail.StartTLSRequired
	}
	if skipVerify {
		s.TLS = &tls.Config{InsecureSkipVerify: true, MinVersion: tls.VersionTLS12} //nolint:gosec // SMTP_SKIP_SSL_VERIFY / skip_ssl_verify asked for it
	}
	return s
}

// SMTPMailer is SmtpMailer: one message per SMTP session, from the deployment's sender.
type SMTPMailer struct {
	Server kmail.Server
	// From is the From header: "Name <address>", or the bare address without a name.
	From    string
	Address string
	Dialer  kmail.Dialer
	Now     func() time.Time
}

// NewSMTPMailer is build_mailer: nil when the settings name no server, an error when they name
// one Go cannot read or one without a sender address.
func NewSMTPMailer(s SMTPSettings, d kmail.Dialer) (*SMTPMailer, error) {
	srv, ok, err := s.SMTPServer()
	if err != nil || !ok {
		return nil, err
	}
	address := strings.TrimSpace(s.FromEmail)
	if address == "" {
		return nil, errors.New("SMTP_FROM_EMAIL is required when SMTP_HOST or SMTP_CONNECTION_URI is set")
	}
	if _, err := mail.ParseAddress(address); err != nil {
		return nil, fmt.Errorf("SMTP_FROM_EMAIL: %w", err)
	}
	from := address
	if name := strings.TrimSpace(s.FromName); name != "" {
		from = (&mail.Address{Name: name, Address: address}).String()
	}
	return &SMTPMailer{Server: srv, From: from, Address: address, Dialer: d, Now: time.Now}, nil
}

// Send delivers e; the error is the transport's.
func (m *SMTPMailer) Send(ctx context.Context, e domain.Email) error {
	raw, err := BuildEmail(m.From, e, m.Now())
	if err != nil {
		return err
	}
	ctx, cancel := context.WithTimeout(ctx, smtpTimeout)
	defer cancel()
	return kmail.Send(ctx, m.Dialer, m.Server, m.Address, e.To, raw)
}

// BuildEmail is the message as MIME: the text part, then the HTML alternative when there is one.
func BuildEmail(from string, e domain.Email, now time.Time) ([]byte, error) {
	if strings.ContainsAny(e.To, "\r\n") || strings.ContainsAny(from, "\r\n") {
		return nil, errors.New("invalid header: an address has a line break")
	}
	var body bytes.Buffer
	contentType := `text/plain; charset="utf-8"`
	if e.HTMLBody == "" {
		body.WriteString(crlf(e.TextBody))
	} else {
		mw := multipart.NewWriter(&body)
		for _, part := range []struct{ kind, text string }{{"plain", e.TextBody}, {"html", e.HTMLBody}} {
			pw, err := mw.CreatePart(textproto.MIMEHeader{
				"Content-Type": {"text/" + part.kind + `; charset="utf-8"`}, "Content-Transfer-Encoding": {"8bit"},
			})
			if err != nil {
				return nil, err
			}
			if _, err := pw.Write([]byte(crlf(part.text))); err != nil {
				return nil, err
			}
		}
		if err := mw.Close(); err != nil {
			return nil, err
		}
		contentType = `multipart/alternative; boundary="` + mw.Boundary() + `"`
	}
	var b bytes.Buffer
	header := func(k, v string) { b.WriteString(k + ": " + v + "\r\n") }
	header("From", from)
	header("To", e.To)
	header("Subject", mime.QEncoding.Encode("utf-8", strings.Join(strings.Fields(e.Subject), " ")))
	header("Date", now.Format(time.RFC1123Z))
	header("MIME-Version", "1.0")
	header("Content-Type", contentType)
	if e.HTMLBody == "" {
		header("Content-Transfer-Encoding", "8bit")
	}
	b.WriteString("\r\n")
	b.Write(body.Bytes())
	return b.Bytes(), nil
}

func crlf(s string) string {
	return strings.ReplaceAll(strings.ReplaceAll(s, "\r\n", "\n"), "\n", "\r\n")
}
