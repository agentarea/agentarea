package handlers

import (
	"encoding/json"
	"io"
	"math"
	"mime"
	"net/http"
	"strings"
	"unicode/utf8"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx/wirejson"
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

// model checks the body is an object; loc is ("body",).
func model(v any, errs *[]httpx.FieldError) (wirejson.Object, bool) {
	switch o := v.(type) {
	case wirejson.Object:
		return o, true
	case absent:
		*errs = append(*errs, httpx.Missing("body"))
	default:
		*errs = append(*errs, httpx.ModelAttributesType("body"))
	}
	return nil, false
}

// extraForbidden reports keys outside fields, after the field errors
// (extra="forbid").
func extraForbidden(o wirejson.Object, fields []string, errs *[]httpx.FieldError) {
	for _, m := range o {
		known := false
		for _, f := range fields {
			if m.Key == f {
				known = true
				break
			}
		}
		if !known {
			*errs = append(*errs, httpx.ExtraForbidden("body", m.Key))
		}
	}
}

// str is a str field with length bounds (0 = none); nullable admits null.
func str(o wirejson.Object, key string, minLen, maxLen int, nullable bool, errs *[]httpx.FieldError) (value *string, set bool) {
	v, ok := o.Get(key)
	if !ok {
		return nil, false
	}
	if v == nil && nullable {
		return nil, true
	}
	s, isStr := v.(string)
	if !isStr {
		*errs = append(*errs, httpx.StringType("body", key))
		return nil, true
	}
	n := utf8.RuneCountInString(s)
	if minLen > 0 && n < minLen {
		*errs = append(*errs, httpx.StringTooShort(minLen, "body", key))
		return nil, true
	}
	if maxLen > 0 && n > maxLen {
		*errs = append(*errs, httpx.StringTooLong(maxLen, "body", key))
		return nil, true
	}
	return &s, true
}

// intField is a required int in pydantic's lax mode.
func intField(o wirejson.Object, key string, errs *[]httpx.FieldError) (int64, bool) {
	v, ok := o.Get(key)
	if !ok {
		*errs = append(*errs, httpx.Missing("body", key))
		return 0, false
	}
	switch x := v.(type) {
	case bool:
		if x {
			return 1, true
		}
		return 0, true
	case json.Number:
		if n, ok := httpx.ParseInt(string(x)); ok {
			return n.Value, true
		}
	case wirejson.Float:
		if float64(x) != math.Trunc(float64(x)) {
			*errs = append(*errs, httpx.IntFromFloat("body", key))
			return 0, false
		}
		return int64(x), true
	case string:
		if n, ok := httpx.ParseInt(x); ok {
			return n.Value, true
		}
		*errs = append(*errs, httpx.IntParsing("body", key))
		return 0, false
	}
	*errs = append(*errs, httpx.IntType("body", key))
	return 0, false
}

// required is a str field with min_length that must be present.
func required(o wirejson.Object, key string, minLen int, errs *[]httpx.FieldError) string {
	v, set := str(o, key, minLen, 0, false, errs)
	if !set {
		*errs = append(*errs, httpx.Missing("body", key))
	}
	if v == nil {
		return ""
	}
	return *v
}
