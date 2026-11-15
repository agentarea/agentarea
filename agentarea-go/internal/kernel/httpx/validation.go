package httpx

import (
	"fmt"
	"math"
	"regexp"
	"strconv"
	"strings"
	"unicode/utf8"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx/wirejson"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
)

// Field errors with pydantic 2's types and messages (pydantic-core
// ErrorType). Loc is the place FastAPI names: "body", "query", "path",
// "header" first, then field names and list indexes.

// Loc builds a location.
func Loc(parts ...any) []any { return parts }

// Missing is a required value that is absent.
func Missing(loc ...any) FieldError {
	return FieldError{Type: "missing", Loc: loc, Msg: "Field required"}
}

// ExtraForbidden is a key a model with extra="forbid" does not declare.
func ExtraForbidden(loc ...any) FieldError {
	return FieldError{Type: "extra_forbidden", Loc: loc, Msg: "Extra inputs are not permitted"}
}

// IntParsing is a string that is not an integer.
func IntParsing(loc ...any) FieldError {
	return FieldError{Type: "int_parsing", Loc: loc, Msg: "Input should be a valid integer, unable to parse string as an integer"}
}

// IntType is a JSON value of the wrong type for an integer.
func IntType(loc ...any) FieldError {
	return FieldError{Type: "int_type", Loc: loc, Msg: "Input should be a valid integer"}
}

// IntFromFloat is a number with a fractional part where an integer is expected.
func IntFromFloat(loc ...any) FieldError {
	return FieldError{Type: "int_from_float", Loc: loc, Msg: "Input should be a valid integer, got a number with a fractional part"}
}

// FloatParsing is a string that is not a number.
func FloatParsing(loc ...any) FieldError {
	return FieldError{Type: "float_parsing", Loc: loc, Msg: "Input should be a valid number, unable to parse string as a number"}
}

// FloatType is a JSON value of the wrong type for a number.
func FloatType(loc ...any) FieldError {
	return FieldError{Type: "float_type", Loc: loc, Msg: "Input should be a valid number"}
}

// BoolParsing is a string that is not a boolean.
func BoolParsing(loc ...any) FieldError {
	return FieldError{Type: "bool_parsing", Loc: loc, Msg: "Input should be a valid boolean, unable to interpret input"}
}

// BoolType is a JSON value of the wrong type for a boolean.
func BoolType(loc ...any) FieldError {
	return FieldError{Type: "bool_type", Loc: loc, Msg: "Input should be a valid boolean"}
}

// StringType is a JSON value of the wrong type for a string.
func StringType(loc ...any) FieldError {
	return FieldError{Type: "string_type", Loc: loc, Msg: "Input should be a valid string"}
}

// ListType is a JSON value of the wrong type for a list.
func ListType(loc ...any) FieldError {
	return FieldError{Type: "list_type", Loc: loc, Msg: "Input should be a valid list"}
}

// DictType is a JSON value of the wrong type for a dict.
func DictType(loc ...any) FieldError {
	return FieldError{Type: "dict_type", Loc: loc, Msg: "Input should be a valid dictionary"}
}

// ModelAttributesType is a body that is not an object where a model is expected.
func ModelAttributesType(loc ...any) FieldError {
	return FieldError{Type: "model_attributes_type", Loc: loc, Msg: "Input should be a valid dictionary or object to extract fields from"}
}

func plural(n int) string {
	if n == 1 {
		return ""
	}
	return "s"
}

// StringTooShort is a string under min_length characters.
func StringTooShort(minLength int, loc ...any) FieldError {
	return FieldError{
		Type: "string_too_short", Loc: loc,
		Msg: fmt.Sprintf("String should have at least %d character%s", minLength, plural(minLength)),
		Ctx: wirejson.Object{{Key: "min_length", Value: minLength}},
	}
}

// StringTooLong is a string over max_length characters.
func StringTooLong(maxLength int, loc ...any) FieldError {
	return FieldError{
		Type: "string_too_long", Loc: loc,
		Msg: fmt.Sprintf("String should have at most %d character%s", maxLength, plural(maxLength)),
		Ctx: wirejson.Object{{Key: "max_length", Value: maxLength}},
	}
}

// StringPatternMismatch is a string the field's pattern does not match.
func StringPatternMismatch(pattern string, loc ...any) FieldError {
	return FieldError{
		Type: "string_pattern_mismatch", Loc: loc,
		Msg: "String should match pattern '" + pattern + "'",
		Ctx: wirejson.Object{{Key: "pattern", Value: pattern}},
	}
}

func bound(typ, words, key string, limit any, loc []any) FieldError {
	return FieldError{
		Type: typ, Loc: loc,
		Msg: fmt.Sprintf("Input should be %s %s", words, pyNumber(limit)),
		Ctx: wirejson.Object{{Key: key, Value: limit}},
	}
}

func pyNumber(v any) string {
	switch n := v.(type) {
	case wirejson.Float:
		return wirejson.FormatFloat(float64(n))
	case float64:
		return wirejson.FormatFloat(n)
	default:
		return fmt.Sprint(n)
	}
}

// GreaterThanEqual is a number under ge; limit is an int or a wirejson.Float.
func GreaterThanEqual(limit any, loc ...any) FieldError {
	return bound("greater_than_equal", "greater than or equal to", "ge", limit, loc)
}

// GreaterThan is a number not over gt.
func GreaterThan(limit any, loc ...any) FieldError {
	return bound("greater_than", "greater than", "gt", limit, loc)
}

// LessThanEqual is a number over le.
func LessThanEqual(limit any, loc ...any) FieldError {
	return bound("less_than_equal", "less than or equal to", "le", limit, loc)
}

// LessThan is a number not under lt.
func LessThan(limit any, loc ...any) FieldError {
	return bound("less_than", "less than", "lt", limit, loc)
}

// expected renders choices as pydantic does: 'a', 'b' or 'c'.
func expected(choices []string) string {
	quoted := make([]string, len(choices))
	for i, c := range choices {
		quoted[i] = "'" + c + "'"
	}
	if len(quoted) == 1 {
		return quoted[0]
	}
	return strings.Join(quoted[:len(quoted)-1], ", ") + " or " + quoted[len(quoted)-1]
}

// LiteralError is a value outside a Literal's string choices.
func LiteralError(choices []string, loc ...any) FieldError {
	e := expected(choices)
	return FieldError{Type: "literal_error", Loc: loc, Msg: "Input should be " + e, Ctx: wirejson.Object{{Key: "expected", Value: e}}}
}

// EnumError is a value outside a string Enum's values.
func EnumError(choices []string, loc ...any) FieldError {
	e := expected(choices)
	return FieldError{Type: "enum", Loc: loc, Msg: "Input should be " + e, Ctx: wirejson.Object{{Key: "expected", Value: e}}}
}

// ValueError is a validator's ValueError: FastAPI's jsonable_encoder turns
// the exception in ctx into an empty object.
func ValueError(msg string, loc ...any) FieldError {
	return FieldError{Type: "value_error", Loc: loc, Msg: "Value error, " + msg, Ctx: wirejson.Object{{Key: "error", Value: wirejson.Object{}}}}
}

// UUIDParsing is a string that is not a UUID; reason is the uuid crate's.
func UUIDParsing(reason string, loc ...any) FieldError {
	return FieldError{
		Type: "uuid_parsing", Loc: loc, Msg: "Input should be a valid UUID, " + reason,
		Ctx: wirejson.Object{{Key: "error", Value: reason}},
	}
}

// JSONInvalid is a request body json.loads refuses (FastAPI routing.py):
// loc is ("body", position).
func JSONInvalid(e *wirejson.DecodeError) FieldError {
	return FieldError{
		Type: "json_invalid", Loc: []any{"body", e.Pos}, Msg: "JSON decode error",
		Ctx: wirejson.Object{{Key: "error", Value: e.Msg}},
	}
}

// CheckJSONBody is FastAPI's body read: nil for a body json.loads accepts,
// a 422 json_invalid for one it refuses, the 400 "There was an error
// parsing the body" for one that is not UTF-8.
func CheckJSONBody(body []byte) error {
	decodeErr, ok := wirejson.Check(body)
	if !ok {
		return HTTPError(400, "There was an error parsing the body")
	}
	if decodeErr != nil {
		return Validation(JSONInvalid(decodeErr))
	}
	return nil
}

// Int is an integer read from a query or path string, pydantic's lax
// str->int. Overflow is set, with Value saturated, for an integer past
// int64, which pydantic accepts and then compares with the bounds.
type Int struct {
	Value    int64
	Overflow bool
}

var intPattern = regexp.MustCompile(`^[+-]?[0-9]+(?:_[0-9]+)*(?:\.0+)?$`)

// ParseInt reads s as pydantic does: surrounding whitespace, one sign,
// single underscores between digits and a zero fraction are accepted.
func ParseInt(s string) (Int, bool) {
	s = strings.TrimSpace(s)
	if !intPattern.MatchString(s) {
		return Int{}, false
	}
	digits, _, _ := strings.Cut(strings.ReplaceAll(s, "_", ""), ".")
	n, err := strconv.ParseInt(digits, 10, 64)
	if err != nil {
		if strings.HasPrefix(digits, "-") {
			return Int{Value: math.MinInt64, Overflow: true}, true
		}
		return Int{Value: math.MaxInt64, Overflow: true}, true
	}
	return Int{Value: n}, true
}

// IntBounds are a query or path integer's ge/le constraints.
type IntBounds struct {
	Ge, Le       int64
	HasGe, HasLe bool
}

// ValidateInt parses s and checks its bounds, returning the field error
// pydantic reports first.
func ValidateInt(s string, b IntBounds, loc ...any) (int64, *FieldError) {
	n, ok := ParseInt(s)
	if !ok {
		e := IntParsing(loc...)
		return 0, &e
	}
	if b.HasGe && n.Value < b.Ge {
		e := GreaterThanEqual(b.Ge, loc...)
		return 0, &e
	}
	if b.HasLe && (n.Value > b.Le || (n.Overflow && n.Value > 0)) {
		e := LessThanEqual(b.Le, loc...)
		return 0, &e
	}
	return n.Value, nil
}

// ParseBool reads s as pydantic's str->bool does.
func ParseBool(s string) (value, ok bool) {
	switch strings.ToLower(s) {
	case "1", "on", "t", "true", "y", "yes":
		return true, true
	case "0", "off", "f", "false", "n", "no":
		return false, true
	}
	return false, false
}

var floatPattern = regexp.MustCompile(`^[+-]?(?:[0-9]+(?:_[0-9]+)*(?:\.(?:[0-9]+(?:_[0-9]+)*)?)?|\.[0-9]+(?:_[0-9]+)*)(?:[eE][+-]?[0-9]+(?:_[0-9]+)*)?$`)

// ParseFloat reads s as pydantic's str->float does (Python's float()).
func ParseFloat(s string) (float64, bool) {
	s = strings.TrimSpace(s)
	switch strings.ToLower(strings.TrimLeft(s, "+-")) {
	case "nan", "inf", "infinity":
		f, err := strconv.ParseFloat(s, 64)
		return f, err == nil
	}
	if !floatPattern.MatchString(s) {
		return 0, false
	}
	f, err := strconv.ParseFloat(strings.ReplaceAll(s, "_", ""), 64)
	if err != nil {
		return f, strings.Contains(err.Error(), "range")
	}
	return f, true
}

// ParseUUID reads s as pydantic does (the uuid crate's parse_str: simple,
// hyphenated, braced and urn forms, either case) and returns its canonical
// lowercase hyphenated form, or the crate's reason for refusing it.
func ParseUUID(s string) (string, string) {
	inner, ok := uuidInner(s)
	if ok {
		if hexOnly := strings.ReplaceAll(inner, "-", ""); len(hexOnly) == 32 && isHexString(hexOnly) && validUUIDShape(inner) {
			h := strings.ToLower(hexOnly)
			return h[0:8] + "-" + h[8:12] + "-" + h[12:16] + "-" + h[16:20] + "-" + h[20:32], ""
		}
	}
	return "", uuidReason(s)
}

func uuidInner(s string) (string, bool) {
	switch {
	case len(s) == 32:
		return s, !strings.Contains(s, "-")
	case len(s) == 36:
		return s, true
	case len(s) == 38 && s[0] == '{' && s[37] == '}':
		return s[1:37], true
	case len(s) == 45 && strings.HasPrefix(s, "urn:uuid:"):
		return s[9:], true
	}
	return "", false
}

func validUUIDShape(s string) bool {
	if len(s) == 32 {
		return true
	}
	return len(s) == 36 && s[8] == '-' && s[13] == '-' && s[18] == '-' && s[23] == '-'
}

func isHexString(s string) bool {
	for i := 0; i < len(s); i++ {
		if !isHexByte(s[i]) {
			return false
		}
	}
	return true
}

func isHexByte(c byte) bool {
	return (c >= '0' && c <= '9') || (c >= 'a' && c <= 'f') || (c >= 'A' && c <= 'F')
}

// uuidReason is the uuid crate's InvalidUuid::into_err message.
func uuidReason(input string) string {
	if !utf8.ValidString(input) {
		return "invalid UTF-8"
	}
	body, offset, simple := input, 0, true
	switch {
	case len(input) >= 2 && input[0] == '{' && input[len(input)-1] == '}':
		body, offset, simple = input[1:len(input)-1], 1, false
	case strings.HasPrefix(input, "urn:uuid:"):
		body, offset, simple = input[9:], 9, false
	}
	hyphens := 0
	var bounds [4]int
	for i, r := range body {
		switch {
		case r >= utf8.RuneSelf:
			return fmt.Sprintf("invalid character: expected an optional prefix of `urn:uuid:` followed by [0-9a-fA-F-], found `%c` at %d", r, i+offset+1)
		case r == '-':
			if hyphens < 4 {
				bounds[hyphens] = i
			}
			hyphens++
		case !isHexByte(byte(r)):
			return fmt.Sprintf("invalid character: expected an optional prefix of `urn:uuid:` followed by [0-9a-fA-F-], found `%c` at %d", r, i+offset+1)
		}
	}
	switch {
	case hyphens == 0 && simple:
		return fmt.Sprintf("invalid length: expected length 32 for simple format, found %d", len(input))
	case hyphens != 4:
		return fmt.Sprintf("invalid group count: expected 5, found %d", hyphens+1)
	}
	starts := [5]int{0, 9, 14, 19, 24}
	expectedLen := [5]int{8, 4, 4, 4, 12}
	for i := range 4 {
		if bounds[i] != starts[i+1]-1 {
			return fmt.Sprintf("invalid group length in group %d: expected %d, found %d", i, expectedLen[i], bounds[i]-starts[i])
		}
	}
	return fmt.Sprintf("invalid group length in group 4: expected 12, found %d", len(input)-starts[4])
}

// ValidateUUID parses s and returns the field error pydantic reports.
func ValidateUUID(s string, loc ...any) (string, *FieldError) {
	id, reason := ParseUUID(s)
	if reason != "" {
		e := UUIDParsing(reason, loc...)
		return "", &e
	}
	return id, nil
}

// WorkspaceParam is the path parameter every workspace route carries.
const WorkspaceParam = "workspace"

// WorkspacePrefix is the workspace route group's prefix (router.py WORKSPACE_PREFIX).
const WorkspacePrefix = "/v1/workspaces/{workspace}"

// WorkspaceSlugPattern is WORKSPACE_SLUG_PATTERN, as pydantic quotes it.
const WorkspaceSlugPattern = `^[a-z0-9]+(?:-[a-z0-9]+)*$`

// ValidateWorkspacePath is router.py's _workspace_path: the slug's length,
// then its pattern, reported at ("path", "workspace").
func ValidateWorkspacePath(slug string) *FieldError {
	if utf8.RuneCountInString(slug) > scope.WorkspaceSlugColumnLength {
		e := StringTooLong(scope.WorkspaceSlugColumnLength, "path", WorkspaceParam)
		return &e
	}
	if !scope.ValidWorkspaceSlug(slug) {
		e := StringPatternMismatch(WorkspaceSlugPattern, "path", WorkspaceParam)
		return &e
	}
	return nil
}
