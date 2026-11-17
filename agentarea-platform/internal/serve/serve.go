// Package serve assembles the serve role's HTTP edge: one chi router from
// kernel/httpx behind the middleware chain, the root and health routes, and
// the seam where each module mounts its routes. A path nothing mounted is
// a 404 problem.
package serve

import (
	"context"
	"errors"
	"fmt"
	"io/fs"
	"log/slog"
	"net/http"
	"time"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx/wirejson"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/lifecycle"
	"github.com/agentarea/agentarea/agentarea-platform/internal/serve/apidocs"
	"github.com/agentarea/agentarea/agentarea-platform/internal/serve/static"
)

// Routes is what a module mounts on. A generated server goes on the chi
// tree, its errors rendered by Errors:
//
//	srv := projects.NewStrictHandlerWithOptions(impl, nil, projects.StrictHTTPServerOptions{
//		RequestErrorHandlerFunc: rt.Errors.Write, ResponseErrorHandlerFunc: rt.Errors.Write})
//	projects.HandlerWithOptions(srv, projects.ChiServerOptions{
//		BaseRouter: rt.Mux.Chi(), ErrorHandlerFunc: rt.Errors.Write})
//
// A route outside the spec (a {x:path} route, a WebSocket, a mount) goes on
// Mux with Handle("METHOD /path", h).
type Routes struct {
	Mux    *httpx.Mux
	Errors *httpx.Errors
	// MaxBody is the edge's body limit, for a handler that reads a body itself.
	MaxBody int64
}

// Module is one module's HTTP surface.
type Module struct {
	Name string
	// Errors maps the module's typed errors; nil when it has none.
	Errors httpx.ErrorMapper
	Mount  func(rt Routes) error
}

// Options are the assembly's inputs that do not come from the environment.
type Options struct {
	// Version is the build's version, reported by GET /health.
	Version string
	// Now is the clock of GET /health; nil is time.Now.
	Now func() time.Time
	// Checks gate GET /readyz.
	Checks []lifecycle.Checker
	// OpenAPI is the document served at /openapi.json, with Swagger UI at
	// /docs and ReDoc at /redoc; nil serves none of them.
	OpenAPI []byte
}

// Assembly is the built edge.
type Assembly struct {
	// Handler is the router behind the middleware chain.
	Handler http.Handler
	// Mux is the router, for listing what is mounted.
	Mux *httpx.Mux
}

// Assemble builds the edge from the modules, in order.
func Assemble(cfg Config, opts Options, log *slog.Logger, modules ...Module) (*Assembly, error) {
	var mappers []httpx.ErrorMapper
	for _, m := range modules {
		if m.Errors != nil {
			mappers = append(mappers, m.Errors)
		}
	}
	errs := httpx.NewErrors(cfg.Edge.APIURL, log, mappers...)
	mux := httpx.NewMux(errs)
	mux.Chi().Use(routeLabel)
	rt := Routes{Mux: mux, Errors: errs, MaxBody: cfg.Edge.MaxBody}
	var problems []error
	if err := mount(rt, rootRoutes(opts)); err != nil {
		problems = append(problems, fmt.Errorf("root routes: %w", err))
	}
	for _, m := range modules {
		if m.Mount == nil {
			problems = append(problems, fmt.Errorf("module %s: no Mount", m.Name))
			continue
		}
		if err := mount(rt, m.Mount); err != nil {
			problems = append(problems, fmt.Errorf("module %s: %w", m.Name, err))
		}
	}
	if err := errors.Join(problems...); err != nil {
		return nil, err
	}
	return &Assembly{Handler: instrumented(httpx.Chain(cfg.Edge, errs, log, mux)), Mux: mux}, nil
}

// mount turns a registration panic (a malformed pattern, chi's duplicate
// wildcard) into an error naming the module.
func mount(rt Routes, f func(Routes) error) (err error) {
	defer func() {
		if v := recover(); v != nil {
			err = fmt.Errorf("%v", v)
		}
	}()
	return f(rt)
}

// Health endpoints of the process, for probes; GET /health is the API's.
const (
	LivePath  = "/livez"
	ReadyPath = "/readyz"
)

const readyCheckTimeout = 2 * time.Second

const htmlType = "text/html; charset=utf-8"

// rootRoutes are main.py's own routes (GET /, GET /health), FastAPI's
// /openapi.json, /docs and /redoc, and the probes.
func rootRoutes(opts Options) func(Routes) error {
	now := opts.Now
	if now == nil {
		now = time.Now
	}
	return func(rt Routes) error {
		rt.Mux.Handle("GET /", jsonHandler(func(*http.Request) (int, wirejson.Object) {
			return http.StatusOK, wirejson.Object{{Key: "message", Value: "AgentArea API is running."}}
		}))
		// main.py registers /health twice; the first, without connections, is served.
		rt.Mux.Handle("GET /health", jsonHandler(func(*http.Request) (int, wirejson.Object) {
			return http.StatusOK, wirejson.Object{
				{Key: "status", Value: "healthy"},
				{Key: "version", Value: opts.Version},
				{Key: "timestamp", Value: isoformat(now())},
			}
		}))
		if opts.OpenAPI != nil {
			rt.Mux.Handle("GET /openapi.json", rawHandler("application/json", opts.OpenAPI))
			rt.Mux.Handle("GET /docs", rawHandler(htmlType, apidocs.Swagger()))
			rt.Mux.Handle("GET /docs/oauth2-redirect", rawHandler(htmlType, apidocs.OAuth2Redirect()))
			rt.Mux.Handle("GET /redoc", rawHandler(htmlType, apidocs.ReDoc()))
		}
		files := staticFiles(rt.Errors, static.FS())
		rt.Mux.Handle("GET /static/{path...}", files)
		rt.Mux.Handle("HEAD /static/{path...}", files)
		rt.Mux.Handle("GET "+LivePath, jsonHandler(func(*http.Request) (int, wirejson.Object) {
			return http.StatusOK, wirejson.Object{{Key: "status", Value: "ok"}}
		}))
		rt.Mux.Handle("GET "+ReadyPath, jsonHandler(func(r *http.Request) (int, wirejson.Object) {
			ctx, cancel := context.WithTimeout(r.Context(), readyCheckTimeout)
			defer cancel()
			var failed wirejson.Object
			for _, c := range opts.Checks {
				if err := c.Check(ctx); err != nil {
					failed = append(failed, wirejson.Member{Key: c.Name(), Value: err.Error()})
				}
			}
			if len(failed) > 0 {
				return http.StatusServiceUnavailable, wirejson.Object{{Key: "status", Value: "unavailable"}, {Key: "failed", Value: failed}}
			}
			return http.StatusOK, wirejson.Object{{Key: "status", Value: "ok"}}
		}))
		return nil
	}
}

// staticFiles is main.py's StaticFiles mount: a regular file of fsys, else a 404.
func staticFiles(errs *httpx.Errors, fsys fs.FS) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		name := r.PathValue("path")
		if st, err := fs.Stat(fsys, name); !fs.ValidPath(name) || err != nil || !st.Mode().IsRegular() {
			errs.Write(w, r, httpx.NotFound("Not Found"))
			return
		}
		http.ServeFileFS(w, r, fsys, name)
	})
}

// isoformat is Python's naive datetime.isoformat(): microseconds only when
// non-zero.
func isoformat(t time.Time) string {
	if t.Nanosecond()/1000 == 0 {
		return t.Format("2006-01-02T15:04:05")
	}
	return t.Format("2006-01-02T15:04:05.000000")
}

func rawHandler(contentType string, body []byte) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Content-Type", contentType)
		_, _ = w.Write(body)
	})
}

func jsonHandler(f func(r *http.Request) (int, wirejson.Object)) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		status, body := f(r)
		b, err := wirejson.Marshal(body, wirejson.Compact)
		if err != nil {
			http.Error(w, http.StatusText(http.StatusInternalServerError), http.StatusInternalServerError)
			return
		}
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(status)
		_, _ = w.Write(b)
	})
}
