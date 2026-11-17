package serve

import (
	"net/http"

	"github.com/go-chi/chi/v5"
	"go.opentelemetry.io/contrib/instrumentation/net/http/otelhttp"
	"go.opentelemetry.io/otel/attribute"
	"go.opentelemetry.io/otel/trace"

	kobs "github.com/agentarea/agentarea/agentarea-platform/internal/kernel/obs"
)

// instrumented is FastAPIInstrumentor: a server span per request, continuing the caller's
// trace, and http.server.request.duration. Without telemetry the global providers are no-ops.
func instrumented(h http.Handler) http.Handler {
	return otelhttp.NewHandler(h, "http.server", otelhttp.WithSpanNameFormatter(func(_ string, r *http.Request) string {
		return r.Method
	}))
}

// routeLabel names the matched route on the span and the duration metric once chi has routed:
// "GET /v1/agents/{agent_id}", never the raw path.
func routeLabel(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		next.ServeHTTP(w, r)
		rc := chi.RouteContext(r.Context())
		if rc == nil {
			return
		}
		pattern := rc.RoutePattern()
		if pattern == "" {
			return
		}
		route := attribute.String(kobs.AttrHTTPRoute, pattern)
		span := trace.SpanFromContext(r.Context())
		span.SetName(r.Method + " " + pattern)
		span.SetAttributes(route)
		if l, ok := otelhttp.LabelerFromContext(r.Context()); ok {
			l.Add(route)
		}
	})
}
