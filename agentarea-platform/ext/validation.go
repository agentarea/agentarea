package ext

import "github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx"

// Pydantic v2 field errors, worded and shaped as FastAPI renders them, for
// extension handlers that validate what FastAPI validated. loc is the
// error's location, e.g. ("body", "amount").

// IntBounds are a query or path integer's ge/le constraints.
type IntBounds = httpx.IntBounds

func Missing(loc ...any) FieldError             { return httpx.Missing(loc...) }
func IntType(loc ...any) FieldError             { return httpx.IntType(loc...) }
func IntParsing(loc ...any) FieldError          { return httpx.IntParsing(loc...) }
func IntFromFloat(loc ...any) FieldError        { return httpx.IntFromFloat(loc...) }
func BoolType(loc ...any) FieldError            { return httpx.BoolType(loc...) }
func StringType(loc ...any) FieldError          { return httpx.StringType(loc...) }
func ModelAttributesType(loc ...any) FieldError { return httpx.ModelAttributesType(loc...) }

func GreaterThan(limit any, loc ...any) FieldError      { return httpx.GreaterThan(limit, loc...) }
func GreaterThanEqual(limit any, loc ...any) FieldError { return httpx.GreaterThanEqual(limit, loc...) }
func LessThan(limit any, loc ...any) FieldError         { return httpx.LessThan(limit, loc...) }
func LessThanEqual(limit any, loc ...any) FieldError    { return httpx.LessThanEqual(limit, loc...) }

func StringPatternMismatch(pattern string, loc ...any) FieldError {
	return httpx.StringPatternMismatch(pattern, loc...)
}

func UUIDParsing(reason string, loc ...any) FieldError { return httpx.UUIDParsing(reason, loc...) }
func ValueError(msg string, loc ...any) FieldError     { return httpx.ValueError(msg, loc...) }

// ValidateUUID parses s and returns the field error pydantic reports.
func ValidateUUID(s string, loc ...any) (string, *FieldError) { return httpx.ValidateUUID(s, loc...) }

// ValidateInt parses a query or path integer and checks its bounds.
func ValidateInt(s string, b IntBounds, loc ...any) (int64, *FieldError) {
	return httpx.ValidateInt(s, b, loc...)
}

// CheckJSONBody is FastAPI's body read: nil for a body json.loads accepts,
// json_invalid with CPython's position otherwise.
func CheckJSONBody(body []byte) error { return httpx.CheckJSONBody(body) }
