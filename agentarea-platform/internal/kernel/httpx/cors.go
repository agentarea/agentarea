package httpx

import (
	"io"
	"net/http"
	"regexp"
	"slices"
	"sort"
	"strconv"
	"strings"
)

// allMethods is what "*" expands to (starlette/middleware/cors.py ALL_METHODS).
func allMethods() []string {
	return []string{"DELETE", "GET", "HEAD", "OPTIONS", "PATCH", "POST", "PUT"}
}

func safelistedHeaders() []string {
	return []string{"Accept", "Accept-Language", "Content-Language", "Content-Type"}
}

type cors struct {
	allowOrigins     []string
	allowAllOrigins  bool
	allowAllHeaders  bool
	allowMethods     []string
	allowHeaders     []string
	originRegex      *regexp.Regexp
	explicitPreOrig  bool
	simpleHeaders    http.Header
	preflightHeaders http.Header
}

func newCORS(c CORSConfig) *cors {
	methods := c.Methods
	if slices.Contains(methods, "*") {
		methods = allMethods()
	}
	x := &cors{
		allowOrigins:    c.Origins,
		allowAllOrigins: slices.Contains(c.Origins, "*"),
		allowAllHeaders: slices.Contains(c.Headers, "*"),
		allowMethods:    methods,
	}
	if c.OriginRegex != "" {
		x.originRegex, _ = compileFull(c.OriginRegex)
	}
	x.explicitPreOrig = !x.allowAllOrigins
	x.simpleHeaders = http.Header{}
	if x.allowAllOrigins {
		x.simpleHeaders.Set("Access-Control-Allow-Origin", "*")
	}
	x.preflightHeaders = http.Header{}
	if x.explicitPreOrig {
		x.preflightHeaders.Set("Vary", "Origin")
	} else {
		x.preflightHeaders.Set("Access-Control-Allow-Origin", "*")
	}
	x.preflightHeaders.Set("Access-Control-Allow-Methods", strings.Join(methods, ", "))
	x.preflightHeaders.Set("Access-Control-Max-Age", strconv.Itoa(c.MaxAge))
	set := map[string]bool{}
	for _, h := range safelistedHeaders() {
		set[h] = true
	}
	for _, h := range c.Headers {
		set[h] = true
	}
	headers := make([]string, 0, len(set))
	for h := range set {
		headers = append(headers, h)
	}
	sort.Strings(headers)
	if len(headers) > 0 && !x.allowAllHeaders {
		x.preflightHeaders.Set("Access-Control-Allow-Headers", strings.Join(headers, ", "))
	}
	for _, h := range headers {
		x.allowHeaders = append(x.allowHeaders, strings.ToLower(h))
	}
	return x
}

func (x *cors) allowedOrigin(origin string) bool {
	if x.allowAllOrigins {
		return true
	}
	if x.originRegex != nil && x.originRegex.MatchString(origin) {
		return true
	}
	return slices.Contains(x.allowOrigins, origin)
}

// CORS is Starlette's CORSMiddleware with allow_credentials=False: a
// preflight is answered here, a request with an Origin gets the simple
// headers on whatever it answers (except the catch-all 500, see Errors.Write).
func CORS(c CORSConfig, next http.Handler) http.Handler {
	x := newCORS(c)
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		origins, hasOrigin := r.Header["Origin"]
		if !hasOrigin {
			next.ServeHTTP(w, r)
			return
		}
		origin := ""
		if len(origins) > 0 {
			origin = origins[0]
		}
		if _, preflight := r.Header["Access-Control-Request-Method"]; preflight && r.Method == http.MethodOptions {
			x.preflight(w, r, origin)
			return
		}
		next.ServeHTTP(&corsWriter{ResponseWriter: w, cors: x, origin: origin, r: r}, r)
	})
}

func (x *cors) preflight(w http.ResponseWriter, r *http.Request, origin string) {
	h := w.Header()
	for k, vs := range x.preflightHeaders {
		h[k] = slices.Clone(vs)
	}
	var failures []string
	if x.allowedOrigin(origin) {
		if x.explicitPreOrig {
			h.Set("Access-Control-Allow-Origin", origin)
		}
	} else {
		failures = append(failures, "origin")
	}
	if !slices.Contains(x.allowMethods, r.Header.Get("Access-Control-Request-Method")) {
		failures = append(failures, "method")
	}
	requested, hasRequested := r.Header["Access-Control-Request-Headers"]
	switch {
	case x.allowAllHeaders && hasRequested:
		h.Set("Access-Control-Allow-Headers", firstOf(requested))
	case hasRequested:
		for name := range strings.SplitSeq(strings.ToLower(firstOf(requested)), ",") {
			if !slices.Contains(x.allowHeaders, strings.TrimSpace(name)) {
				failures = append(failures, "headers")
				break
			}
		}
	}
	if _, ok := r.Header["Access-Control-Request-Private-Network"]; ok {
		failures = append(failures, "private-network")
	}
	status, body := http.StatusOK, "OK"
	if len(failures) > 0 {
		status, body = http.StatusBadRequest, "Disallowed CORS "+strings.Join(failures, ", ")
	}
	h.Set("Content-Type", "text/plain; charset=utf-8")
	h.Set("Content-Length", strconv.Itoa(len(body)))
	w.WriteHeader(status)
	_, _ = io.WriteString(w, body)
}

func firstOf(vs []string) string {
	if len(vs) == 0 {
		return ""
	}
	return vs[0]
}

type corsWriter struct {
	http.ResponseWriter
	cors        *cors
	origin      string
	r           *http.Request
	wroteHeader bool
}

func (w *corsWriter) addHeaders() {
	if w.wroteHeader {
		return
	}
	w.wroteHeader = true
	if st, ok := w.r.Context().Value(edgeStateKey{}).(*edgeState); ok && st.outsideCORS {
		return
	}
	h := w.Header()
	for k, vs := range w.cors.simpleHeaders {
		h[k] = slices.Clone(vs)
	}
	if !w.cors.allowAllOrigins && w.cors.allowedOrigin(w.origin) {
		h.Set("Access-Control-Allow-Origin", w.origin)
		addVary(h, "Origin")
	}
}

// addVary is MutableHeaders.add_vary_header.
func addVary(h http.Header, v string) {
	if existing := h.Get("Vary"); existing != "" {
		v = existing + ", " + v
	}
	h.Set("Vary", v)
}

func (w *corsWriter) WriteHeader(code int) {
	if code >= 200 {
		w.addHeaders()
	}
	w.ResponseWriter.WriteHeader(code)
}

func (w *corsWriter) Write(b []byte) (int, error) {
	w.addHeaders()
	return w.ResponseWriter.Write(b)
}

func (w *corsWriter) Unwrap() http.ResponseWriter { return w.ResponseWriter }
