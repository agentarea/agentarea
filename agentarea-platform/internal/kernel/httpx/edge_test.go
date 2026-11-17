package httpx

import (
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"testing"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx/wirejson"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
)

// keptHeaders are the headers capture.py recorded.
var keptHeaders = []string{
	"content-type", "www-authenticate", "retry-after", "allow", "access-control-allow-origin",
	"access-control-allow-methods", "access-control-allow-headers", "access-control-max-age",
	"access-control-allow-credentials", "vary",
}

type goldenCase struct {
	Name    string `json:"name"`
	Request struct {
		Method  string            `json:"method"`
		Path    string            `json:"path"`
		Headers map[string]string `json:"headers"`
		JSON    json.RawMessage   `json:"json"`
		Content *string           `json:"content"`
		Stream  []string          `json:"stream"`
	} `json:"request"`
	Status  int               `json:"status"`
	Headers map[string]string `json:"headers"`
	Body    string            `json:"body"`
}

func loadCases(t *testing.T, name string) []goldenCase {
	t.Helper()
	raw, err := os.ReadFile("testdata/" + name)
	if err != nil {
		t.Fatal(err)
	}
	var cases []goldenCase
	if err := json.Unmarshal(raw, &cases); err != nil {
		t.Fatal(err)
	}
	return cases
}

type sqlState string

func (s sqlState) Error() string    { return "integrity" }
func (s sqlState) SQLState() string { return string(s) }

func raised(t *testing.T) map[string]error {
	t.Helper()
	detail := ""
	for _, c := range loadCases(t, "problems.json") {
		if c.Name == "raise_app_custom" {
			var body struct{ Detail string }
			if err := json.Unmarshal([]byte(c.Body), &body); err != nil {
				t.Fatal(err)
			}
			detail = body.Detail
		}
	}
	return map[string]error{
		"bad_request":       BadRequest("Name must not be empty"),
		"app_default":       NewError(500, CodeInternal, ""),
		"not_found_default": NotFound(""),
		"conflict":          Conflict("Slug already taken"),
		"permission_denied": Forbidden("Only admins may do this"),
		"auth_default":      Unauthorized("Missing bearer token"),
		"auth_own_header":   Unauthorized("Expired").WithHeader("WWW-Authenticate", `Bearer error="invalid_token"`),
		"app_custom": NewTitledError(418, "teapot", "Custom Title", detail).
			With("targets", []string{"b", "a"}).
			With("amount", wirejson.Float(10.0)).
			With("ratio", wirejson.Float(0.1)).
			With("big", wirejson.Float(1e16)).
			With("small", wirejson.Float(1e-05)).
			With("huge", wirejson.Float(1.5e300)).
			With("count", 3).
			With("none", nil).
			With("flag", true).
			With("nested", wirejson.Object{{Key: "z", Value: 1}, {Key: "a", Value: []any{wirejson.Float(1.5), "x"}}}),
		"budget_cap": NewError(402, "budget_cap_exceeded", "Monthly budget cap of 5.00 USD reached").
			With("current_mtd_usd", wirejson.Float(5.25)).
			With("cap_usd", wirejson.Float(5.0)).
			With("currency", "USD").
			With("workspace_id", "ws-1").
			With("agent_id", nil),
		"unknown_status": NewError(599, "odd", "odd"),
		"ws_access_denied": &scope.AccessDeniedError{
			ResourceType: "agent", ResourceID: "a-1", CurrentWorkspace: "ws-1", ResourceWorkspace: "ws-2", UserID: "u-1",
		},
		"ws_missing_context":       &scope.MissingContextError{Field: "workspace_id"},
		"ws_invalid_jwt":           Unauthorized("Invalid or missing authentication token"),
		"ws_not_found":             NotFound("The requested agent does not exist"),
		"builtin_permission":       &PermissionError{Msg: "Read-only resource"},
		"builtin_permission_empty": &PermissionError{},
		"http_404":                 HTTPError(404, "Task not found"),
		"http_429":                 HTTPError(429, "Rate limit exceeded").WithHeader("Retry-After", "7"),
		"http_no_detail":           HTTPError(503, ""),
		"integrity_unique":         sqlState("23505"),
		"integrity_fk":             sqlState("23503"),
		"integrity_not_null":       sqlState("23502"),
		"unhandled":                errors.New("boom"),
	}
}

func writeJSON(w http.ResponseWriter, v any) error {
	body, err := wirejson.Marshal(v, wirejson.Compact)
	if err != nil {
		return err
	}
	w.Header().Set("Content-Type", "application/json")
	_, err = w.Write(body)
	return err
}

// readJSONBody is FastAPI's body read for a JSON route: missing, unparsable,
// then the decoded value.
func readJSONBody(r *http.Request) (any, error) {
	body, err := io.ReadAll(r.Body)
	if err != nil {
		return nil, err
	}
	if len(body) == 0 {
		return nil, Validation(Missing("body"))
	}
	if !isJSON(r.Header.Get("Content-Type")) {
		return nil, Validation(DictType("body"))
	}
	if err := CheckJSONBody(body); err != nil {
		return nil, err
	}
	return wirejson.Unmarshal(body)
}

// validateItem is the test's stand-in for the Item model of capture.py.
func validateItem(v any) error {
	obj, ok := v.(wirejson.Object)
	if !ok {
		return Validation(ModelAttributesType("body"))
	}
	var errs []FieldError
	known := map[string]bool{"name": true, "count": true, "kind": true, "ratio": true, "tags": true, "nested": true, "owner": true}
	for _, field := range []string{"name", "count", "kind"} {
		if _, ok := obj.Get(field); !ok {
			errs = append(errs, Missing("body", field))
		}
	}
	if len(errs) > 0 {
		return Validation(errs...)
	}
	name, _ := obj.Get("name")
	if s, ok := name.(string); ok {
		switch n := len([]rune(s)); {
		case n < 1:
			errs = append(errs, StringTooShort(1, "body", "name"))
		case n > 5:
			errs = append(errs, StringTooLong(5, "body", "name"))
		}
	}
	count, _ := obj.Get("count")
	switch c := count.(type) {
	case string:
		if _, fe := ValidateInt(c, IntBounds{Ge: 0, HasGe: true, Le: 10, HasLe: true}, "body", "count"); fe != nil {
			errs = append(errs, *fe)
		}
	case json.Number:
		if _, fe := ValidateInt(c.String(), IntBounds{Ge: 0, HasGe: true, Le: 10, HasLe: true}, "body", "count"); fe != nil {
			errs = append(errs, *fe)
		}
	}
	kind, _ := obj.Get("kind")
	if k, _ := kind.(string); k != "a" && k != "b" {
		errs = append(errs, LiteralError([]string{"a", "b"}, "body", "kind"))
	}
	if ratio, ok := obj.Get("ratio"); ok {
		if s, isStr := ratio.(string); isStr {
			if _, ok := ParseFloat(s); !ok {
				errs = append(errs, FloatParsing("body", "ratio"))
			}
		}
	}
	if tags, ok := obj.Get("tags"); ok {
		for i, tag := range tags.([]any) {
			if _, isStr := tag.(string); !isStr {
				errs = append(errs, StringType("body", "tags", i))
			}
		}
	}
	if nested, ok := obj.Get("nested"); ok {
		x, _ := nested.(wirejson.Object).Get("x")
		if s, isStr := x.(string); isStr {
			if _, fe := ValidateInt(s, IntBounds{}, "body", "nested", "x"); fe != nil {
				errs = append(errs, *fe)
			}
		}
	}
	if owner, ok := obj.Get("owner"); ok {
		if _, fe := ValidateUUID(owner.(string), "body", "owner"); fe != nil {
			errs = append(errs, *fe)
		}
	}
	for _, m := range obj {
		if !known[m.Key] {
			errs = append(errs, ExtraForbidden("body", m.Key))
		}
	}
	return Validation(errs...)
}

func testEdge(t *testing.T, cors CORSConfig) http.Handler {
	t.Helper()
	errs := NewErrors("https://api.example.test/", nil)
	mux := NewMux(errs)
	cases := raised(t)
	mux.Handle("GET /raise/{name}", errs.Handler(func(_ http.ResponseWriter, r *http.Request) error {
		if r.PathValue("name") == "panic" {
			panic("boom")
		}
		return cases[r.PathValue("name")]
	}))
	mux.Handle("POST /items", errs.Handler(func(w http.ResponseWriter, r *http.Request) error {
		v, err := readJSONBody(r)
		if err != nil {
			return err
		}
		if err := validateItem(v); err != nil {
			return err
		}
		return writeJSON(w, v)
	}))
	mux.Handle("GET /items/{item_id}", errs.Handler(func(w http.ResponseWriter, r *http.Request) error {
		var fes []FieldError
		id, fe := ValidateUUID(r.PathValue("item_id"), "path", "item_id")
		if fe != nil {
			fes = append(fes, *fe)
		}
		q := Query(r.URL.RawQuery)
		flag := false
		if v, ok := last(q, "flag"); ok {
			b, ok := ParseBool(v)
			if !ok {
				fes = append(fes, BoolParsing("query", "flag"))
			}
			flag = b
		}
		limit := int64(10)
		if v, ok := last(q, "limit"); ok {
			n, fe := ValidateInt(v, IntBounds{Ge: 1, HasGe: true}, "query", "limit")
			if fe != nil {
				fes = append(fes, *fe)
			}
			limit = n
		}
		if err := Validation(fes...); err != nil {
			return err
		}
		return writeJSON(w, wirejson.Object{{Key: "id", Value: id}, {Key: "flag", Value: flag}, {Key: "limit", Value: limit}})
	}))
	mux.Handle("GET /page", errs.Handler(func(w http.ResponseWriter, r *http.Request) error {
		p, err := ParsePagination(Query(r.URL.RawQuery))
		if err != nil {
			return err
		}
		var items []wirejson.Object
		for i := p.Offset(); i < p.Offset()+2; i++ {
			items = append(items, wirejson.Object{{Key: "n", Value: i}, {Key: "f", Value: wirejson.Float(1)}, {Key: "s", Value: "é"}})
		}
		page := NewPage(items, 5, p)
		page.HasNext = true
		return writeJSON(w, page)
	}))
	mux.Handle("POST /echo", errs.Handler(func(w http.ResponseWriter, r *http.Request) error {
		if _, err := readJSONBody(r); err != nil {
			return err
		}
		return writeJSON(w, wirejson.Object{{Key: "ok", Value: true}})
	}))
	return Chain(Config{MaxBody: 512, CORS: cors}, errs, nil, mux)
}

func send(h http.Handler, c goldenCase) *httptest.ResponseRecorder {
	var body io.Reader
	length := int64(0)
	switch {
	case c.Request.JSON != nil:
		raw, _ := wirejson.Unmarshal(c.Request.JSON)
		b, _ := wirejson.Marshal(raw, wirejson.Dumps)
		body, length = strings.NewReader(string(b)), int64(len(b))
	case c.Request.Content != nil:
		body, length = strings.NewReader(*c.Request.Content), int64(len(*c.Request.Content))
	case c.Request.Stream != nil:
		body, length = io.MultiReader(stringsReaders(c.Request.Stream)...), -1
	}
	req := httptest.NewRequest(c.Request.Method, c.Request.Path, body)
	req.ContentLength = length
	if c.Request.JSON != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	for k, v := range c.Request.Headers {
		req.Header.Set(k, v)
	}
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)
	return rec
}

func stringsReaders(chunks []string) []io.Reader {
	out := make([]io.Reader, len(chunks))
	for i, c := range chunks {
		out[i] = strings.NewReader(c)
	}
	return out
}

func checkCases(t *testing.T, h http.Handler, cases []goldenCase) {
	t.Helper()
	if len(cases) == 0 {
		t.Fatal("no cases")
	}
	for _, c := range cases {
		t.Run(c.Name, func(t *testing.T) {
			rec := send(h, c)
			if rec.Code != c.Status {
				t.Errorf("status %d, Python %d", rec.Code, c.Status)
			}
			if got := rec.Body.String(); got != c.Body {
				t.Errorf("body\n got %s\nwant %s", got, c.Body)
			}
			for _, k := range keptHeaders {
				want, has := c.Headers[k]
				got := rec.Header().Values(k)
				switch {
				case has && (len(got) != 1 || got[0] != want):
					t.Errorf("header %s = %q, Python %q", k, got, want)
				case !has && len(got) > 0:
					t.Errorf("header %s = %q, Python sends none", k, got)
				}
			}
		})
	}
}

func TestProblemsMatchPython(t *testing.T) {
	checkCases(t, testEdge(t, CORSConfig{Origins: []string{"*"}, Methods: []string{"*"}, Headers: []string{"*"}, MaxAge: 3600}),
		loadCases(t, "problems.json"))
}

func TestCORSWildcardMatchesPython(t *testing.T) {
	checkCases(t, testEdge(t, CORSConfig{Origins: []string{"*"}, Methods: []string{"*"}, Headers: []string{"*"}, MaxAge: 3600}),
		loadCases(t, "cors_wildcard.json"))
}

func TestCORSListedMatchesPython(t *testing.T) {
	checkCases(t, testEdge(t, CORSConfig{
		Origins: []string{"https://app.example.test"}, OriginRegex: `https://.*\.preview\.example\.test`,
		Methods: []string{"GET", "POST"}, Headers: []string{"Authorization", "X-Custom"}, MaxAge: 600,
	}), loadCases(t, "cors_listed.json"))
}

func TestPanicIsTheCatchAllOutsideCORS(t *testing.T) {
	h := testEdge(t, CORSConfig{Origins: []string{"*"}, Methods: []string{"*"}, Headers: []string{"*"}, MaxAge: 3600})
	req := httptest.NewRequest("GET", "/raise/panic", nil)
	req.Header.Set("Origin", "https://x.example")
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)
	want := `{"type":"about:blank","title":"Internal Server Error","status":500,"code":"internal_error","detail":"Internal Server Error"}`
	if rec.Code != 500 || rec.Body.String() != want || rec.Header().Get("Access-Control-Allow-Origin") != "" {
		t.Fatalf("%d %q %v", rec.Code, rec.Body.String(), rec.Header())
	}
}

func TestRouteContract(t *testing.T) {
	ok := []Route{
		{Method: "GET", Path: "/v1/workspaces/{workspace}/agents", OperationID: "list_agents", ResolvesWorkspace: true},
		{Method: "POST", Path: "/a2a/{agent_id}/rpc", OperationID: "rpc", ResolvesWorkspace: true, BindsWorkspace: true},
		{Method: "GET", Path: "/health", OperationID: "health"},
	}
	if err := CheckRouteContract(ok); err != nil {
		t.Fatal(err)
	}
	bad := append(ok,
		Route{Method: "GET", Path: "/v1/agents", OperationID: "list_agents", ResolvesWorkspace: true})
	want := "routes resolve a workspace context but neither carry '{workspace}' in their path nor bind one before it: GET /v1/agents\n" +
		"operation ids are not unique: list_agents -> ['GET /v1/workspaces/{workspace}/agents', 'GET /v1/agents']"
	if err := CheckRouteContract(bad); err == nil || err.Error() != want {
		t.Fatalf("got %v", err)
	}
}
