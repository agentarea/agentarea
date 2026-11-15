package handlers

import (
	"io"
	"mime"
	"net/http"
	"strings"
	"unicode"
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

// uuidField is a UUID | None field; the value is canonical.
func uuidField(o wirejson.Object, key string, errs *[]httpx.FieldError) (value *string, set bool) {
	v, ok := o.Get(key)
	if !ok {
		return nil, false
	}
	if v == nil {
		return nil, true
	}
	s, isStr := v.(string)
	if !isStr {
		*errs = append(*errs, httpx.FieldError{Type: "uuid_type", Loc: []any{"body", key}, Msg: "UUID input should be a string, bytes or UUID object"})
		return nil, true
	}
	id, fe := httpx.ValidateUUID(s, "body", key)
	if fe != nil {
		*errs = append(*errs, *fe)
		return nil, true
	}
	return &id, true
}

// pyStrip is str.strip(): Python's whitespace includes U+001C..U+001F.
func pyStrip(s string) string {
	return strings.TrimFunc(s, func(r rune) bool {
		return unicode.IsSpace(r) || (r >= 0x1c && r <= 0x1f)
	})
}

// boolField is a bool | None field.
func boolField(o wirejson.Object, key string, errs *[]httpx.FieldError) (value *bool, set bool) {
	v, ok := o.Get(key)
	if !ok {
		return nil, false
	}
	if v == nil {
		return nil, true
	}
	b, isBool := v.(bool)
	if !isBool {
		*errs = append(*errs, httpx.BoolType("body", key))
		return nil, true
	}
	return &b, true
}
