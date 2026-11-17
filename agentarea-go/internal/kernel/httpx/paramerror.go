package httpx

import (
	"net/http"
	"reflect"
)

// paramValidation turns the parameter errors oapi-codegen's wrappers raise
// (one set of types per generated package) into the 422 FastAPI answers.
func paramValidation(r *http.Request, err error) error {
	v := reflect.ValueOf(err)
	if v.Kind() != reflect.Pointer || v.IsNil() || v.Elem().Kind() != reflect.Struct {
		return nil
	}
	field := v.Elem().FieldByName("ParamName")
	if !field.IsValid() || field.Kind() != reflect.String {
		return nil
	}
	name := field.String()
	where := "query"
	if !r.URL.Query().Has(name) {
		where = "path"
	}
	switch v.Elem().Type().Name() {
	case "RequiredParamError":
		return Validation(Missing("query", name))
	case "RequiredHeaderError":
		return Validation(Missing("header", name))
	case "UnescapedCookieParamError":
		return Validation(StringType("cookie", name))
	case "InvalidParamFormatError", "UnmarshalingParamError", "TooManyValuesForParamError":
		if _, fe := ValidateInt(r.URL.Query().Get(name), IntBounds{}, where, name); fe != nil && looksNumeric(v) {
			return Validation(*fe)
		}
		return Validation(FieldError{Type: "value_error", Loc: []any{where, name}, Msg: "Input is not a valid value"})
	}
	return nil
}

// looksNumeric reports whether the wrapped parse error came from reading a number.
func looksNumeric(v reflect.Value) bool {
	f := v.Elem().FieldByName("Err")
	if !f.IsValid() || f.IsNil() {
		return false
	}
	e, ok := f.Interface().(error)
	if !ok {
		return false
	}
	return errorType(e) == "NumError"
}
