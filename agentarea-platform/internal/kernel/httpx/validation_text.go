package httpx

import (
	"fmt"
	"strings"
)

// ModelValidationError is a pydantic ValidationError raised outside a request
// (a platform tool validating its arguments): str() of it is the message.
type ModelValidationError struct {
	Model  string
	Errors []FieldError
}

// Error is str(ValidationError) without the input values; a leading
// "body" or "query" location is left out.
func (e *ModelValidationError) Error() string {
	noun := "error"
	if len(e.Errors) != 1 {
		noun = "errors"
	}
	var b strings.Builder
	fmt.Fprintf(&b, "%d validation %s for %s", len(e.Errors), noun, e.Model)
	for _, fe := range e.Errors {
		loc := fe.Loc
		if len(loc) > 0 && (loc[0] == "body" || loc[0] == "query") {
			loc = loc[1:]
		}
		parts := make([]string, len(loc))
		for i, p := range loc {
			parts[i] = fmt.Sprint(p)
		}
		fmt.Fprintf(&b, "\n%s\n  %s [type=%s]", strings.Join(parts, "."), fe.Msg, fe.Type)
	}
	return b.String()
}
