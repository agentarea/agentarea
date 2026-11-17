package handlers

import (
	"io"
	"mime"
	"net/http"
	"strings"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx/wirejson"
)

// absent is a request body FastAPI saw none of.
type absent struct{}

// readBody is FastAPI's body read for a JSON body parameter: an empty body
// is absent, a JSON (or missing) content type is parsed, any other body is
// raw bytes the model then refuses.
func readBody(r *http.Request) (any, error) {
	raw, err := io.ReadAll(r.Body)
	if err != nil {
		return nil, err
	}
	if len(raw) == 0 {
		return absent{}, nil
	}
	if ct := r.Header.Get("Content-Type"); ct != "" && !jsonContentType(ct) {
		return raw, nil
	}
	if err := httpx.CheckJSONBody(raw); err != nil {
		return nil, err
	}
	return wirejson.Unmarshal(raw)
}

func jsonContentType(ct string) bool {
	media, _, err := mime.ParseMediaType(ct)
	if err != nil {
		media = strings.ToLower(strings.TrimSpace(strings.SplitN(ct, ";", 2)[0]))
	}
	main, sub, _ := strings.Cut(media, "/")
	return main == "application" && (sub == "json" || strings.HasSuffix(sub, "+json"))
}

// model checks the value is an object at loc.
func model(v any, loc []any, errs *[]httpx.FieldError) (wirejson.Object, bool) {
	switch o := v.(type) {
	case wirejson.Object:
		return o, true
	case absent:
		*errs = append(*errs, httpx.Missing(loc...))
	default:
		*errs = append(*errs, httpx.ModelAttributesType(loc...))
	}
	return nil, false
}

func at(loc []any, more ...any) []any {
	out := make([]any, 0, len(loc)+len(more))
	return append(append(out, loc...), more...)
}
