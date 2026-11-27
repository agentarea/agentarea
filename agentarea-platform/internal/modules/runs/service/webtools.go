package service

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"mime"
	"net/http"
	"net/url"
	"regexp"
	"strings"
	"time"
	"unicode/utf8"

	"golang.org/x/net/html"
	"golang.org/x/net/html/charset"
)

// webToolset is web_toolset.py: search through the deployment's search
// service, and pages read inline, never stored.
const webToolset = "agentarea/web"

const (
	webTimeout      = 15 * time.Second
	webInlineChars  = 50_000
	webMaxBytes     = 5 * 1024 * 1024
	webMaxRedirects = 5
	webMaxLinks     = 100
	webUserAgent    = "Mozilla/5.0 (compatible; AgentArea/1.0; +https://agentarea.ai)"
)

// WebClients are the transports of the web toolset: Public for a page an
// agent names (every hop vetted, public addresses only), Vendor for the
// operator's search service.
type WebClients struct {
	Public http.RoundTripper
	Vendor http.RoundTripper
}

type webTools struct {
	clients   WebClients
	searchURL string
}

func (s *Service) webCaller(in ToolCall) ToolCaller {
	b := in.Binding
	if b.Source != "code" || b.Code == nil || b.Code.Namespace != webToolset {
		return nil
	}
	return webTools{clients: s.d.Web, searchURL: s.d.Settings.ToolSearchURL}
}

func (t webTools) Call(ctx context.Context, inv ToolInvocation) (ToolOutput, error) {
	var text string
	switch inv.Binding.Code.Method {
	case "search_web":
		text = t.search(ctx, inv.Args)
	case "fetch_webpage":
		text = t.fetch(ctx, inv.Args)
	default:
		return unknownTool(inv.ToolName), nil
	}
	if strings.HasPrefix(text, "Error") {
		return ToolOutput{Result: text, Error: text, Source: "builtin"}, nil
	}
	return ToolOutput{Success: true, Result: text, Source: "builtin"}, nil
}

func (t webTools) search(ctx context.Context, args map[string]any) string {
	if t.searchURL == "" {
		return "Error: web search is not configured; set AGENTAREA_TOOL_SEARCH_URL to a SearXNG-compatible endpoint"
	}
	query, _ := args["query"].(string)
	query = strings.TrimSpace(query)
	if query == "" {
		return "Error: query must be non-empty"
	}
	maxResults := 8
	if v, ok := args["max_results"]; ok && v != nil {
		f, isNum := v.(float64)
		if !isNum || f != float64(int(f)) || f < 1 || f > 20 {
			return "Error: max_results must be between 1 and 20"
		}
		maxResults = int(f)
	}
	ctx, cancel := context.WithTimeout(ctx, webTimeout)
	defer cancel()
	u := t.searchURL + "/search?" + url.Values{"q": {query}, "format": {"json"}}.Encode()
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, u, nil)
	if err != nil {
		return "Error searching the web: " + err.Error()
	}
	req.Header.Set("Accept", "application/json")
	resp, err := (&http.Client{Transport: t.clients.Vendor}).Do(req)
	if err != nil {
		return "Error searching the web: " + err.Error()
	}
	defer func() { _ = resp.Body.Close() }()
	if resp.StatusCode >= 400 {
		return fmt.Sprintf("Error searching the web: search service answered %d", resp.StatusCode)
	}
	var payload struct {
		Results      any     `json:"results"`
		Unresponsive [][]any `json:"unresponsive_engines"`
	}
	if err := json.NewDecoder(io.LimitReader(resp.Body, webMaxBytes)).Decode(&payload); err != nil {
		return "Error searching the web: " + err.Error()
	}
	raw, ok := payload.Results.([]any)
	if !ok {
		return "Error: search service returned an invalid response"
	}
	type result struct {
		Title   string `json:"title"`
		URL     string `json:"url"`
		Snippet string `json:"snippet"`
		Engine  string `json:"engine"`
	}
	results := []result{}
	for _, item := range raw[:min(maxResults, len(raw))] {
		m, ok := item.(map[string]any)
		if !ok {
			continue
		}
		link, okURL := m["url"].(string)
		title, okTitle := m["title"].(string)
		if !okURL || !okTitle {
			continue
		}
		results = append(results, result{Title: title, URL: link, Snippet: textOf(m["content"]), Engine: textOf(m["engine"])})
	}
	if len(results) == 0 && len(payload.Unresponsive) > 0 {
		engines := make([]string, 0, len(payload.Unresponsive))
		for _, pair := range payload.Unresponsive {
			parts := make([]string, 0, len(pair))
			for _, p := range pair {
				parts = append(parts, fmt.Sprint(p))
			}
			engines = append(engines, strings.Join(parts, ": "))
		}
		return "Error searching the web: no search engine answered (" + strings.Join(engines, "; ") +
			"). The search is down, not empty: try again later or fetch a page you know directly."
	}
	return compactJSON(map[string]any{"query": query, "results": results})
}

func textOf(v any) string {
	if v == nil {
		return ""
	}
	if s, ok := v.(string); ok {
		return s
	}
	return fmt.Sprint(v)
}

func (t webTools) fetch(ctx context.Context, args map[string]any) string {
	raw, _ := args["url"].(string)
	if !strings.HasPrefix(raw, "http://") && !strings.HasPrefix(raw, "https://") {
		return fmt.Sprintf("Error: url must be http(s); got %q", raw)
	}
	timeout := webTimeout
	if v, ok := args["timeout_seconds"].(float64); ok && v > 0 {
		timeout = time.Duration(v * float64(time.Second))
	}
	ctx, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, raw, nil)
	if err != nil {
		return fmt.Sprintf("Error fetching %s: %s", raw, err)
	}
	req.Header.Set("Accept", "text/html,application/xhtml+xml,text/plain,application/json;q=0.9,*/*;q=0.1")
	req.Header.Set("User-Agent", webUserAgent)
	client := &http.Client{Transport: t.clients.Public, CheckRedirect: func(_ *http.Request, via []*http.Request) error {
		if len(via) > webMaxRedirects {
			return fmt.Errorf("stopped after %d redirects", webMaxRedirects)
		}
		return nil
	}}
	resp, err := client.Do(req)
	if err != nil {
		return fmt.Sprintf("Error fetching %s: %s", raw, err)
	}
	defer func() { _ = resp.Body.Close() }()
	contentType := resp.Header.Get("Content-Type")
	if !isTextContentType(contentType) {
		got := contentType
		if got == "" {
			got = "an unknown content type"
		}
		return fmt.Sprintf("Error: %s returned %s; fetch_webpage reads text pages only. Download files with the sandbox shell instead.", raw, got)
	}
	body, err := io.ReadAll(io.LimitReader(resp.Body, webMaxBytes+1))
	if err != nil {
		return fmt.Sprintf("Error fetching %s: %s", raw, err)
	}
	if len(body) > webMaxBytes {
		return fmt.Sprintf("Error: %s is larger than %d bytes", raw, webMaxBytes)
	}
	text := decodeBody(body, contentType)
	finalURL := resp.Request.URL.String()
	payload := orderedJSON{
		{"url", finalURL}, {"status", resp.StatusCode}, {"content_type", contentType},
		{"truncated", utf8.RuneCountInString(text) > webInlineChars},
	}
	if isHTMLContentType(contentType) {
		extracted, links := htmlSummary(text, resp.Request.URL)
		payload = append(payload, kv{"extracted_text", truncateRunes(extracted, webInlineChars)}, kv{"links", links})
	}
	payload = append(payload, kv{"text", truncateRunes(text, webInlineChars)})
	return payload.String()
}

func mediaType(contentType string) string {
	mt, _, err := mime.ParseMediaType(contentType)
	if err != nil {
		mt = strings.TrimSpace(strings.SplitN(contentType, ";", 2)[0])
	}
	return strings.ToLower(mt)
}

func isTextContentType(contentType string) bool {
	if contentType == "" {
		return false
	}
	ct := mediaType(contentType)
	if strings.HasPrefix(ct, "application/") && (strings.HasSuffix(ct, "+xml") || strings.HasSuffix(ct, "+json")) {
		return true
	}
	for _, p := range []string{"text/", "application/json", "application/xml", "application/xhtml", "application/javascript"} {
		if strings.HasPrefix(ct, p) {
			return true
		}
	}
	return false
}

func isHTMLContentType(contentType string) bool {
	ct := mediaType(contentType)
	return ct == "text/html" || ct == "application/xhtml+xml"
}

func decodeBody(body []byte, contentType string) string {
	if _, params, err := mime.ParseMediaType(contentType); err == nil {
		if cs := params["charset"]; cs != "" && !strings.EqualFold(cs, "utf-8") {
			if enc, _ := charset.Lookup(cs); enc != nil {
				if out, err := enc.NewDecoder().Bytes(body); err == nil {
					return string(out)
				}
			}
		}
	}
	return strings.ToValidUTF8(string(body), "�")
}

var spaceRun = regexp.MustCompile(`\s+`)

func squash(s string) string { return strings.TrimSpace(spaceRun.ReplaceAllString(s, " ")) }

type pageLink struct {
	Href string `json:"href"`
	Text string `json:"text"`
}

// htmlSummary is _HTMLSummaryExtractor: visible text with script, style,
// noscript and head dropped, and every link resolved against the page.
func htmlSummary(page string, base *url.URL) (string, []pageLink) {
	links := []pageLink{}
	var text, linkText strings.Builder
	var href string
	skip := 0
	z := html.NewTokenizer(strings.NewReader(page))
	for {
		switch z.Next() {
		case html.ErrorToken:
			out := squash(text.String())
			if len(links) > webMaxLinks {
				links = links[:webMaxLinks]
			}
			return out, links
		case html.StartTagToken, html.SelfClosingTagToken:
			name, hasAttr := z.TagName()
			tag := string(name)
			if !inlineTag(tag) {
				text.WriteByte(' ')
			}
			if dropTag(tag) {
				skip++
				continue
			}
			if tag != "a" || skip != 0 {
				continue
			}
			for hasAttr {
				var k, v []byte
				k, v, hasAttr = z.TagAttr()
				if string(k) == "href" && len(v) > 0 {
					if ref, err := url.Parse(string(v)); err == nil {
						href = base.ResolveReference(ref).String()
						linkText.Reset()
					}
				}
			}
		case html.EndTagToken:
			name, _ := z.TagName()
			tag := string(name)
			if !inlineTag(tag) {
				text.WriteByte(' ')
			}
			if tag == "a" && href != "" {
				links = append(links, pageLink{Href: href, Text: squash(linkText.String())})
				href = ""
			}
			if dropTag(tag) && skip > 0 {
				skip--
			}
		case html.TextToken:
			if skip == 0 {
				t := string(z.Text())
				text.WriteString(t)
				if href != "" {
					linkText.WriteString(t)
				}
			}
		case html.CommentToken, html.DoctypeToken:
		}
	}
}

// inlineTag runs on within a line; any other tag separates words, so
// adjacent blocks do not glue together.
func inlineTag(tag string) bool {
	switch tag {
	case "a", "abbr", "b", "bdi", "bdo", "cite", "code", "data", "dfn", "em", "i", "kbd", "mark", "q", "s", "samp",
		"small", "span", "strong", "sub", "sup", "time", "u", "var", "wbr":
		return true
	}
	return false
}

func dropTag(tag string) bool {
	return tag == "script" || tag == "style" || tag == "noscript" || tag == "head"
}

func truncateRunes(s string, n int) string {
	if utf8.RuneCountInString(s) <= n {
		return s
	}
	i := 0
	for pos := range s {
		if i == n {
			return s[:pos]
		}
		i++
	}
	return s
}

type kv struct {
	k string
	v any
}

// orderedJSON keeps the envelope's key order and leaves URLs unescaped, so
// a link reads in the conversation exactly as a later fetch requests it.
type orderedJSON []kv

func (o orderedJSON) String() string {
	var b strings.Builder
	b.WriteByte('{')
	for i, p := range o {
		if i > 0 {
			b.WriteString(", ")
		}
		b.WriteString(compactJSON(p.k))
		b.WriteString(": ")
		b.WriteString(compactJSON(p.v))
	}
	b.WriteByte('}')
	return b.String()
}

func compactJSON(v any) string {
	var b strings.Builder
	enc := json.NewEncoder(&b)
	enc.SetEscapeHTML(false)
	if err := enc.Encode(v); err != nil {
		return `""`
	}
	return strings.TrimSuffix(b.String(), "\n")
}
