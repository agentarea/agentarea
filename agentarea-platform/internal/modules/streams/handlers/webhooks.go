package handlers

import (
	"bytes"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"mime"
	"mime/multipart"
	"net/http"
	"sort"
	"strconv"
	"strings"
	"unicode/utf8"

	"github.com/go-chi/chi/v5"

	gen "github.com/agentarea/agentarea/agentarea-platform/api/openapi/streams"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/domain"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/service"
)

// mountWebhooks registers the webhook sink at the app root when the catalog, secrets, bus and
// dedup are wired. The sink reads the raw body, so it is not the generated wrapper.
func mountWebhooks(r chi.Router, _ *gen.ServerInterfaceWrapper, s *Server, errs *httpx.Errors) {
	if !s.svc.WebhooksReady() {
		return
	}
	r.Get("/webhooks/health", func(w http.ResponseWriter, _ *http.Request) {
		status := "healthy"
		if !s.svc.WebhookHealthy() {
			status = "unhealthy"
		}
		writeJSON(w, http.StatusOK, map[string]any{"status": status, "service": "webhook-manager"})
	})
	r.Post("/webhooks/{webhook_id}", func(w http.ResponseWriter, req *http.Request) {
		s.handleWebhook(w, req, errs)
	})
}

func writeJSON(w http.ResponseWriter, status int, body any) {
	raw, err := json.Marshal(body)
	if err != nil {
		raw = []byte(`{"status":"error","message":"Internal server error processing webhook"}`)
		status = http.StatusInternalServerError
	}
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Content-Length", strconv.Itoa(len(raw)))
	w.WriteHeader(status)
	_, _ = w.Write(raw)
}

func webhookError(w http.ResponseWriter, status int, msg string) {
	writeJSON(w, status, map[string]any{"status": "error", "message": msg})
}

var errTooLarge = errors.New("request too large")

// readLimited is the request body, refused past limit bytes: first by its declared length,
// then while it is read.
func readLimited(r *http.Request, limit int64) ([]byte, error) {
	if r.ContentLength > limit {
		return nil, errTooLarge
	}
	if declared := r.Header.Get("Content-Length"); declared != "" && isDigits(declared) {
		if n, err := strconv.ParseInt(declared, 10, 64); err != nil || n > limit {
			return nil, errTooLarge
		}
	}
	raw, err := io.ReadAll(io.LimitReader(r.Body, limit+1))
	if err != nil {
		return nil, err
	}
	if int64(len(raw)) > limit {
		return nil, errTooLarge
	}
	return raw, nil
}

func isDigits(s string) bool {
	for _, c := range s {
		if c < '0' || c > '9' {
			return false
		}
	}
	return s != ""
}

// requestHeaders is dict(request.headers): lowercase names, the last value of a repeated one.
func requestHeaders(r *http.Request) map[string]string {
	out := make(map[string]string, len(r.Header)+1)
	if r.Host != "" {
		out["host"] = r.Host
	}
	for k, vs := range r.Header {
		if len(vs) > 0 {
			out[strings.ToLower(k)] = vs[len(vs)-1]
		}
	}
	return out
}

func (s *Server) handleWebhook(w http.ResponseWriter, r *http.Request, errs *httpx.Errors) {
	ctx := r.Context()
	webhookID := chi.URLParam(r, "webhook_id")
	if s.rate != nil {
		if err := httpx.EnforceRateLimit(ctx, s.rate, s.log, httpx.WebhookScope, webhookID, s.svc.WebhookRate()); err != nil {
			errs.Write(w, r, err)
			return
		}
	}
	raw, err := readLimited(r, domain.MaxRequestBytes)
	if errors.Is(err, errTooLarge) {
		webhookError(w, http.StatusRequestEntityTooLarge, fmt.Sprintf("The request is larger than %d bytes", domain.MaxRequestBytes))
		return
	}
	if err != nil {
		webhookError(w, http.StatusBadRequest, "Body cannot be read: "+err.Error())
		return
	}
	contentType := strings.ToLower(r.Header.Get("Content-Type"))
	body, err := parseBody(raw, contentType)
	if err != nil {
		webhookError(w, http.StatusBadRequest, "Body cannot be read: "+err.Error())
		return
	}
	if problem, bad := PGTextProblem(body, "$"); bad {
		webhookError(w, http.StatusUnprocessableEntity, "Body cannot be stored: "+problem)
		return
	}
	answer, err := s.svc.HandleWebhook(ctx, service.WebhookDelivery{
		WebhookID: webhookID, Headers: requestHeaders(r), Raw: raw, Body: body,
	})
	if err != nil {
		s.log.ErrorContext(ctx, "Unexpected error handling webhook", "webhook_id", webhookID, "error", err.Error())
		webhookError(w, http.StatusInternalServerError, "Internal server error processing webhook")
		return
	}
	writeJSON(w, answer.Status, answer.Body)
}

// parseBody is JSON strictly, form fields as text, form files as inline attachments, else text.
func parseBody(raw []byte, contentType string) (any, error) {
	switch {
	case strings.Contains(contentType, "application/json") || strings.HasSuffix(contentType, "+json"):
		if len(raw) == 0 {
			return nil, nil
		}
		if !utf8.Valid(raw) {
			return nil, errors.New("the body is not UTF-8")
		}
		return service.DecodeJSON(raw)
	case strings.Contains(contentType, "application/x-www-form-urlencoded"):
		if !utf8.Valid(raw) {
			return nil, errors.New("the body is not UTF-8")
		}
		return parseQSL(string(raw)), nil
	case strings.Contains(contentType, "multipart/form-data"):
		return parseMultipart(raw, contentType)
	}
	if len(raw) == 0 {
		return nil, nil
	}
	if !utf8.Valid(raw) {
		return nil, errors.New("the body is not UTF-8")
	}
	return string(raw), nil
}

// parseQSL is dict(parse_qsl(text, keep_blank_values=True)): pairs split on &, the last value
// of a repeated name, + as space, bad escapes kept as written.
func parseQSL(text string) map[string]any {
	out := map[string]any{}
	for _, pair := range strings.Split(text, "&") {
		if pair == "" {
			continue
		}
		k, v, _ := strings.Cut(pair, "=")
		out[unquotePlus(k)] = unquotePlus(v)
	}
	return out
}

func unhex(c byte) (byte, bool) {
	switch {
	case c >= '0' && c <= '9':
		return c - '0', true
	case c >= 'a' && c <= 'f':
		return c - 'a' + 10, true
	case c >= 'A' && c <= 'F':
		return c - 'A' + 10, true
	}
	return 0, false
}

func unquotePlus(s string) string {
	s = strings.ReplaceAll(s, "+", " ")
	var b bytes.Buffer
	for i := 0; i < len(s); i++ {
		if s[i] == '%' && i+2 < len(s) {
			hi, ok1 := unhex(s[i+1])
			lo, ok2 := unhex(s[i+2])
			if ok1 && ok2 {
				b.WriteByte(hi<<4 | lo)
				i += 2
				continue
			}
		}
		b.WriteByte(s[i])
	}
	return strings.ToValidUTF8(b.String(), "�")
}

func parseMultipart(raw []byte, contentType string) (any, error) {
	_, params, err := mime.ParseMediaType(contentType)
	if err != nil {
		return nil, err
	}
	boundary := params["boundary"]
	if boundary == "" {
		return nil, errors.New("multipart body without a boundary")
	}
	mr := multipart.NewReader(bytes.NewReader(raw), boundary)
	fields := map[string]any{}
	var files []any
	for {
		part, err := mr.NextRawPart()
		if errors.Is(err, io.EOF) {
			break
		}
		if err != nil {
			return nil, err
		}
		data, err := io.ReadAll(part)
		if err != nil {
			return nil, err
		}
		name := part.FormName()
		if part.FileName() == "" {
			if !utf8.Valid(data) {
				return nil, errors.New("a form field is not UTF-8")
			}
			fields[name] = string(data)
			continue
		}
		var ct any
		if v := part.Header.Get("Content-Type"); v != "" {
			ct = v
		}
		files = append(files, map[string]any{
			"field": name, "name": part.FileName(), "mime": ct, "size": json.Number(strconv.Itoa(len(data))),
			"content_base64": base64.StdEncoding.EncodeToString(data),
		})
	}
	if len(files) > 0 {
		fields["attachments"] = files
	}
	return fields, nil
}

func textProblem(s string) (string, bool) {
	if strings.ContainsRune(s, 0) {
		return "contains a NUL character", true
	}
	return "", false
}

// PGTextProblem is pg_text_problem: the first string Postgres cannot store as text. JSON decoding
// already replaces an unpaired surrogate with U+FFFD, so only NUL is left to find.
func PGTextProblem(v any, path string) (string, bool) {
	switch x := v.(type) {
	case string:
		if p, bad := textProblem(x); bad {
			return path + " " + p, true
		}
	case map[string]any:
		keys := make([]string, 0, len(x))
		for k := range x {
			keys = append(keys, k)
		}
		sort.Strings(keys)
		for _, k := range keys {
			if p, bad := textProblem(k); bad {
				return "a key in " + path + " " + p, true
			}
			if p, bad := PGTextProblem(x[k], path+"."+k); bad {
				return p, true
			}
		}
	case []any:
		for i, item := range x {
			if p, bad := PGTextProblem(item, path+"["+strconv.Itoa(i)+"]"); bad {
				return p, true
			}
		}
	}
	return "", false
}
