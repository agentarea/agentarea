package transport

import (
	"context"
	"crypto/tls"
	"errors"
	"fmt"
	"net"
	"sort"
	"strconv"
	"strings"
	"time"

	"github.com/emersion/go-imap/v2"
	"github.com/emersion/go-imap/v2/imapclient"

	"github.com/agentarea/event-service/internal/catalog"
	"github.com/agentarea/event-service/internal/egress"
	"github.com/agentarea/event-service/internal/template"
)

// IMAPTransport reads new messages of a mailbox by UID. The cursor is
// "<uidvalidity>:<last uid>". The first poll records the mailbox's present; a
// changed UIDVALIDITY renumbers the mailbox, so it is a gap and a new start.
type IMAPTransport struct {
	policy egress.Policy
}

const (
	// Messages per poll; the rest come on the next one.
	imapBatch   = 25
	imapTimeout = 60 * time.Second
)

// Mailbox is a poll block's imap templates, rendered.
type Mailbox struct {
	Host     string
	Port     int
	Security string // tls | starttls | plain
	Name     string
	Username string
	Password string
}

// Fetch logs in, reads the messages after the cursor and logs out.
func (t *IMAPTransport) Fetch(ctx context.Context, f Fetch) (Result, error) {
	if f.Poll.IMAP == nil {
		return Result{}, fmt.Errorf("imap poll has no imap block")
	}
	mailbox, err := RenderMailbox(*f.Poll.IMAP, f.Values)
	if err != nil {
		return Result{}, err
	}
	validity, last, err := ParseIMAPCursor(f.Values.Cursor)
	if err != nil {
		return Result{}, err
	}

	client, err := t.dial(mailbox)
	if err != nil {
		return Result{}, fmt.Errorf("imap %s: %w", mailbox.Host, err)
	}
	defer client.Close()
	stop := context.AfterFunc(ctx, func() { _ = client.Close() })
	defer stop()

	if err := client.Login(mailbox.Username, mailbox.Password).Wait(); err != nil {
		return Result{}, fmt.Errorf("imap %s: login: %w", mailbox.Host, err)
	}
	selected, err := client.Select(mailbox.Name, &imap.SelectOptions{ReadOnly: true}).Wait()
	if err != nil {
		return Result{}, fmt.Errorf("imap %s: select %s: %w", mailbox.Host, mailbox.Name, err)
	}

	newest, err := lastUID(client, selected)
	if err != nil {
		return Result{}, fmt.Errorf("imap %s: %w", mailbox.Host, err)
	}
	present := FormatIMAPCursor(selected.UIDValidity, newest)
	if f.Values.Cursor == "" {
		return Result{Cursor: present}, nil
	}
	if validity != selected.UIDValidity {
		return Result{
			Cursor: present,
			Gap:    fmt.Sprintf("mailbox %s was renumbered (UIDVALIDITY %d to %d); messages that arrived in between may be missing", mailbox.Name, validity, selected.UIDValidity),
		}, nil
	}
	if newest <= last {
		_ = client.Logout().Wait()
		return Result{}, nil
	}

	var after imap.UIDSet
	after.AddRange(imap.UID(last+1), 0)
	found, err := client.UIDSearch(&imap.SearchCriteria{UID: []imap.UIDSet{after}}, nil).Wait()
	if err != nil {
		return Result{}, fmt.Errorf("imap %s: search: %w", mailbox.Host, err)
	}
	var uids []imap.UID
	for _, uid := range found.AllUIDs() {
		if uint32(uid) > last {
			uids = append(uids, uid)
		}
	}
	sort.Slice(uids, func(i, j int) bool { return uids[i] < uids[j] })
	if len(uids) > imapBatch {
		uids = uids[:imapBatch]
	}
	if len(uids) == 0 {
		return Result{Cursor: present}, nil
	}

	messages, err := client.Fetch(imap.UIDSetNum(uids...), &imap.FetchOptions{
		UID:         true,
		BodySection: []*imap.FetchItemBodySection{{Peek: true}},
	}).Collect()
	if err != nil {
		return Result{}, fmt.Errorf("imap %s: fetch: %w", mailbox.Host, err)
	}
	sort.Slice(messages, func(i, j int) bool { return messages[i].UID < messages[j].UID })

	result := Result{}
	for _, msg := range messages {
		if uint32(msg.UID) <= last || len(msg.BodySection) == 0 {
			continue
		}
		item, err := ParseMessage(msg.BodySection[0].Bytes)
		if err != nil {
			return Result{}, fmt.Errorf("imap %s: message uid %d: %w", mailbox.Host, msg.UID, err)
		}
		result.Items = append(result.Items, item)
		last = uint32(msg.UID)
	}
	result.Cursor = FormatIMAPCursor(validity, last)
	_ = client.Logout().Wait()
	return result, nil
}

func (t *IMAPTransport) dial(m Mailbox) (*imapclient.Client, error) {
	options := &imapclient.Options{
		TLSConfig: &tls.Config{ServerName: m.Host, MinVersion: tls.VersionTLS12},
		Dialer:    t.policy.Dialer(true, m.Host),
	}
	address := net.JoinHostPort(m.Host, strconv.Itoa(m.Port))
	switch m.Security {
	case "tls":
		return imapclient.DialTLS(address, options)
	case "starttls":
		return imapclient.DialStartTLS(address, options)
	default:
		return imapclient.DialInsecure(address, options)
	}
}

// lastUID is the newest UID the mailbox has given out: UIDNEXT-1, or the UID
// of its last message when the server sends no UIDNEXT.
func lastUID(client *imapclient.Client, selected *imap.SelectData) (uint32, error) {
	if selected.UIDNext > 0 {
		return uint32(selected.UIDNext) - 1, nil
	}
	if selected.NumMessages == 0 {
		return 0, nil
	}
	msgs, err := client.Fetch(imap.SeqSetNum(selected.NumMessages), &imap.FetchOptions{UID: true}).Collect()
	if err != nil {
		return 0, fmt.Errorf("read the last message's uid: %w", err)
	}
	if len(msgs) == 0 {
		return 0, errors.New("the last message has no uid")
	}
	return uint32(msgs[0].UID), nil
}

// RenderMailbox fills the imap templates. host, username and password are
// required; port, use_ssl and mailbox default to 993 / TLS / INBOX when the
// template is empty or names a value the member left out.
func RenderMailbox(block catalog.IMAP, v template.Values) (Mailbox, error) {
	m := Mailbox{Name: "INBOX", Security: "tls"}
	var err error
	if m.Host, err = template.Render(block.Host, v); err != nil {
		return Mailbox{}, fmt.Errorf("imap host: %w", err)
	}
	if m.Username, err = template.Render(block.Username, v); err != nil {
		return Mailbox{}, fmt.Errorf("imap username: %w", err)
	}
	if m.Password, err = template.Render(block.Password, v); err != nil {
		return Mailbox{}, fmt.Errorf("imap password: %w", err)
	}
	if m.Host == "" || m.Username == "" {
		return Mailbox{}, fmt.Errorf("imap host and username are required")
	}
	if security, ok, err := optional(block.UseSSL, v); err != nil {
		return Mailbox{}, fmt.Errorf("imap use_ssl: %w", err)
	} else if ok {
		switch strings.ToLower(security) {
		case "true", "1", "tls", "ssl":
			m.Security = "tls"
		case "false", "0", "starttls":
			m.Security = "starttls"
		case "plain", "none":
			m.Security = "plain"
		default:
			return Mailbox{}, fmt.Errorf("imap use_ssl %q is not true, false, starttls or plain", security)
		}
	}
	m.Port = 993
	if m.Security != "tls" {
		m.Port = 143
	}
	if port, ok, err := optional(block.Port, v); err != nil {
		return Mailbox{}, fmt.Errorf("imap port: %w", err)
	} else if ok {
		if m.Port, err = strconv.Atoi(port); err != nil || m.Port <= 0 || m.Port > 65535 {
			return Mailbox{}, fmt.Errorf("imap port %q is not a port number", port)
		}
	}
	if name, ok, err := optional(block.Mailbox, v); err != nil {
		return Mailbox{}, fmt.Errorf("imap mailbox: %w", err)
	} else if ok {
		m.Name = name
	}
	return m, nil
}

func optional(tmpl string, v template.Values) (string, bool, error) {
	if tmpl == "" {
		return "", false, nil
	}
	value, err := template.Render(tmpl, v)
	if errors.Is(err, template.ErrMissing) {
		return "", false, nil
	}
	if err != nil {
		return "", false, err
	}
	value = strings.TrimSpace(value)
	return value, value != "", nil
}

// ParseIMAPCursor reads "<uidvalidity>:<last uid>"; "" is (0, 0).
func ParseIMAPCursor(cursor string) (validity, last uint32, err error) {
	if cursor == "" {
		return 0, 0, nil
	}
	v, l, ok := strings.Cut(cursor, ":")
	if !ok {
		return 0, 0, fmt.Errorf("imap cursor %q is not <uidvalidity>:<uid>", cursor)
	}
	pv, err1 := strconv.ParseUint(v, 10, 32)
	pl, err2 := strconv.ParseUint(l, 10, 32)
	if err1 != nil || err2 != nil {
		return 0, 0, fmt.Errorf("imap cursor %q is not <uidvalidity>:<uid>", cursor)
	}
	return uint32(pv), uint32(pl), nil
}

// FormatIMAPCursor writes the cursor ParseIMAPCursor reads.
func FormatIMAPCursor(validity, last uint32) string {
	return fmt.Sprintf("%d:%d", validity, last)
}
