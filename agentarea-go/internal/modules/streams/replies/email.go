package replies

import (
	"bytes"
	"context"
	"crypto/tls"
	"errors"
	"fmt"
	"mime"
	"mime/multipart"
	"net"
	"net/mail"
	"net/smtp"
	"net/textproto"
	"regexp"
	"strconv"
	"strings"
	"time"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/netguard"
)

const smtpTimeout = 30 * time.Second

// Email sends a task's events as HTML mail to whoever wrote the mail that started it, threaded
// under it. The address's target names whom to answer (to), the subject, message_id and
// references; the source's credentials the SMTP host, port, username, password, from_address
// and use_tls.
type Email struct {
	Credentials Credentials
	// Dialer connects to the member's SMTP host (netguard member_connection).
	Dialer netguard.Dialer
	// TLS is the client TLS configuration; nil verifies against the system roots.
	TLS *tls.Config
}

func (Email) Format(s Send) (string, error) {
	d := s.Event.Data
	switch s.Event.Type {
	case "task.completed":
		return htmlWrap("Task Complete", "<p>"+escapeHTML(pyStr(firstTruthy(d, "final_response", "result"), "Task completed."))+"</p>", "success"), nil
	case "task.failed":
		return htmlWrap("Task Failed", "<p><strong>Error:</strong> "+escapeHTML(pyStr(get(d, "error"), "Unknown error"))+"</p>", "error"), nil
	case "task.cancelled":
		return htmlWrap("Task Cancelled", "<p>The task was cancelled.</p>", "warning"), nil
	case "approval.requested":
		return htmlWrap("Action Required", "<p><strong>Your input is needed:</strong></p><blockquote>"+
			escapeHTML(pyStr(get(d, "question"), "Approval needed"))+"</blockquote><p>Please respond via the AgentArea dashboard.</p>", "warning"), nil
	case "approval.decided":
		switch d["approved"] {
		case true:
			return htmlWrap("Approved", "<p>The action was approved. The agent is continuing.</p>", "success"), nil
		case false:
			reason := ""
			if c := d["comment"]; truthy(c) {
				reason = "<p><strong>Reason:</strong> " + escapeHTML(pyStr(c, "")) + "</p>"
			}
			return htmlWrap("Action Denied", "<p>The action was denied and did not run.</p>"+reason, "error"), nil
		}
		return htmlWrap("Approval Resolved", "<p>The approval request was resolved.</p>", "info"), nil
	}
	return htmlWrap("Agent Update: "+s.Event.Type, "<p>"+escapeHTML(s.Event.Type)+"</p>", "info"), nil
}

func (e Email) Send(ctx context.Context, s Send, message string) error {
	target, _ := s.Target.Config["target"].(map[string]any)
	to := ReplyAddress(target["to"])
	if to == "" {
		return fatalf("email channel: %v has no address to reply to", target["to"])
	}
	creds, err := s.credentials(ctx, e.Credentials)
	if err != nil {
		return err
	}
	from := creds["from_address"]
	if from == "" {
		from = "agent@agentarea.local"
	}
	host := creds["smtp_host"]
	if host == "" {
		return fatalf("email channel: SMTP credentials have no smtp_host")
	}
	port := 25
	if p := creds["smtp_port"]; p != "" {
		if port, err = strconv.Atoi(strings.TrimSpace(p)); err != nil || port <= 0 || port > 65535 {
			return fatalf("email channel: smtp_port %q is not a port", p)
		}
	}
	messageID, _ := target["message_id"].(string)
	raw, err := BuildReply(from, to, ReplySubject(target["subject"]), messageID, ReplyReferences(target["references"], messageID), message)
	if err != nil {
		return err
	}
	ctx, cancel := context.WithTimeout(ctx, smtpTimeout)
	defer cancel()
	conn, err := e.Dialer.DialContext(ctx, "tcp", net.JoinHostPort(host, strconv.Itoa(port)))
	if err != nil {
		if errors.Is(err, netguard.ErrUnsafe) {
			return fatalf("email channel: SMTP host refused: %v", err)
		}
		return fmt.Errorf("email channel: SMTP transport error: %w", err)
	}
	defer func() { _ = conn.Close() }()
	if dl, ok := ctx.Deadline(); ok {
		_ = conn.SetDeadline(dl)
	}
	cfg := &tls.Config{ServerName: host, MinVersion: tls.VersionTLS12}
	if e.TLS != nil {
		cfg = e.TLS.Clone()
		cfg.ServerName = host
	}
	if useTLS, _ := strconv.ParseBool(creds["use_tls"]); useTLS {
		conn = tls.Client(conn, cfg)
	}
	c, err := smtp.NewClient(conn, host)
	if err != nil {
		return fmt.Errorf("email channel: SMTP transport error: %w", err)
	}
	defer func() { _ = c.Close() }()
	if _, isTLS := conn.(*tls.Conn); !isTLS {
		if ok, _ := c.Extension("STARTTLS"); ok {
			if err := c.StartTLS(cfg); err != nil {
				return fmt.Errorf("email channel: STARTTLS failed: %w", err)
			}
		}
	}
	if user := creds["username"]; user != "" {
		if err := c.Auth(plainAuth{user: user, password: creds["password"]}); err != nil {
			var pe *textproto.Error
			if errors.As(err, &pe) && pe.Code == 535 {
				return fatalf("email channel: SMTP authentication failed: %v", err)
			}
			return smtpError(err)
		}
	}
	if err := c.Mail(from); err != nil {
		return smtpError(err)
	}
	if err := c.Rcpt(to); err != nil {
		return smtpError(err)
	}
	w, err := c.Data()
	if err != nil {
		return smtpError(err)
	}
	if _, err := w.Write(raw); err != nil {
		return smtpError(err)
	}
	if err := w.Close(); err != nil {
		return smtpError(err)
	}
	return c.Quit()
}

func smtpError(err error) error { return fmt.Errorf("email channel: SMTP error: %w", err) }

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

// BuildReply is the multipart/alternative reply: a plain-text part and the HTML message.
func BuildReply(from, to, subject, inReplyTo string, references []string, message string) ([]byte, error) {
	for name, v := range map[string]string{"From": from, "To": to, "In-Reply-To": inReplyTo} {
		if strings.ContainsAny(v, "\r\n") {
			return nil, fatalf("email channel: invalid header: %s has a line break", name)
		}
	}
	var body bytes.Buffer
	mw := multipart.NewWriter(&body)
	for _, part := range []struct{ kind, text string }{{"plain", htmlToPlain(message)}, {"html", message}} {
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
	var b bytes.Buffer
	header := func(k, v string) { b.WriteString(k + ": " + v + "\r\n") }
	header("Subject", mime.QEncoding.Encode("utf-8", subject))
	header("From", from)
	header("To", to)
	if inReplyTo != "" {
		header("In-Reply-To", inReplyTo)
	}
	if len(references) > 0 {
		refs := strings.Join(references, " ")
		if strings.ContainsAny(refs, "\r\n") {
			return nil, fatalf("email channel: invalid header: References has a line break")
		}
		header("References", refs)
	}
	header("MIME-Version", "1.0")
	header("Content-Type", `multipart/alternative; boundary="`+mw.Boundary()+`"`)
	b.WriteString("\r\n")
	b.Write(body.Bytes())
	return b.Bytes(), nil
}

func crlf(s string) string {
	return strings.ReplaceAll(strings.ReplaceAll(s, "\r\n", "\n"), "\n", "\r\n")
}

// ReplySubject is reply_subject: one line, "Re: " in front unless it is there.
func ReplySubject(v any) string {
	subject, _ := v.(string)
	subject = strings.Join(strings.Fields(subject), " ")
	if subject == "" {
		return "Re: (no subject)"
	}
	if strings.HasPrefix(strings.ToLower(subject), "re:") {
		return subject
	}
	return "Re: " + subject
}

// ReplyAddress is reply_address: the first address in the sender's Reply-To or From.
func ReplyAddress(v any) string {
	s, _ := v.(string)
	if s == "" {
		return ""
	}
	if list, err := mail.ParseAddressList(s); err == nil {
		for _, a := range list {
			if strings.Contains(a.Address, "@") {
				return a.Address
			}
		}
		return ""
	}
	if a, err := mail.ParseAddress(s); err == nil && strings.Contains(a.Address, "@") {
		return a.Address
	}
	return ""
}

// ReplyReferences is reply_references: the whole chain plus the mail answered.
func ReplyReferences(v any, messageID string) []string {
	var chain []string
	switch x := v.(type) {
	case string:
		chain = strings.Fields(x)
	case []any:
		for _, r := range x {
			chain = append(chain, fmt.Sprint(r))
		}
	}
	if messageID != "" {
		for _, r := range chain {
			if r == messageID {
				return chain
			}
		}
		chain = append(chain, messageID)
	}
	return chain
}

func escapeHTML(s string) string {
	return strings.NewReplacer("&", "&amp;", "<", "&lt;", ">", "&gt;").Replace(s)
}

func htmlWrap(subject, body, status string) string {
	color := map[string]string{"success": "#22c55e", "error": "#ef4444", "warning": "#f59e0b", "info": "#3b82f6"}[status]
	if color == "" {
		color = "#3b82f6"
	}
	return `<div style="font-family: -apple-system, sans-serif; max-width: 600px; margin: 0 auto;">
  <div style="border-left: 4px solid ` + color + `; padding: 12px 16px; margin: 16px 0;">
    <h3 style="margin: 0 0 8px 0; color: #1f2937;">` + escapeHTML(subject) + `</h3>
    ` + body + `
  </div>
  <p style="color: #9ca3af; font-size: 12px;">Sent by AgentArea</p>
</div>`
}

var (
	brRE  = regexp.MustCompile(`<br\s*/?>`)
	tagRE = regexp.MustCompile(`<[^>]+>`)
)

func htmlToPlain(s string) string {
	s = brRE.ReplaceAllString(s, "\n")
	s = tagRE.ReplaceAllString(s, "")
	return strings.TrimSpace(strings.NewReplacer("&amp;", "&", "&lt;", "<", "&gt;", ">").Replace(s))
}

var _ Sender = Email{}
