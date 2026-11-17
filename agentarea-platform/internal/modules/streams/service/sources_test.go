package service_test

import (
	"context"
	"crypto/hmac"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"net/http"
	"strings"
	"testing"

	"github.com/google/uuid"

	ksecrets "github.com/agentarea/agentarea/agentarea-platform/internal/kernel/secrets"
	catalogapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/catalog/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/domain"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/service"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/store/storetest"
)

type sourceFixture struct {
	ctx     context.Context
	svc     *service.Service
	secrets *storetest.Secrets
	bus     *storetest.Bus
	blob    *storetest.Blob
	ws      string
	stream  string
}

const enderType = `{"slug":"ender","name":"Ender","delivery":"webhook",
 "credentials":[{"key":"token","label":"Token","required":true}],
 "verification":{"scheme":"shared_token","secret":"token","header":"X-Token"},
 "signals":[{"when":"{body:type}","equals":"bye","signal":"ended","key":"{body:sub}","reason":"{body:why}"}],
 "event":{"kind":"{body:type}","key":"{body:id}"}}`

func newSources(t *testing.T, quota int) sourceFixture {
	t.Helper()
	pool := storetest.Pool(t)
	ws := storetest.Workspace(t, pool)
	ctx, _ := storetest.Caller(context.Background(), ws, "u1")
	secrets := storetest.NewSecrets()
	f := sourceFixture{ctx: ctx, secrets: secrets, bus: &storetest.Bus{}, blob: &storetest.Blob{}, ws: ws.ID()}
	settings := service.DefaultSettings()
	settings.WriteQuota = quota
	f.svc = service.New(service.Deps{
		DB: storetest.DB{Pool: pool}, Graph: &storetest.Graph{AllowAll: true},
		SourceTypes:   storetest.ShippedSourceTypes(t, catalogapi.SourceTypeRow{Slug: "ender", Spec: json.RawMessage(enderType)}),
		Secrets:       secrets,
		SecretCatalog: secrets.Catalog,
		Blob:          f.blob, Bus: f.bus, Dedup: &storetest.Dedup{}, Quota: &storetest.Quota{},
		APIURL: "https://api.example.test", Settings: settings,
	})
	st, err := f.svc.CreateStream(ctx, "inbox-"+uuid.NewString()[:8], "")
	if err != nil {
		t.Fatal(err)
	}
	f.stream = st.ID
	return f
}

func value(s string) service.Credential { return service.Credential{Value: &s} }

func signed(secret string, body []byte) string {
	m := hmac.New(sha256.New, []byte(secret))
	m.Write(body)
	return "sha256=" + hex.EncodeToString(m.Sum(nil))
}

func (f sourceFixture) github(t *testing.T) domain.Source {
	t.Helper()
	src, issued, err := f.svc.AddSource(f.ctx, f.stream, service.NewSource{SourceType: "github", Kind: "webhook",
		Credentials: map[string]service.Credential{"webhook_secret": value("s3cret")}})
	if err != nil {
		t.Fatal(err)
	}
	if len(issued) != 0 || src.WebhookID == nil || len(*src.WebhookID) < 20 {
		t.Fatalf("source %+v issued %v", src, issued)
	}
	return src
}

func (f sourceFixture) deliver(t *testing.T, src domain.Source, headers map[string]string, body string) service.WebhookAnswer {
	t.Helper()
	var parsed any
	if body != "" {
		parsed = mustDecode(t, body)
	}
	a, err := f.svc.HandleWebhook(context.Background(), service.WebhookDelivery{WebhookID: *src.WebhookID, Headers: headers,
		Raw: []byte(body), Body: parsed})
	if err != nil {
		t.Fatal(err)
	}
	return a
}

func mustDecode(t *testing.T, s string) any {
	t.Helper()
	v, err := service.DecodeJSON([]byte(s))
	if err != nil {
		t.Fatal(err)
	}
	return v
}

func status(a service.WebhookAnswer) string {
	m, _ := a.Body.(map[string]any)
	s, _ := m["status"].(string)
	return s
}

func TestAGithubSourceStoresItsCredentialAndListsWithItsURL(t *testing.T) {
	f := newSources(t, 600)
	src := f.github(t)
	name := service.CredentialSecretName("github", *src.CredentialKey)
	if v := f.secrets.Values[name]; v != `{"webhook_secret": "s3cret"}` && v != `{"webhook_secret":"s3cret"}` {
		t.Fatalf("stored credentials %q", v)
	}
	if got := f.svc.PublicWebhookURL(*src.WebhookID); got != "https://api.example.test/webhooks/"+*src.WebhookID {
		t.Fatal(got)
	}
	list, err := f.svc.ListSources(f.ctx, f.stream)
	if err != nil || len(list) != 1 || list[0].ID != src.ID {
		t.Fatalf("list %v %v", list, err)
	}
	if err := f.svc.DeleteSource(f.ctx, f.stream, src.ID); err != nil {
		t.Fatal(err)
	}
	if _, ok := f.secrets.Values[name]; ok {
		t.Fatal("credential secret survived its source")
	}
}

func TestAnIssuedSigningSecretIsReturnedOnce(t *testing.T) {
	f := newSources(t, 600)
	_, issued, err := f.svc.AddSource(f.ctx, f.stream, service.NewSource{SourceType: "generic_webhook", Kind: "webhook"})
	if err != nil {
		t.Fatal(err)
	}
	if len(issued["signing_secret"]) < 20 {
		t.Fatalf("issued %v", issued)
	}
	mcp, err := f.svc.SourceTypeEntries(f.ctx)
	if err != nil || len(mcp) < 15 {
		t.Fatalf("entries %d %v", len(mcp), err)
	}
}

func TestAddSourceRefusals(t *testing.T) {
	f := newSources(t, 600)
	cases := map[string]service.NewSource{
		"Unknown source type 'nope'": {SourceType: "nope", Kind: "webhook"},
		"webhook_secret":             {SourceType: "github", Kind: "webhook"},
		"has no credential extra":    {SourceType: "github", Kind: "webhook", Credentials: map[string]service.Credential{"webhook_secret": value("x"), "extra": value("y")}},
	}
	for want, n := range cases {
		_, _, err := f.svc.AddSource(f.ctx, f.stream, n)
		if err == nil || !strings.Contains(err.Error(), want) && !strings.Contains(strings.ToLower(err.Error()), strings.ToLower(want)) {
			t.Errorf("%s: %v", want, err)
		}
	}
	sid := uuid.NewString()
	f.secrets.Named[sid] = ksecrets.Secret{ID: sid, Name: "gh"}
	f.secrets.Denied[sid] = true
	_, _, err := f.svc.AddSource(f.ctx, f.stream, service.NewSource{SourceType: "github", Kind: "webhook",
		Credentials: map[string]service.Credential{"webhook_secret": {SecretID: &sid}}})
	if !errors.Is(err, service.ErrSecretForbidden) {
		t.Fatalf("denied secret: %v", err)
	}
}

func TestAPickedSecretIsStoredAsAReference(t *testing.T) {
	f := newSources(t, 600)
	sid := uuid.NewString()
	f.secrets.Named[sid] = ksecrets.Secret{ID: sid, Name: "gh_hook"}
	f.secrets.Values["gh_hook"] = "s3cret"
	src, _, err := f.svc.AddSource(f.ctx, f.stream, service.NewSource{SourceType: "github", Kind: "webhook",
		Credentials: map[string]service.Credential{"webhook_secret": {SecretID: &sid}}})
	if err != nil {
		t.Fatal(err)
	}
	if v := f.secrets.Values[service.CredentialSecretName("github", *src.CredentialKey)]; !strings.Contains(v, `"secret_name":"gh_hook"`) {
		t.Fatalf("stored %q", v)
	}
	if len(f.secrets.Refs[service.SecretConsumer+":"+src.ID]) == 0 {
		t.Fatal("no reference staged")
	}
	body := `{"action":"opened","sender":{"login":"octo"}}`
	a := f.deliver(t, src, map[string]string{"x-hub-signature-256": signed("s3cret", []byte(body)), "x-github-event": "issues",
		"x-github-delivery": "d1"}, body)
	if a.Status != http.StatusAccepted {
		t.Fatalf("referenced secret did not verify: %+v", a)
	}
}

func TestTheSinkVerifiesRecordsAndDeduplicates(t *testing.T) {
	f := newSources(t, 600)
	src := f.github(t)
	body := `{"action":"opened","sender":{"login":"octo"}}`
	headers := map[string]string{"x-hub-signature-256": signed("s3cret", []byte(body)), "x-github-event": "issues",
		"x-github-delivery": "d1", "authorization": "Bearer leak"}
	if a := f.deliver(t, src, headers, body); a.Status != http.StatusAccepted || status(a) != "accepted" {
		t.Fatalf("first: %+v", a)
	}
	if a := f.deliver(t, src, headers, body); a.Status != http.StatusAccepted || status(a) != "duplicate" {
		t.Fatalf("second: %+v", a)
	}
	pub := f.bus.Events()
	if len(pub) != 1 {
		t.Fatalf("published %d", len(pub))
	}
	raw, _ := json.Marshal(pub[0].Event)
	if strings.Contains(string(raw), "leak") || strings.Contains(string(raw), "sha256=") {
		t.Fatalf("credentials reached the event: %s", raw)
	}
	bad := map[string]string{"x-hub-signature-256": signed("other", []byte(body)), "x-github-event": "issues"}
	if a := f.deliver(t, src, bad, body); a.Status != http.StatusUnauthorized {
		t.Fatalf("bad signature: %+v", a)
	}
	unknown := domain.Source{WebhookID: ptr("nope")}
	if a := f.deliver(t, unknown, nil, "{}"); a.Status != http.StatusNotFound {
		t.Fatalf("unknown webhook: %+v", a)
	}
}

func TestALargeBodyMovesToTheWorkspaceFiles(t *testing.T) {
	f := newSources(t, 600)
	src := f.github(t)
	body := `{"action":"opened","pad":"` + strings.Repeat("x", 70*1024) + `"}`
	a := f.deliver(t, src, map[string]string{"x-hub-signature-256": signed("s3cret", []byte(body)), "x-github-event": "issues",
		"x-github-delivery": "big"}, body)
	if a.Status != http.StatusAccepted {
		t.Fatalf("%+v", a)
	}
	keys := f.blob.Keys()
	if len(keys) != 1 || !strings.HasSuffix(keys[0], "/body.json") || !strings.Contains(keys[0], "events/"+f.stream+"/") {
		t.Fatalf("stored %v", keys)
	}
}

func TestTheQuotaRefusesWithTooManyRequests(t *testing.T) {
	f := newSources(t, 1)
	src := f.github(t)
	send := func(id string) service.WebhookAnswer {
		body := `{"action":"opened"}`
		return f.deliver(t, src, map[string]string{"x-hub-signature-256": signed("s3cret", []byte(body)), "x-github-event": "issues",
			"x-github-delivery": id}, body)
	}
	if a := send("q1"); a.Status != http.StatusAccepted {
		t.Fatalf("%+v", a)
	}
	if a := send("q2"); a.Status != http.StatusTooManyRequests {
		t.Fatalf("%+v", a)
	}
}

func TestAHandshakeIsAnsweredAndAnEndedSignalClearsTheSource(t *testing.T) {
	f := newSources(t, 600)
	slack, _, err := f.svc.AddSource(f.ctx, f.stream, service.NewSource{SourceType: "ender", Kind: "webhook",
		Credentials: map[string]service.Credential{"token": value("t1")}})
	if err != nil {
		t.Fatal(err)
	}
	hdr := map[string]string{"x-token": "t1"}
	if a := f.deliver(t, slack, hdr, `{"type":"ping","id":"1"}`); a.Status != http.StatusAccepted {
		t.Fatalf("event: %+v", a)
	}
	if a := f.deliver(t, slack, hdr, `{"type":"bye","sub":"s1","why":"revoked"}`); a.Status != http.StatusOK || status(a) != "ended" {
		t.Fatalf("ended: %+v", a)
	}
	if a := f.deliver(t, slack, map[string]string{"x-token": "t2"}, `{"type":"ping"}`); a.Status != http.StatusUnauthorized {
		t.Fatalf("wrong token: %+v", a)
	}
}

func ptr(s string) *string { return &s }
