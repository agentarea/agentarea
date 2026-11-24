package httpx

import (
	"bufio"
	"bytes"
	"context"
	"errors"
	"io"
	"log/slog"
	"net"
	"net/http"
	"net/url"
	"strconv"
	"strings"
	"unicode/utf8"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx/wirejson"
)

// Chain is the middleware main.py installs, outermost first, as Starlette
// applies add_middleware in reverse: the catch-all (ServerErrorMiddleware),
// CORS, body size, NUL refusal, audit request context.
func Chain(cfg Config, errs *Errors, log *slog.Logger, h http.Handler) http.Handler {
	h = AuditContext(h)
	h = RefuseNUL(h)
	h = LimitBody(cfg.MaxBody, h)
	h = CORS(cfg.CORS, h)
	return Recover(errs, log, h)
}

// Recover is Starlette's ServerErrorMiddleware: a panic becomes the 500
// problem, without CORS headers; once the response has started the
// connection is cut instead.
func Recover(errs *Errors, log *slog.Logger, next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		ctx, st := withEdgeState(r.Context())
		r = r.WithContext(ctx)
		sw := &startedWriter{ResponseWriter: w}
		defer func() {
			v := recover()
			if v == nil {
				return
			}
			err, ok := v.(error)
			if ok && errors.Is(err, http.ErrAbortHandler) {
				panic(v)
			}
			if !ok {
				err = &panicError{v: v}
			}
			if sw.started {
				if log != nil {
					log.ErrorContext(r.Context(), "handler panicked after the response started", "error", err)
				}
				panic(http.ErrAbortHandler)
			}
			st.outsideCORS = true
			for k := range w.Header() {
				w.Header().Del(k)
			}
			errs.Write(w, r, err)
		}()
		next.ServeHTTP(sw, r)
	})
}

type panicError struct{ v any }

func (e *panicError) Error() string { return "panic: " + strings.TrimSpace(sprint(e.v)) }

func sprint(v any) string {
	if s, ok := v.(interface{ String() string }); ok {
		return s.String()
	}
	if s, ok := v.(string); ok {
		return s
	}
	b, _ := wirejson.Marshal(v, wirejson.Compact)
	return string(b)
}

// startedWriter records whether the response has started.
type startedWriter struct {
	http.ResponseWriter
	started bool
}

func (w *startedWriter) WriteHeader(code int) {
	if code >= 200 || code == http.StatusSwitchingProtocols {
		w.started = true
	}
	w.ResponseWriter.WriteHeader(code)
}

func (w *startedWriter) Write(b []byte) (int, error) {
	w.started = true
	return w.ResponseWriter.Write(b)
}

func (w *startedWriter) Unwrap() http.ResponseWriter { return w.ResponseWriter }

func (w *startedWriter) Hijack() (net.Conn, *bufio.ReadWriter, error) {
	w.started = true
	return http.NewResponseController(w.ResponseWriter).Hijack()
}

// tooLargeBody is BodySizeLimitMiddleware's own answer: plain JSON, not a problem.
const tooLargeBody = `{"detail":"Request body too large"}`

func writeTooLarge(w http.ResponseWriter) {
	h := w.Header()
	h.Set("Content-Type", "application/json")
	h.Set("Content-Length", strconv.Itoa(len(tooLargeBody)))
	w.WriteHeader(http.StatusRequestEntityTooLarge)
	_, _ = io.WriteString(w, tooLargeBody)
}

// LimitBody is BodySizeLimitMiddleware: a declared Content-Length over max
// is refused before the handler runs; a body that streams past max fails
// the read with ErrBodyTooLarge, and whatever the handler then answers
// (unless it had already started its response) is replaced by the 413.
func LimitBody(maxBytes int64, next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.ContentLength > maxBytes {
			writeTooLarge(w)
			return
		}
		lb := &limitedBody{rc: r.Body, max: maxBytes}
		gw := &guardedWriter{ResponseWriter: w, body: lb}
		if r.Body != nil && r.Body != http.NoBody {
			r.Body = lb
		}
		next.ServeHTTP(gw, r)
		if lb.exceeded && !gw.started {
			gw.answer()
		}
	})
}

type limitedBody struct {
	rc       io.ReadCloser
	max      int64
	n        int64
	exceeded bool
}

func (b *limitedBody) Read(p []byte) (int, error) {
	if b.exceeded {
		return 0, ErrBodyTooLarge
	}
	n, err := b.rc.Read(p)
	b.n += int64(n)
	if b.n > b.max {
		b.exceeded = true
		return 0, ErrBodyTooLarge
	}
	return n, err
}

func (b *limitedBody) Close() error { return b.rc.Close() }

type guardedWriter struct {
	http.ResponseWriter
	body     *limitedBody
	started  bool
	answered bool
}

func (w *guardedWriter) answer() {
	w.started, w.answered = true, true
	for k := range w.Header() {
		w.Header().Del(k)
	}
	writeTooLarge(w.ResponseWriter)
}

func (w *guardedWriter) WriteHeader(code int) {
	if w.answered {
		return
	}
	if w.body.exceeded && !w.started {
		w.answer()
		return
	}
	if code >= 200 {
		w.started = true
	}
	w.ResponseWriter.WriteHeader(code)
}

func (w *guardedWriter) Write(b []byte) (int, error) {
	if !w.started {
		w.WriteHeader(http.StatusOK)
	}
	if w.answered {
		return len(b), nil
	}
	return w.ResponseWriter.Write(b)
}

func (w *guardedWriter) Unwrap() http.ResponseWriter { return w.ResponseWriter }

// RefuseNUL is NulCharacterMiddleware: 422 nul_character for a U+0000 in
// the decoded path, a query name or value, or a string or key of a JSON
// body (application/json or any +json type) that json.loads accepts.
func RefuseNUL(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if strings.Contains(r.URL.Path, "\x00") || queryHasNUL(r.URL.RawQuery) {
			refuseNUL(w)
			return
		}
		if isJSON(r.Header.Get("Content-Type")) && r.Body != nil && r.Body != http.NoBody {
			body, err := io.ReadAll(r.Body)
			r.Body = io.NopCloser(bytes.NewReader(body))
			if err != nil {
				r.Body = io.NopCloser(io.MultiReader(bytes.NewReader(body), errReader{err}))
			} else if wirejson.ContainsNUL(body) {
				refuseNUL(w)
				return
			}
		}
		next.ServeHTTP(w, r)
	})
}

type errReader struct{ err error }

func (e errReader) Read([]byte) (int, error) { return 0, e.err }

func refuseNUL(w http.ResponseWriter) {
	WriteProblem(w, Problem{
		Status: http.StatusUnprocessableEntity, Code: CodeNUL,
		Detail: "Request contains a NUL (U+0000) character, which cannot be stored",
	}, nil)
}

func isJSON(contentType string) bool {
	media, _, _ := strings.Cut(contentType, ";")
	media = strings.ToLower(strings.TrimSpace(media))
	return media == "application/json" || strings.HasSuffix(media, "+json")
}

func queryHasNUL(raw string) bool {
	for _, kv := range QueryPairs(raw) {
		if strings.Contains(kv[0], "\x00") || strings.Contains(kv[1], "\x00") {
			return true
		}
	}
	return false
}

// QueryPairs parses a query string as Starlette does (urllib's parse_qsl
// with keep_blank_values): split on "&" only, "+" is a space, a malformed
// escape is kept as written, undecodable bytes become U+FFFD.
func QueryPairs(raw string) [][2]string {
	var out [][2]string
	for part := range strings.SplitSeq(raw, "&") {
		if part == "" {
			continue
		}
		name, value, _ := strings.Cut(part, "=")
		out = append(out, [2]string{unquotePlus(name), unquotePlus(value)})
	}
	return out
}

// Query is QueryPairs as url.Values.
func Query(raw string) url.Values {
	v := url.Values{}
	for _, kv := range QueryPairs(raw) {
		v.Add(kv[0], kv[1])
	}
	return v
}

func unquotePlus(s string) string {
	s = strings.ReplaceAll(s, "+", " ")
	if !strings.Contains(s, "%") {
		return s
	}
	var buf []byte
	for i := 0; i < len(s); i++ {
		if s[i] == '%' && i+2 < len(s) && isHexByte(s[i+1]) && isHexByte(s[i+2]) {
			v, _ := strconv.ParseUint(s[i+1:i+3], 16, 8)
			buf = append(buf, byte(v))
			i += 2
			continue
		}
		buf = append(buf, s[i])
	}
	if utf8.Valid(buf) {
		return string(buf)
	}
	return strings.ToValidUTF8(string(buf), "�")
}

// Audit is what AuditContextMiddleware records for audit events.
type Audit struct {
	SourceIP  string
	UserAgent string
	RequestID string
}

type auditKey struct{}

// AuditFrom returns the request's audit context.
func AuditFrom(ctx context.Context) (Audit, bool) {
	a, ok := ctx.Value(auditKey{}).(Audit)
	return a, ok
}

// AuditContext is AuditContextMiddleware: the first X-Forwarded-For hop
// else the peer address, the user agent, and X-Request-Id else a new uuid4.
func AuditContext(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		a := Audit{UserAgent: r.Header.Get("User-Agent"), RequestID: r.Header.Get("X-Request-Id")}
		if fwd := r.Header.Get("X-Forwarded-For"); fwd != "" {
			first, _, _ := strings.Cut(fwd, ",")
			a.SourceIP = strings.TrimSpace(first)
		} else if host, _, err := net.SplitHostPort(r.RemoteAddr); err == nil {
			a.SourceIP = host
		}
		if _, ok := r.Header["X-Request-Id"]; !ok {
			a.RequestID = uuid.NewString()
		}
		next.ServeHTTP(w, r.WithContext(context.WithValue(r.Context(), auditKey{}, a)))
	})
}
