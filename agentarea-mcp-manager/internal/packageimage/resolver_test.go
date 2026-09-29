package packageimage

import (
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestResolveVersionAgainstPackageIndexes(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		switch strings.ToLower(r.URL.EscapedPath()) {
		case "/npm/@scope%2fserver":
			_, _ = w.Write([]byte(`{"dist-tags":{"latest":"2.3.4"},"versions":{"1.2.3":{},"2.3.4":{}}}`))
		case "/pypi/demo-pkg/json":
			_, _ = w.Write([]byte(`{"info":{"version":"4.5.6"}}`))
		case "/pypi/demo-pkg/3.2.1/json":
			_, _ = w.Write([]byte(`{"info":{"version":"3.2.1"}}`))
		default:
			t.Logf("unexpected path: path=%q escaped=%q raw=%q", r.URL.Path, r.URL.EscapedPath(), r.URL.RawPath)
			http.NotFound(w, r)
		}
	}))
	defer server.Close()
	resolver := &VersionResolver{NPMRegistryURL: server.URL + "/npm", PyPIURL: server.URL, Client: server.Client()}
	got, err := resolver.Resolve(t.Context(), Invocation{Ecosystem: EcosystemNPM, Package: "@scope/server"})
	if err != nil || got != "2.3.4" {
		t.Fatalf("npm latest = %q, error %v", got, err)
	}
	got, err = resolver.Resolve(t.Context(), Invocation{Ecosystem: EcosystemPyPI, Package: "Demo_Pkg"})
	if err != nil || got != "4.5.6" {
		t.Fatalf("pypi latest = %q, error %v", got, err)
	}
	got, err = resolver.Resolve(t.Context(), Invocation{Ecosystem: EcosystemPyPI, Package: "demo_pkg", Version: "3.2.1"})
	if err != nil || got != "3.2.1" {
		t.Fatalf("pypi exact = %q, error %v", got, err)
	}
}
