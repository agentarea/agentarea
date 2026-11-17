package handlers_test

import (
	"bytes"
	"crypto/hmac"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"log/slog"
	"mime/multipart"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/go-chi/chi/v5"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/handlers"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/service"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/store/storetest"
)

type sourceRig struct {
	t    *testing.T
	h    http.Handler
	base string
	bus  *storetest.Bus
	blob *storetest.Blob
}

func newSourceRig(t *testing.T) *sourceRig {
	t.Helper()
	pool := storetest.Pool(t)
	ws := storetest.Workspace(t, pool)
	secrets := storetest.NewSecrets()
	bus := &storetest.Bus{}
	blob := &storetest.Blob{}
	svc := service.New(service.Deps{DB: storetest.DB{Pool: pool}, Graph: &storetest.Graph{AllowAll: true}, Agents: storetest.Agents{},
		SourceTypes: storetest.ShippedSourceTypes(t), Secrets: secrets, SecretCatalog: secrets.Catalog,
		Blob: blob, Bus: bus, Dedup: &storetest.Dedup{}, Quota: &storetest.Quota{},
		APIURL: "https://api.example.test", Settings: service.DefaultSettings()})
	errs := httpx.NewErrors("http://api.test", slog.Default(), handlers.MapError)
	r := chi.NewRouter()
	caller := func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, req *http.Request) {
			ctx := authn.WithCaller(req.Context(), authn.Caller{Principal: authn.Principal{UserID: "u1"}, Workspace: ws})
			next.ServeHTTP(w, req.WithContext(ctx))
		})
	}
	handlers.Mount(r, errs, caller, handlers.New(svc, nil, nil))
	return &sourceRig{t: t, h: r, base: "/v1/workspaces/" + ws.Slug() + "/streams", bus: bus, blob: blob}
}

func (g *sourceRig) send(method, path, contentType string, body []byte, headers map[string]string) (int, map[string]any) {
	g.t.Helper()
	req := httptest.NewRequest(method, path, bytes.NewReader(body))
	if contentType != "" {
		req.Header.Set("Content-Type", contentType)
	}
	for k, v := range headers {
		req.Header.Set(k, v)
	}
	rec := httptest.NewRecorder()
	g.h.ServeHTTP(rec, req)
	var out map[string]any
	_ = json.Unmarshal(rec.Body.Bytes(), &out)
	return rec.Code, out
}

func (g *sourceRig) json(method, path string, body any) (int, map[string]any) {
	g.t.Helper()
	raw, _ := json.Marshal(body)
	return g.send(method, path, "application/json", raw, nil)
}

func hubSig(body []byte) string {
	m := hmac.New(sha256.New, []byte("s3cret"))
	m.Write(body)
	return "sha256=" + hex.EncodeToString(m.Sum(nil))
}

func TestSourcesOverHTTPAndTheWebhookSink(t *testing.T) {
	g := newSourceRig(t)
	code, st := g.json(http.MethodPost, g.base+"/", map[string]any{"name": "inbox"})
	if code != http.StatusCreated {
		t.Fatalf("stream %d %v", code, st)
	}
	streamID := st["id"].(string)

	code, types := g.send(http.MethodGet, g.base+"/source-types", "", nil, nil)
	if code != http.StatusOK && types == nil {
		t.Fatalf("source types %d", code)
	}
	code, body := g.json(http.MethodPost, g.base+"/"+streamID+"/sources", map[string]any{"source_type": "nope", "kind": "webhook"})
	if code != http.StatusUnprocessableEntity {
		t.Fatalf("unknown type %d %v", code, body)
	}
	code, src := g.json(http.MethodPost, g.base+"/"+streamID+"/sources", map[string]any{"source_type": "github", "kind": "webhook",
		"credentials": map[string]any{"webhook_secret": "s3cret"}})
	if code != http.StatusCreated {
		t.Fatalf("add %d %v", code, src)
	}
	url, _ := src["webhook_url"].(string)
	if !strings.HasPrefix(url, "https://api.example.test/webhooks/") || src["registered"] != false {
		t.Fatalf("source %v", src)
	}
	hook := strings.TrimPrefix(url, "https://api.example.test")

	if code, _ := g.send(http.MethodGet, "/webhooks/health", "", nil, nil); code != http.StatusOK {
		t.Fatalf("health %d", code)
	}
	payload := []byte(`{"action":"opened","sender":{"login":"octo"}}`)
	gh := map[string]string{"X-Hub-Signature-256": hubSig(payload), "X-GitHub-Event": "issues", "X-GitHub-Delivery": "h1"}
	if code, out := g.send(http.MethodPost, hook, "application/json", payload, gh); code != http.StatusAccepted || out["status"] != "accepted" {
		t.Fatalf("deliver %d %v", code, out)
	}
	if code, out := g.send(http.MethodPost, hook, "application/json", []byte(`{"a":`), gh); code != http.StatusBadRequest || out["status"] != "error" {
		t.Fatalf("bad json %d %v", code, out)
	}
	nul := []byte(`{"text":"a\u0000b"}`)
	gh["X-Hub-Signature-256"] = hubSig(nul)
	if code, _ := g.send(http.MethodPost, hook, "application/json", nul, gh); code != http.StatusUnprocessableEntity {
		t.Fatalf("NUL %d", code)
	}
	req := httptest.NewRequest(http.MethodPost, hook, strings.NewReader("{}"))
	req.ContentLength = 26 << 20
	rec := httptest.NewRecorder()
	g.h.ServeHTTP(rec, req)
	if rec.Code != http.StatusRequestEntityTooLarge {
		t.Fatalf("declared length %d", rec.Code)
	}
	if code, _ := g.send(http.MethodPost, "/webhooks/unknown", "application/json", []byte(`{}`), nil); code != http.StatusNotFound {
		t.Fatalf("unknown %d", code)
	}

	sid := src["id"].(string)
	if code, out := g.json(http.MethodPatch, g.base+"/"+streamID+"/sources/"+sid, map[string]any{"senders": map[string]any{"allow": "owner"}}); code != http.StatusUnprocessableEntity {
		t.Fatalf("senders on github %d %v", code, out)
	}
	if code, list := g.send(http.MethodGet, g.base+"/"+streamID+"/sources", "", nil, nil); code != http.StatusOK || list == nil && code != http.StatusOK {
		t.Fatalf("list %d", code)
	}
	if code, _ := g.send(http.MethodDelete, g.base+"/"+streamID+"/sources/"+sid, "", nil, nil); code != http.StatusNoContent {
		t.Fatalf("delete %d", code)
	}
	if code, _ := g.send(http.MethodPost, hook, "application/json", payload, gh); code != http.StatusNotFound {
		t.Fatalf("after delete %d", code)
	}
}

func TestMultipartFilesBecomeAttachments(t *testing.T) {
	g := newSourceRig(t)
	_, st := g.json(http.MethodPost, g.base+"/", map[string]any{"name": "mail"})
	_, src := g.json(http.MethodPost, g.base+"/"+st["id"].(string)+"/sources", map[string]any{"source_type": "email", "kind": "webhook"})
	issued, _ := src["issued"].(map[string]any)
	secret, _ := issued["signing_secret"].(string)
	if secret == "" {
		t.Fatalf("no issued secret: %v", src)
	}
	var buf bytes.Buffer
	mw := multipart.NewWriter(&buf)
	_ = mw.WriteField("message_id", "<m1@x>")
	fw, _ := mw.CreateFormFile("file", "a.txt")
	_, _ = fw.Write([]byte("hello"))
	_ = mw.Close()
	m := hmac.New(sha256.New, []byte(secret))
	m.Write(buf.Bytes())
	sig := hex.EncodeToString(m.Sum(nil))
	hook := strings.TrimPrefix(src["webhook_url"].(string), "https://api.example.test")
	code, out := g.send(http.MethodPost, hook, mw.FormDataContentType(), buf.Bytes(), map[string]string{"X-Webhook-Signature": sig})
	if code != http.StatusAccepted {
		t.Fatalf("multipart %d %v", code, out)
	}
	ev := g.bus.Events()
	raw, _ := json.Marshal(ev[len(ev)-1].Event)
	if strings.Contains(string(raw), "content_base64") || !strings.Contains(string(raw), "a.txt") || !strings.Contains(string(raw), hex.EncodeToString(sha([]byte("hello")))) {
		t.Fatalf("attachment not moved to files: %s", raw)
	}
	if keys := g.blob.Keys(); len(keys) != 1 || !strings.HasSuffix(keys[0], "a.txt") {
		t.Fatalf("stored %v", keys)
	}
}

func sha(b []byte) []byte {
	h := sha256.Sum256(b)
	return h[:]
}
