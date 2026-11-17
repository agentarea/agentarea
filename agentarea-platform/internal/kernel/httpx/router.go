package httpx

import (
	"cmp"
	"fmt"
	"net/http"
	"regexp"
	"slices"
	"strings"

	"github.com/go-chi/chi/v5"
)

// Mux is the API's router (decision 13: chi, which accepts the route pairs
// FastAPI does where net/http's ServeMux panics). An unknown path and a
// known path with another method answer Starlette's problems: 404 and 405
// http_error, the 405 with Allow.
type Mux struct {
	chi   *chi.Mux
	errs  *Errors
	order map[string][]string
}

// NewMux builds an empty router whose 404 and 405 are rendered by errs.
func NewMux(errs *Errors) *Mux {
	m := &Mux{chi: chi.NewRouter(), errs: errs, order: map[string][]string{}}
	m.chi.NotFound(func(w http.ResponseWriter, r *http.Request) {
		errs.Write(w, r, HTTPError(http.StatusNotFound, ""))
	})
	m.chi.MethodNotAllowed(func(w http.ResponseWriter, r *http.Request) {
		errs.Write(w, r, HTTPError(http.StatusMethodNotAllowed, "").WithHeader("Allow", m.allow(r)))
	})
	return m
}

// ServeHTTP routes r.
func (m *Mux) ServeHTTP(w http.ResponseWriter, r *http.Request) { m.chi.ServeHTTP(w, r) }

// Handle registers h for "METHOD /path" in net/http's syntax; a trailing
// "{name...}" matches the rest of the path. h reads parameters with
// r.PathValue.
func (m *Mux) Handle(pattern string, h http.Handler) {
	method, path, err := splitPattern(pattern)
	if err != nil {
		panic(err)
	}
	chiPath, names, rest := chiPattern(path)
	m.chi.Method(method, chiPath, withPathValues(names, rest, h))
	m.order[chiPath] = append(m.order[chiPath], method)
}

// Group is a Router that registers under prefix.
func (m *Mux) Group(prefix string) Router {
	return &group{m: m, prefix: strings.TrimRight(prefix, "/")}
}

type group struct {
	m      *Mux
	prefix string
}

func (g *group) Handle(pattern string, h http.Handler) {
	method, path, err := splitPattern(pattern)
	if err != nil {
		panic(err)
	}
	g.m.Handle(method+" "+g.prefix+path, h)
}

// allow is Starlette's Allow on a 405: the methods of the first route
// registered for the path. A path whose routes were registered on the chi
// tree directly (the generated servers) lists every method it has.
func (m *Mux) allow(r *http.Request) string {
	path := r.URL.RawPath
	if path == "" {
		path = r.URL.Path
	}
	var allowed []string
	pattern := ""
	for _, method := range []string{"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"} {
		rctx := chi.NewRouteContext()
		if m.chi.Match(rctx, method, path) {
			allowed = append(allowed, method)
			if pattern == "" {
				pattern = rctx.RoutePattern()
			}
		}
	}
	if order := m.order[pattern]; len(order) > 0 {
		return order[0]
	}
	return strings.Join(allowed, ", ")
}

// Chi exposes the tree for the generated chi servers (HandlerFromMux).
func (m *Mux) Chi() chi.Router { return m.chi }

func splitPattern(pattern string) (string, string, error) {
	method, path, ok := strings.Cut(pattern, " ")
	path = strings.TrimSpace(path)
	if !ok || method == "" || !strings.HasPrefix(path, "/") {
		return "", "", fmt.Errorf("route %q: pattern must be \"METHOD /path\"", pattern)
	}
	return method, path, nil
}

var restParam = regexp.MustCompile(`\{([A-Za-z_][A-Za-z0-9_]*)\.\.\.\}$`)

var pathParam = regexp.MustCompile(`\{([A-Za-z_][A-Za-z0-9_]*)\}`)

// chiPattern turns a net/http pattern into chi's: "{name...}" becomes "*".
func chiPattern(path string) (string, []string, string) {
	rest := ""
	if m := restParam.FindStringSubmatch(path); m != nil {
		rest = m[1]
		path = strings.TrimSuffix(path, m[0]) + "*"
	}
	var names []string
	for _, m := range pathParam.FindAllStringSubmatch(path, -1) {
		names = append(names, m[1])
	}
	return path, names, rest
}

func withPathValues(names []string, rest string, h http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		for _, n := range names {
			r.SetPathValue(n, chi.URLParam(r, n))
		}
		if rest != "" {
			r.SetPathValue(rest, chi.URLParam(r, "*"))
		}
		h.ServeHTTP(w, r)
	})
}

// ByHost serves a request whose Host hostHandler claims before any path
// route: the per-agent A2A host, inserted at position 0 in main.py.
func ByHost(claims func(host string) bool, hostHandler, next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		host := r.Host
		if h, _, ok := strings.Cut(host, ":"); ok && !strings.HasPrefix(host, "[") {
			host = h
		}
		if claims(strings.ToLower(host)) {
			hostHandler.ServeHTTP(w, r)
			return
		}
		next.ServeHTTP(w, r)
	})
}

// Route is what the route contract checks about one operation.
type Route struct {
	Method      string
	Path        string
	OperationID string
	// ResolvesWorkspace: the operation acts in a workspace context.
	ResolvesWorkspace bool
	// BindsWorkspace: the operation binds the workspace of the entity it
	// addresses before it resolves the context (an A2A agent, a runner).
	BindsWorkspace bool
}

// RouteContractError lists every route that breaks the contract, worded
// as route_contract.py words it.
type RouteContractError struct{ Msg string }

func (e *RouteContractError) Error() string { return e.Msg }

// CheckRouteContract is route_contract.py: an operation that resolves a
// workspace carries {workspace} in its path or binds one, and operation ids
// are unique. The error lists every offending route.
func CheckRouteContract(routes []Route) error {
	var unselected []string
	ops := map[string][]string{}
	for _, r := range routes {
		label := r.Method + " " + r.Path
		ops[r.OperationID] = append(ops[r.OperationID], label)
		if r.ResolvesWorkspace && !strings.Contains(r.Path, "{"+WorkspaceParam+"}") && !r.BindsWorkspace {
			unselected = append(unselected, label)
		}
	}
	var problems []string
	if len(unselected) > 0 {
		problems = append(problems, "routes resolve a workspace context but neither carry '{"+WorkspaceParam+
			"}' in their path nor bind one before it: "+strings.Join(unselected, "; "))
	}
	var dups []string
	for op, labels := range ops {
		if len(labels) > 1 {
			dups = append(dups, op+" -> ['"+strings.Join(labels, "', '")+"']")
		}
	}
	if len(dups) > 0 {
		slices.SortFunc(dups, cmp.Compare[string])
		problems = append(problems, "operation ids are not unique: "+strings.Join(dups, "; "))
	}
	if len(problems) > 0 {
		return &RouteContractError{Msg: strings.Join(problems, "\n")}
	}
	return nil
}

var (
	_ Router = (*Mux)(nil)
	_ Router = (*group)(nil)
)
