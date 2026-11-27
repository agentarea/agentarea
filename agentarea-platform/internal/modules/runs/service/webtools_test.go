package service

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/api"
)

func webInvocation(method string, args map[string]any) ToolInvocation {
	return ToolInvocation{ToolName: "web_" + method, Args: args,
		Binding: api.ToolBinding{Source: "code", Code: &api.CodeBinding{Namespace: webToolset, Method: method}}}
}

func TestSearchWebMapsResults(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/search" || r.URL.Query().Get("q") != "go generics" || r.URL.Query().Get("format") != "json" {
			t.Errorf("unexpected request %s", r.URL)
		}
		_, _ = w.Write([]byte(`{"results":[{"title":"A","url":"https://a.example/x?y=1&z=2","content":"snip","engine":"ddg"},{"title":"no url"},{"title":"B","url":"https://b.example","content":"b"},{"title":"C","url":"https://c.example"}]}`))
	}))
	defer srv.Close()
	tools := webTools{clients: WebClients{Public: http.DefaultTransport, Vendor: http.DefaultTransport}, searchURL: srv.URL}
	out, err := tools.Call(context.Background(), webInvocation("search_web", map[string]any{"query": "  go generics ", "max_results": float64(3)}))
	if err != nil || !out.Success {
		t.Fatalf("search failed: %v %+v", err, out)
	}
	if !strings.Contains(out.Result, "https://a.example/x?y=1&z=2") {
		t.Fatalf("url escaped: %s", out.Result)
	}
	var got struct {
		Query   string              `json:"query"`
		Results []map[string]string `json:"results"`
	}
	if err := json.Unmarshal([]byte(out.Result), &got); err != nil {
		t.Fatal(err)
	}
	if got.Query != "go generics" || len(got.Results) != 2 || got.Results[0]["snippet"] != "snip" || got.Results[1]["engine"] != "" {
		t.Fatalf("results: %+v", got)
	}
}

func TestSearchWebRefusals(t *testing.T) {
	unset := webTools{}
	out, _ := unset.Call(context.Background(), webInvocation("search_web", map[string]any{"query": "x"}))
	if out.Success || !strings.Contains(out.Result, "AGENTAREA_TOOL_SEARCH_URL") {
		t.Fatalf("unconfigured: %+v", out)
	}
	set := webTools{searchURL: "http://unused"}
	for _, args := range []map[string]any{{"query": " "}, {"query": "x", "max_results": float64(21)}, {"query": "x", "max_results": true}} {
		if out, _ := set.Call(context.Background(), webInvocation("search_web", args)); out.Success {
			t.Fatalf("accepted %v", args)
		}
	}
}

func TestFetchWebpageHTML(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/old" {
			http.Redirect(w, r, "/page", http.StatusFound)
			return
		}
		w.Header().Set("Content-Type", "text/html; charset=utf-8")
		_, _ = w.Write([]byte(`<html><head><title>T</title><script>var x=1</script></head><body><p>Hello   <b>world</b></p><a href="/next?a=1&amp;b=2">Next  page</a><style>p{}</style></body></html>`))
	}))
	defer srv.Close()
	tools := webTools{clients: WebClients{Public: http.DefaultTransport}}
	out, _ := tools.Call(context.Background(), webInvocation("fetch_webpage", map[string]any{"url": srv.URL + "/old"}))
	if !out.Success {
		t.Fatalf("fetch failed: %+v", out)
	}
	var got struct {
		URL       string     `json:"url"`
		Status    int        `json:"status"`
		Truncated bool       `json:"truncated"`
		Extracted string     `json:"extracted_text"`
		Links     []pageLink `json:"links"`
		Text      string     `json:"text"`
	}
	if err := json.Unmarshal([]byte(out.Result), &got); err != nil {
		t.Fatal(err)
	}
	if got.URL != srv.URL+"/page" || got.Status != 200 || got.Truncated {
		t.Fatalf("envelope: %+v", got)
	}
	if got.Extracted != "Hello world Next page" {
		t.Fatalf("extracted %q", got.Extracted)
	}
	if len(got.Links) != 1 || got.Links[0].Href != srv.URL+"/next?a=1&b=2" || got.Links[0].Text != "Next page" {
		t.Fatalf("links %+v", got.Links)
	}
	if !strings.Contains(got.Text, "<script>") {
		t.Fatalf("raw text missing")
	}
}

func TestFetchWebpageRefusesBinaryAndBadURL(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/pdf")
		_, _ = w.Write([]byte("%PDF"))
	}))
	defer srv.Close()
	tools := webTools{clients: WebClients{Public: http.DefaultTransport}}
	out, _ := tools.Call(context.Background(), webInvocation("fetch_webpage", map[string]any{"url": srv.URL}))
	if out.Success || !strings.Contains(out.Result, "reads text pages only") {
		t.Fatalf("binary: %+v", out)
	}
	out, _ = tools.Call(context.Background(), webInvocation("fetch_webpage", map[string]any{"url": "file:///etc/passwd"}))
	if out.Success {
		t.Fatalf("file url accepted")
	}
}

func TestTextContentTypes(t *testing.T) {
	for ct, want := range map[string]bool{
		"text/plain": true, "application/json; charset=utf-8": true, "application/ld+json": true,
		"application/atom+xml": true, "image/png": false, "": false, "application/octet-stream": false,
	} {
		if isTextContentType(ct) != want {
			t.Errorf("%q: want %v", ct, want)
		}
	}
}

func TestSearchWebSaysSoWhenEveryEngineFailed(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = w.Write([]byte(`{"results":[],"unresponsive_engines":[["brave","Suspended: too many requests"],["duckduckgo","timeout"]]}`))
	}))
	defer srv.Close()
	tools := webTools{clients: WebClients{Public: http.DefaultTransport, Vendor: http.DefaultTransport}, searchURL: srv.URL}
	out, err := tools.Call(context.Background(), webInvocation("search_web", map[string]any{"query": "andy serkis"}))
	if err != nil {
		t.Fatal(err)
	}
	text := strings.TrimSpace(out.Result)
	if out.Success || !strings.Contains(text, "brave: Suspended: too many requests") || !strings.Contains(text, "duckduckgo: timeout") {
		t.Fatalf("an empty answer with every engine down must read as a failure naming them, got success=%v %q", out.Success, text)
	}
}
