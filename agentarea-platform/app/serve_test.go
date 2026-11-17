package app

import (
	"log/slog"
	"net/http"
	"regexp"
	"slices"
	"strings"
	"testing"

	"github.com/go-chi/chi/v5"

	"github.com/agentarea/agentarea/agentarea-platform/api/contract"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authz"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/config"
	"github.com/agentarea/agentarea/agentarea-platform/internal/serve"
)

// mounted is "METHOD /chi/pattern" of every route the serve role mounts.
func mounted(t *testing.T) map[string]bool {
	t.Helper()
	l := config.FromMap(nil)
	a, err := serve.Assemble(serve.LoadConfig(l), serve.Options{}, slog.New(slog.DiscardHandler), append(buildModules(newEdge(nil, authz.Admins{}), coreDeps{Lookup: mapLookup(nil)}).http(), slashRedirect())...)
	if err != nil || l.Err() != nil {
		t.Fatal(err, l.Err())
	}
	out := map[string]bool{}
	err = chi.Walk(a.Mux.Chi(), func(method, route string, _ http.Handler, _ ...func(http.Handler) http.Handler) error {
		out[method+" "+route] = true
		return nil
	})
	if err != nil {
		t.Fatal(err)
	}
	return out
}

// chiKey writes a contract route as chi lists it: "{x...}" is "*".
func chiKey(r contract.Route) string {
	return regexp.MustCompile(`\{\w+\.\.\.\}$`).ReplaceAllString(r.Pattern(), "*")
}

// TestContractRoutesNotYetMounted reports the Python routes the Go API does
// not serve yet, and the routes it serves that Python had not. It reports
// and does not fail: the list shrinks as modules are ported.
func TestContractRoutesNotYetMounted(t *testing.T) {
	routes, err := contract.LoadRoutes()
	if err != nil {
		t.Fatal(err)
	}
	have := mounted(t)
	known := map[string]bool{}
	var missing []string
	for _, r := range routes.Routes {
		key := chiKey(r)
		switch {
		case r.Host != nil:
			key = *r.Host + " " + key
		case r.Method == "*":
			key = "* " + r.Path + "/*"
		case r.Method == "WS":
			key = "GET " + r.Path
		}
		known[key] = true
		if !have[key] {
			missing = append(missing, key)
		}
	}
	var extra []string
	for k := range have {
		if !known[k] && !strings.HasSuffix(k, serve.LivePath) && !strings.HasSuffix(k, serve.ReadyPath) {
			extra = append(extra, k)
		}
	}
	slices.Sort(missing)
	slices.Sort(extra)
	t.Logf("contract routes mounted: %d of %d", len(routes.Routes)-len(missing), len(routes.Routes))
	t.Logf("not yet mounted (%d):\n  %s", len(missing), strings.Join(missing, "\n  "))
	if len(extra) > 0 {
		t.Logf("mounted but not in the contract (%d):\n  %s", len(extra), strings.Join(extra, "\n  "))
	}
}
