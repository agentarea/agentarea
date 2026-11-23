package service_test

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net"
	"net/http"
	"strings"
	"sync"
	"testing"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/netguard"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	identityapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/identity/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/domain"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/service"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/store/storetest"
)

type botAPI struct {
	mu   sync.Mutex
	sent []string
}

func (b *botAPI) RoundTrip(r *http.Request) (*http.Response, error) {
	answer := `{"ok":true,"result":true}`
	switch {
	case strings.HasSuffix(r.URL.Path, "/getMe"):
		answer = `{"ok":true,"result":{"username":"door_bot"}}`
	case strings.HasSuffix(r.URL.Path, "/sendMessage"):
		var m struct {
			ChatID any    `json:"chat_id"`
			Text   string `json:"text"`
		}
		if err := json.NewDecoder(r.Body).Decode(&m); err != nil {
			return nil, err
		}
		if !strings.HasPrefix(r.URL.Path, "/botTOKEN/") {
			m.Text = "wrong bot: " + r.URL.Path
		}
		b.mu.Lock()
		b.sent = append(b.sent, m.Text)
		b.mu.Unlock()
	}
	return &http.Response{StatusCode: 200, Header: http.Header{}, Body: io.NopCloser(strings.NewReader(answer)), Request: r}, nil
}

func (b *botAPI) Transport(netguard.Destination) http.RoundTripper { return b }
func (b *botAPI) Dialer() netguard.Dialer                          { return &net.Dialer{} }

func (b *botAPI) take() []string {
	b.mu.Lock()
	defer b.mu.Unlock()
	out := b.sent
	b.sent = nil
	return out
}

type links struct {
	holders map[string]string
	codes   map[string]string
	pending map[string]string
	offers  []identityapi.Account
	linked  identityapi.Account
}

func (l *links) Offer(_ context.Context, a identityapi.Account, bot string) (string, error) {
	l.offers = append(l.offers, a)
	return fmt.Sprintf("OFFER%d-%s", len(l.offers), bot), nil
}

func (l *links) Holder(_ context.Context, _, id string) (string, bool, error) {
	u, ok := l.holders[id]
	return u, ok, nil
}

func (l *links) Redeem(_ context.Context, code, _, id string) (string, bool, error) {
	u, ok := l.codes[code]
	delete(l.codes, code)
	if ok {
		l.pending[id] = u
	}
	return u, ok, nil
}

func (l *links) Confirm(_ context.Context, a identityapi.Account) (string, bool, error) {
	id := a.ExternalID
	u, ok := l.pending[id]
	delete(l.pending, id)
	if !ok {
		return "", false, nil
	}
	if h, held := l.holders[id]; held && h != u {
		return "", false, identityapi.ErrAccountTaken
	}
	l.holders[id] = u
	l.linked = a
	return u, true, nil
}

func (l *links) Describe(context.Context, string) string { return "o***@example.com" }

type owners struct{ owner string }

func (o owners) Owner(context.Context, string) (string, bool, error) { return o.owner, true, nil }

type door struct {
	svc     *service.Service
	ws      scope.Workspace
	src     domain.Source
	bot     *botAPI
	links   *links
	graph   *storetest.Graph
	notices *storetest.Dedup
}

func newDoor(t *testing.T) door {
	t.Helper()
	pool := storetest.Pool(t)
	ws := storetest.Workspace(t, pool)
	ctx, _ := storetest.Caller(context.Background(), ws, "owner")
	secrets := storetest.NewSecrets()
	d := door{ws: ws, bot: &botAPI{}, graph: &storetest.Graph{}, notices: &storetest.Dedup{},
		links: &links{holders: map[string]string{}, codes: map[string]string{"CODE": "owner"}, pending: map[string]string{}}}
	d.graph.AllowAll = true
	d.svc = service.New(service.Deps{
		DB: storetest.DB{Pool: pool}, Graph: d.graph, SourceTypes: storetest.ShippedSourceTypes(t),
		Secrets: secrets, SecretCatalog: secrets.Catalog, Blob: &storetest.Blob{}, Bus: &storetest.Bus{},
		Dedup: &storetest.Dedup{}, Quota: &storetest.Quota{}, Out: d.bot, APIURL: "https://api.example.test",
		Links: d.links, Owners: owners{owner: "owner"}, Notices: d.notices, AppURL: "https://app.example.test/",
	})
	st, err := d.svc.CreateStream(ctx, "tg-"+uuid.NewString()[:8], "")
	if err != nil {
		t.Fatal(err)
	}
	d.src, _, err = d.svc.AddSource(ctx, st.ID, service.NewSource{SourceType: "telegram", Kind: "webhook",
		Credentials: map[string]service.Credential{"bot_token": value("TOKEN")}})
	if err != nil {
		t.Fatal(err)
	}
	d.bot.take()
	return d
}

func (d door) admit(t *testing.T, from int, chat, text string) (service.Admitted, string) {
	t.Helper()
	body := map[string]any{"message": map[string]any{
		"from": map[string]any{"id": from, "is_bot": false, "username": "alice", "first_name": "Alice", "last_name": "Liddell"},
		"chat": map[string]any{"id": from, "type": chat},
		"text": text,
	}}
	slug := "telegram"
	e := domain.Event{ID: uuid.NewString(), StreamID: d.src.StreamID, WorkspaceID: d.ws.ID(),
		SourceID: &d.src.ID, SourceType: &slug, Data: map[string]any{"body": body, "headers": map[string]any{}}}
	ctx := context.Background()
	dr, err := d.svc.EventAdmission(ctx, d.ws, e)
	if err != nil || dr == nil {
		t.Fatalf("door %+v %v", dr, err)
	}
	a, refused, err := d.svc.Admit(ctx, d.ws, domain.Trigger{ID: "trig", WorkspaceID: d.ws.ID(), AgentID: "agent"}, e, *dr)
	if err != nil {
		t.Fatal(err)
	}
	return a, refused
}

func TestATelegramSenderLinksFromInsideTheChatThenReachesTheAgent(t *testing.T) {
	d := newDoor(t)
	if _, refused := d.admit(t, 42, "private", "hello"); refused != "the sender has not linked their Telegram account" {
		t.Fatalf("refused %q", refused)
	}
	if sent := d.bot.take(); len(sent) != 1 || !strings.Contains(sent[0], "https://app.example.test/link/telegram?bot=door_bot&code=OFFER1-door_bot") {
		t.Fatalf("sent %q", sent)
	}
	want := identityapi.Account{Provider: "telegram", ExternalID: "42", Username: "alice", Name: "Alice Liddell"}
	if len(d.links.offers) != 1 || d.links.offers[0] != want {
		t.Fatalf("offered %+v", d.links.offers)
	}
	d.admit(t, 42, "private", "again")
	if sent := d.bot.take(); len(sent) != 0 {
		t.Fatalf("told twice while the link lives: %q", sent)
	}
	delete(d.notices.Keys, "trig:42:unlinked")
	d.admit(t, 42, "private", "after the link expired")
	if sent := d.bot.take(); len(sent) != 1 || !strings.Contains(sent[0], "code=OFFER2-door_bot") {
		t.Fatalf("no fresh link: %q", sent)
	}

	if _, refused := d.admit(t, 42, "private", "/start link_CODE"); refused != "account link requested" {
		t.Fatalf("refused %q", refused)
	}
	if sent := d.bot.take(); len(sent) != 1 || !strings.HasPrefix(sent[0], "Link this Telegram account to o***@example.com? Send /confirm") {
		t.Fatalf("sent %q", sent)
	}
	if _, refused := d.admit(t, 42, "private", "/confirm"); refused != "account link confirmation" {
		t.Fatalf("refused %q", refused)
	}
	if sent := d.bot.take(); len(sent) != 1 || sent[0] != "Done: this Telegram account is linked to o***@example.com." {
		t.Fatalf("sent %q", sent)
	}
	if d.links.linked != want {
		t.Fatalf("linked %+v", d.links.linked)
	}

	a, refused := d.admit(t, 42, "private", "hello")
	if refused != "" || a.UserID != "owner" || a.Sender != "" {
		t.Fatalf("admitted %+v refused %q", a, refused)
	}
}

func TestATelegramDoorRefusesWhoItCannotAnswerFor(t *testing.T) {
	d := newDoor(t)
	d.links.holders["7"] = "stranger"
	d.links.holders["42"] = "owner"
	if _, refused := d.admit(t, 42, "group", "hi"); refused != "only private chats reach the agent" {
		t.Fatalf("group: %q", refused)
	}
	if _, refused := d.admit(t, 7, "private", "hi"); !strings.HasPrefix(refused, "only the source's owner may write") {
		t.Fatalf("stranger: %q", refused)
	}
	if sent := d.bot.take(); len(sent) != 1 || sent[0] != "This bot is private." {
		t.Fatalf("sent %q", sent)
	}
	if _, refused := d.admit(t, 42, "private", "/start link_USED"); refused != "account link requested" {
		t.Fatalf("used code: %q", refused)
	}
	if sent := d.bot.take(); len(sent) != 1 || !strings.HasPrefix(sent[0], "This link has expired") {
		t.Fatalf("sent %q", sent)
	}
	d.graph.AllowAll = false
	if _, refused := d.admit(t, 42, "private", "hi"); refused != "user owner may not run agent agent" {
		t.Fatalf("no execute: %q", refused)
	}
	if sent := d.bot.take(); len(sent) != 1 || !strings.Contains(sent[0], "doesn't have access") {
		t.Fatalf("sent %q", sent)
	}
}
