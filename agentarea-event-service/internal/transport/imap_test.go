package transport

import (
	"context"
	"net"
	"strconv"
	"strings"
	"testing"
	"time"

	"github.com/emersion/go-imap/v2"
	"github.com/emersion/go-imap/v2/imapserver"
	"github.com/emersion/go-imap/v2/imapserver/imapmemserver"

	"github.com/agentarea/event-service/internal/catalog"
	"github.com/agentarea/event-service/internal/template"
)

const mailOne = "Message-ID: <one@x>\r\nFrom: Ann <ann@x>\r\nTo: bot@x\r\nSubject: Hello\r\n" +
	"Date: Wed, 15 Oct 2026 10:00:00 +0000\r\nContent-Type: text/plain; charset=utf-8\r\n\r\nfirst body\r\n"

const mailTwo = "Message-ID: <two@x>\r\nFrom: bob@x\r\nReply-To: team@x\r\nTo: bot@x\r\nSubject: Re: Hello\r\n" +
	"In-Reply-To: <one@x>\r\nReferences: <one@x>\r\n" +
	"MIME-Version: 1.0\r\nContent-Type: multipart/mixed; boundary=b\r\n\r\n" +
	"--b\r\nContent-Type: text/plain\r\n\r\nsecond body\r\n" +
	"--b\r\nContent-Type: text/csv\r\nContent-Disposition: attachment; filename=\"a.csv\"\r\n" +
	"Content-Transfer-Encoding: base64\r\n\r\nYSxiCg==\r\n--b--\r\n"

type mailServer struct {
	addr  string
	inbox *imapmemserver.User
}

func startMailServer(t *testing.T) *mailServer {
	t.Helper()
	mem := imapmemserver.New()
	user := imapmemserver.NewUser("bot", "pw")
	if err := user.Create("INBOX", nil); err != nil {
		t.Fatalf("create INBOX: %v", err)
	}
	mem.AddUser(user)
	server := imapserver.New(&imapserver.Options{
		NewSession: func(*imapserver.Conn) (imapserver.Session, *imapserver.GreetingData, error) {
			return mem.NewSession(), nil, nil
		},
		Caps:         imap.CapSet{imap.CapIMAP4rev1: {}, imap.CapIMAP4rev2: {}},
		InsecureAuth: true,
	})
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatalf("listen: %v", err)
	}
	go func() { _ = server.Serve(listener) }()
	t.Cleanup(func() { _ = server.Close() })
	return &mailServer{addr: listener.Addr().String(), inbox: user}
}

func (m *mailServer) deliver(t *testing.T, raw string) {
	t.Helper()
	if _, err := m.inbox.Append("INBOX", literal(raw), &imap.AppendOptions{Time: time.Now()}); err != nil {
		t.Fatalf("append: %v", err)
	}
}

type literalReader struct {
	*strings.Reader
	size int64
}

func (l literalReader) Size() int64 { return l.size }

func literal(s string) imap.LiteralReader {
	return literalReader{Reader: strings.NewReader(s), size: int64(len(s))}
}

func (m *mailServer) fetch(t *testing.T, cursor string) Result {
	t.Helper()
	host, port, _ := net.SplitHostPort(m.addr)
	tr, _ := NewSet(openPolicy(t), nil).Get(IMAP)
	res, err := tr.Fetch(context.Background(), Fetch{
		Poll: catalog.Poll{Transport: IMAP, IMAP: &catalog.IMAP{
			Host: "{config.host}", Port: "{config.port}", UseSSL: "{config.use_ssl}", Mailbox: "{config.mailbox}",
			Username: "{config.username}", Password: "{credentials.password}",
		}},
		Values: template.Values{
			Config:      map[string]any{"host": host, "port": port, "use_ssl": "plain", "username": "bot"},
			Credentials: map[string]string{"password": "pw"},
			Cursor:      cursor,
		},
	})
	if err != nil {
		t.Fatalf("Fetch: %v", err)
	}
	return res
}

func TestIMAPStartsAtThePresentThenReadsNewMail(t *testing.T) {
	m := startMailServer(t)
	m.deliver(t, mailOne)

	first := m.fetch(t, "")
	if len(first.Items) != 0 || !strings.HasSuffix(first.Cursor, ":1") {
		t.Fatalf("first poll = %+v", first)
	}

	m.deliver(t, mailTwo)
	second := m.fetch(t, first.Cursor)
	if len(second.Items) != 1 || !strings.HasSuffix(second.Cursor, ":2") {
		t.Fatalf("second poll = %+v", second)
	}
	item := second.Items[0].(map[string]any)
	if item["message_id"] != "two@x" || item["in_reply_to"] != "one@x" || item["subject"] != "Re: Hello" ||
		item["reply_to"] != "team@x" || item["from"] != "bob@x" {
		t.Fatalf("item = %v", item)
	}
	if !strings.Contains(item["text"].(string), "second body") {
		t.Fatalf("text = %q", item["text"])
	}
	attachments := item["attachments"].([]any)
	if len(attachments) != 1 || attachments[0].(map[string]any)["name"] != "a.csv" ||
		attachments[0].(map[string]any)["content_base64"] != "YSxiCg==" {
		t.Fatalf("attachments = %v", attachments)
	}

	again := m.fetch(t, second.Cursor)
	if len(again.Items) != 0 {
		t.Fatalf("read a message twice: %+v", again)
	}
}

func TestARenumberedMailboxIsAGap(t *testing.T) {
	m := startMailServer(t)
	m.deliver(t, mailOne)
	first := m.fetch(t, "")
	validity, _, _ := ParseIMAPCursor(first.Cursor)

	res := m.fetch(t, strconv.FormatUint(uint64(validity+1), 10)+":0")
	if res.Gap == "" || res.Cursor != first.Cursor {
		t.Fatalf("result = %+v", res)
	}
}

func TestIMAPCursorRoundTrips(t *testing.T) {
	v, l, err := ParseIMAPCursor(FormatIMAPCursor(7, 42))
	if err != nil || v != 7 || l != 42 {
		t.Fatalf("got %d %d %v", v, l, err)
	}
	if _, _, err := ParseIMAPCursor("garbage"); err == nil {
		t.Fatal("parsed a garbage cursor")
	}
}

func TestRenderMailboxDefaults(t *testing.T) {
	m, err := RenderMailbox(catalog.IMAP{
		Host: "{config.host}", Port: "{config.port}", UseSSL: "{config.use_ssl}", Mailbox: "{config.mailbox}",
		Username: "{config.username}", Password: "{credentials.password}",
	}, template.Values{Config: map[string]any{"host": "imap.example.com", "username": "u"}, Credentials: map[string]string{"password": "p"}})
	if err != nil {
		t.Fatalf("RenderMailbox: %v", err)
	}
	if m.Port != 993 || m.Security != "tls" || m.Name != "INBOX" {
		t.Fatalf("mailbox = %+v", m)
	}
	if _, err := RenderMailbox(catalog.IMAP{Host: "{config.host}", Username: "u", Password: "p", UseSSL: "maybe"},
		template.Values{Config: map[string]any{"host": "h"}}); err == nil {
		t.Fatal("accepted use_ssl=maybe")
	}
}
