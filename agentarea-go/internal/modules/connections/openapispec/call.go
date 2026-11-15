package openapispec

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"sort"
	"strings"
	"unicode/utf8"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx/wirejson"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/netguard"
)

// ResultMaxBytes is _RESULT_MAX_BYTES: a successful result's text cap.
const ResultMaxBytes = 64 * 1024

// MaxResponseBytes bounds the response read into memory.
const MaxResponseBytes = 32 << 20

// Request is one operation call: the connection's resolved parts and the agent's arguments.
type Request struct {
	Op Operation
	// BaseTemplate is the stored base URL (placeholders kept): the one logged.
	BaseTemplate string
	// BaseURL has its URL variables filled: it carries credentials.
	BaseURL string
	Headers map[string]string
	// Query is the connection's configured parameters; they win over the agent's.
	Query map[string]string
	Args  map[string]any
}

// Result is what OpenAPITool.execute returns.
type Result struct {
	Success bool
	Result  string
	Error   string
	// StatusCode is 0 when no response came back.
	StatusCode int
	// Body is the decoded (transformed) JSON response, untruncated, for the meter.
	Body any
}

func failed(msg string) Result { return Result{Error: msg} }

// strValue is Python's str() of an argument.
func strValue(v any) string { return text(v) }

// QuoteAll is urllib.parse.quote(s, safe=""): only unreserved bytes stay.
func QuoteAll(s string) string {
	return strings.ReplaceAll(url.QueryEscape(s), "+", "%20")
}

// queryValues is httpx's encoding of a params value.
func queryValues(v any) []string {
	switch t := v.(type) {
	case []any:
		out := make([]string, 0, len(t))
		for _, x := range t {
			out = append(out, queryValues(x)...)
		}
		return out
	case bool:
		if t {
			return []string{"true"}
		}
		return []string{"false"}
	case nil:
		return []string{""}
	}
	return []string{strValue(v)}
}

// Build is the request OpenAPITool._call sends; err is a refusal of the
// arguments (Invalid request body, an unsupported content type) as its message.
func Build(ctx context.Context, r Request) (*http.Request, string, error) {
	path := r.Op.Path
	for _, p := range r.Op.Parameters {
		if p.InPath() {
			if v, ok := r.Args[p.Name]; ok {
				path = strings.ReplaceAll(path, "{"+p.Name+"}", QuoteAll(strValue(v)))
			}
		}
	}
	urlTemplate := strings.TrimRight(r.BaseTemplate, "/") + path
	target := strings.TrimRight(r.BaseURL, "/") + path

	type kv struct{ k, v string }
	var query []kv
	seen := map[string]int{}
	setQuery := func(k string, vs []string) {
		if i, ok := seen[k]; ok {
			kept := query[:i]
			for _, q := range query[i:] {
				if q.k != k {
					kept = append(kept, q)
				}
			}
			query = kept
		}
		seen[k] = len(query)
		for _, v := range vs {
			query = append(query, kv{k, v})
		}
	}
	for _, p := range r.Op.Parameters {
		if p.InQuery() {
			if v, ok := r.Args[p.Name]; ok {
				setQuery(p.Name, queryValues(v))
			}
		}
	}
	for _, k := range sortedKeys(r.Query) {
		setQuery(k, []string{r.Query[k]})
	}
	headers := http.Header{}
	for k, v := range r.Headers {
		headers.Set(k, v)
	}
	for _, p := range r.Op.Parameters {
		if p.InHeader() {
			if v, ok := r.Args[p.Name]; ok {
				headers.Set(p.Name, strValue(v))
			}
		}
	}
	var body io.Reader
	if rb := r.Op.RequestBody; rb != nil {
		if raw, ok := r.Args["body"]; ok {
			switch {
			case rb.ContentType == "application/json":
				shaped, err := ApplyRequestTransform(r.Op.RequestTransform, raw)
				if err != nil {
					return nil, urlTemplate, errorf("Invalid request body: %s", err.Error())
				}
				b, err := json.Marshal(shaped)
				if err != nil {
					return nil, urlTemplate, errorf("Invalid request body: %s", err.Error())
				}
				body = bytes.NewReader(b)
				headers.Set("Content-Type", "application/json")
			case strings.HasPrefix(rb.ContentType, "text/"):
				body = strings.NewReader(strValue(raw))
			default:
				return nil, urlTemplate, errorf("Unsupported request body content type: %s", rb.ContentType)
			}
		}
	}
	if len(query) > 0 {
		var b strings.Builder
		for i, q := range query {
			if i > 0 {
				b.WriteByte('&')
			}
			b.WriteString(url.QueryEscape(q.k))
			b.WriteByte('=')
			b.WriteString(url.QueryEscape(q.v))
		}
		if strings.Contains(target, "?") {
			target += "&" + b.String()
		} else {
			target += "?" + b.String()
		}
	}
	req, err := http.NewRequestWithContext(ctx, r.Op.Method, target, body)
	if err != nil {
		return nil, urlTemplate, errorf("Failed to build request path: %s", err.Error())
	}
	req.Header = headers
	return req, urlTemplate, nil
}

func sortedKeys(m map[string]string) []string {
	out := make([]string, 0, len(m))
	for k := range m {
		out = append(out, k)
	}
	sort.Strings(out)
	return out
}

// Do sends req through client (pinned, no redirects) and reads the answer
// as OpenAPITool._call does, payments aside: a 402 is a failed call here.
func Do(client *http.Client, req *http.Request, op Operation) Result {
	resp, err := client.Do(req)
	if err != nil {
		switch {
		case errors.Is(err, netguard.ErrUnsafe):
			return failed("Destination is not an allowed address")
		case isTimeout(err):
			return failed("HTTP timeout: " + err.Error())
		}
		return failed("HTTP request error: " + err.Error())
	}
	defer func() { _ = resp.Body.Close() }()
	raw, err := io.ReadAll(io.LimitReader(resp.Body, MaxResponseBytes+1))
	status := resp.StatusCode
	if err != nil {
		return failed("HTTP request error: " + err.Error())
	}
	if len(raw) > MaxResponseBytes {
		return Result{Error: fmt.Sprintf("HTTP %d: the response is larger than %d bytes", status, MaxResponseBytes), StatusCode: status}
	}
	if status < 200 || status >= 300 {
		return Result{Error: fmt.Sprintf("HTTP %d: %s", status, firstRunes(decoded(raw), 500)), StatusCode: status}
	}
	if status == http.StatusNoContent || len(raw) == 0 {
		return success("", status, nil)
	}
	ct := resp.Header.Get("Content-Type")
	isXML := strings.Contains(ct, "/xml") || strings.Contains(ct, "+xml")
	var body any
	var result string
	switch {
	case strings.Contains(ct, "application/json"):
		parsed, err := wirejson.Unmarshal(raw)
		if err != nil {
			return Result{Error: "Failed to decode response: " + err.Error(), StatusCode: status}
		}
		if body, err = ApplyResponseTransform(op.ResponseTransform, parsed); err != nil {
			return Result{Error: "Failed to decode response: " + err.Error(), StatusCode: status}
		}
		if result, err = dumps(body); err != nil {
			return Result{Error: "Failed to decode response: " + err.Error(), StatusCode: status}
		}
	case isXML && len(op.ResponseTransform) > 0:
		var err error
		if body, err = ApplyResponseTransform(op.ResponseTransform, decoded(raw)); err != nil {
			return Result{Error: "Failed to decode response: " + err.Error(), StatusCode: status}
		}
		if result, err = dumps(body); err != nil {
			return Result{Error: "Failed to decode response: " + err.Error(), StatusCode: status}
		}
	case strings.HasPrefix(ct, "text/") || strings.Contains(ct, "text") || isXML:
		result = decoded(raw)
	default:
		result = fmt.Sprintf("<binary %d bytes, content-type=%s>", len(raw), ct)
	}
	if op.ErrorPath != "" && body != nil {
		if vendor, ok := JSONPath(body, op.ErrorPath); ok && vendor != nil {
			detail, _ := dumps(vendor)
			return Result{Error: fmt.Sprintf("HTTP %d with an error: %s", status, firstRunes(detail, 500)), StatusCode: status}
		}
	}
	return success(result, status, body)
}

func success(result string, status int, body any) Result {
	if n := len(result); n > ResultMaxBytes {
		result = strings.ToValidUTF8(result[:ResultMaxBytes], "�") + fmt.Sprintf("...[truncated, original %d bytes]", n)
	}
	return Result{Success: true, Result: result, StatusCode: status, Body: body}
}

func isTimeout(err error) bool {
	var t interface{ Timeout() bool }
	return errors.Is(err, context.DeadlineExceeded) || errors.Is(err, os.ErrDeadlineExceeded) || (errors.As(err, &t) && t.Timeout())
}

func decoded(raw []byte) string {
	if utf8.Valid(raw) {
		return string(raw)
	}
	return strings.ToValidUTF8(string(raw), "�")
}

func firstRunes(s string, n int) string {
	i := 0
	for pos := range s {
		if i == n {
			return s[:pos]
		}
		i++
	}
	return s
}

// dumps is json.dumps(v, ensure_ascii=False): ", " and ": " between items.
func dumps(v any) (string, error) {
	raw, err := wirejson.Marshal(v, wirejson.Compact)
	if err != nil {
		return "", err
	}
	var b strings.Builder
	inString, escaped := false, false
	for _, c := range string(raw) {
		b.WriteRune(c)
		switch {
		case inString:
			switch {
			case escaped:
				escaped = false
			case c == '\\':
				escaped = true
			case c == '"':
				inString = false
			}
		case c == '"':
			inString = true
		case c == ',' || c == ':':
			b.WriteByte(' ')
		}
	}
	return b.String(), nil
}
