package openapispec

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx/wirejson"
)

func doc(t *testing.T, raw string) any {
	t.Helper()
	v, err := wirejson.Unmarshal([]byte(raw))
	if err != nil {
		t.Fatal(err)
	}
	return v
}

func TestSlugify(t *testing.T) {
	for in, want := range map[string]string{"getPet": "getPet", "get pet/by id": "get_pet_by_id", "": ""} {
		if got := Slugify(in); got != want {
			t.Fatalf("Slugify(%q) = %q, want %q", in, got, want)
		}
	}
}

func TestParseSpecKeepsOrderAndRefusesReservedNames(t *testing.T) {
	spec := doc(t, `{"openapi":"3.0.0","paths":{
"/z":{"get":{"operationId":"zed"}},
"/a/{id}":{"parameters":[{"name":"id","in":"path","required":true,"schema":{"type":"string"}}],
 "post":{"operationId":"makeA","requestBody":{"required":true,"content":{"application/json":{"schema":{"type":"object","properties":{"n":{"type":"integer"}}}}}}}}}}`)
	tools, err := ParseSpec(spec, nil)
	if err != nil {
		t.Fatal(err)
	}
	if len(tools) != 2 || tools[0].Name != "zed" || tools[1].Name != "makeA" {
		t.Fatalf("tools = %+v", tools)
	}
	ops, err := ParseOperations(spec, nil)
	if err != nil {
		t.Fatal(err)
	}
	if ops[1].Method != "POST" && ops[1].Method != "post" {
		t.Fatalf("method = %q", ops[1].Method)
	}
	raw, _ := json.Marshal(tools[1].InputSchema)
	if !strings.Contains(string(raw), `"id"`) {
		t.Fatalf("path parameter missing from schema: %s", raw)
	}
}

func TestCheckURLVariables(t *testing.T) {
	if err := CheckURLVariables("https://api.example.com/{tenant}/v1", []string{"tenant"}); err != nil {
		t.Fatal(err)
	}
	if err := CheckURLVariables("https://{tenant}.example.com", []string{"tenant"}); err == nil {
		t.Fatal("a variable in the host was accepted")
	}
	if err := CheckURLVariables("https://api.example.com/v1", []string{"unused"}); err == nil {
		t.Fatal("an unused variable was accepted")
	}
}

func TestCatalogKeyTemplate(t *testing.T) {
	scheme := "Bearer"
	tpl, err := CatalogKeyTemplate(map[string]any{"api_key": map[string]any{"fields": []any{
		map[string]any{"name": "Authorization", "location": "header", "label": "API key", "scheme": scheme},
		map[string]any{"name": "app", "location": "query", "label": "App id"},
	}}})
	if err != nil || tpl == nil {
		t.Fatalf("template = %v, %v", tpl, err)
	}
	h, q, err := tpl.Credentials(map[string]string{"Authorization": "k", "app": " a "})
	if err != nil || h[0].Value != "Bearer k" || q[0].Value != "a" {
		t.Fatalf("h = %v, q = %v, err = %v", h, q, err)
	}
	if _, _, err := tpl.Credentials(map[string]string{"Authorization": "k"}); err == nil || err.Error() != "App id is required" {
		t.Fatalf("missing field: %v", err)
	}
	if none, err := CatalogKeyTemplate(map[string]any{}); none != nil || err != nil {
		t.Fatalf("no template: %v %v", none, err)
	}
}

func TestFetchDoesNotFollowRedirectsAndBoundsSize(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/redirect":
			http.Redirect(w, r, "/spec.yaml", http.StatusFound)
		case "/spec.yaml":
			_, _ = io.WriteString(w, "openapi: 3.0.0\npaths: {}\n")
		case "/big":
			_, _ = io.WriteString(w, `{"x":"`+strings.Repeat("a", MaxSpecBytes)+`"}`)
		case "/alias.yaml":
			_, _ = io.WriteString(w, "a: &x [1]\nb: *x\n")
		}
	}))
	defer srv.Close()
	client := &http.Client{CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}
	ctx := context.Background()
	if _, err := Fetch(ctx, client, srv.URL+"/redirect", nil); err == nil || !strings.Contains(err.Error(), "returned HTTP 302") {
		t.Fatalf("redirect: %v", err)
	}
	v, err := Fetch(ctx, client, srv.URL+"/spec.yaml", nil)
	if err != nil {
		t.Fatal(err)
	}
	if o, ok := v.(wirejson.Object); !ok || o[0].Key != "openapi" {
		t.Fatalf("yaml = %#v", v)
	}
	if _, err := Fetch(ctx, client, srv.URL+"/big", nil); err == nil || err.Error() != "Spec response exceeds 5MB limit." {
		t.Fatalf("big: %v", err)
	}
	if _, err := Fetch(ctx, client, srv.URL+"/alias.yaml", nil); err == nil {
		t.Fatal("a YAML alias was accepted")
	}
}

func TestBuildAndDo(t *testing.T) {
	var got *http.Request
	var body string
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		got = r
		raw, _ := io.ReadAll(r.Body)
		body = string(raw)
		if r.URL.Path == "/fail" {
			w.WriteHeader(http.StatusTeapot)
			_, _ = io.WriteString(w, "nope")
			return
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = io.WriteString(w, `{"ok":true,"n":[1,2]}`)
	}))
	defer srv.Close()
	ops, err := ParseOperations(doc(t, `{"openapi":"3.0.0","paths":{
"/items/{id}":{"post":{"operationId":"put","parameters":[{"name":"id","in":"path","required":true},{"name":"q","in":"query"}],
 "requestBody":{"content":{"application/json":{"schema":{"type":"object"}}}}}},
"/fail":{"get":{"operationId":"fail"}}}}`), map[string]bool{"key": true})
	if err != nil {
		t.Fatal(err)
	}
	req, tmpl, err := Build(context.Background(), Request{Op: ops[0], BaseTemplate: srv.URL, BaseURL: srv.URL,
		Headers: map[string]string{"X-K": "v"}, Query: map[string]string{"key": "s"},
		Args: map[string]any{"id": "a/b", "q": "x", "body": map[string]any{"n": 1}}})
	if err != nil {
		t.Fatal(err)
	}
	if !strings.HasPrefix(tmpl, srv.URL+"/items/") || strings.Contains(tmpl, "key=") {
		t.Fatalf("template = %s", tmpl)
	}
	res := Do(srv.Client(), req, ops[0])
	if !res.Success || res.Result != `{"ok": true, "n": [1, 2]}` {
		t.Fatalf("result = %+v", res)
	}
	if got.URL.EscapedPath() != "/items/a%2Fb" || got.URL.Query().Get("key") != "s" || got.URL.Query().Get("q") != "x" || got.Header.Get("X-K") != "v" {
		t.Fatalf("request = %s %v", got.URL, got.Header)
	}
	if !strings.Contains(body, `"n"`) {
		t.Fatalf("body = %s", body)
	}
	req, _, err = Build(context.Background(), Request{Op: ops[1], BaseURL: srv.URL, BaseTemplate: srv.URL})
	if err != nil {
		t.Fatal(err)
	}
	if res := Do(srv.Client(), req, ops[1]); res.Success || res.Error != "HTTP 418: nope" || res.StatusCode != 418 {
		t.Fatalf("failure = %+v", res)
	}
}
