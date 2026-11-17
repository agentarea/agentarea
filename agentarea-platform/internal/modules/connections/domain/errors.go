// Package domain holds connections' types and rules, with no I/O.
package domain

import (
	"encoding/json"
	"strings"
)

// Invalid is a refused input the Python service raises as ValueError: the
// detail is the message, status 400.
type Invalid struct{ Msg string }

func (e *Invalid) Error() string { return e.Msg }

// Linked is a refusal to delete a row another connection still uses: 409.
type Linked struct{ Msg string }

func (e *Linked) Error() string { return e.Msg }

// NotFound is a missing row named by its message, 404.
type NotFound struct{ Msg string }

func (e *NotFound) Error() string { return e.Msg }

// Truthy is Python's truthiness for the JSON values a config holds.
func Truthy(v any) bool {
	switch t := v.(type) {
	case nil:
		return false
	case string:
		return t != ""
	case bool:
		return t
	case float64:
		return t != 0
	case int:
		return t != 0
	case json.Number:
		f, err := t.Float64()
		return err != nil || f != 0
	case []any:
		return len(t) > 0
	case map[string]any:
		return len(t) > 0
	}
	return true
}

// quoted renders a list the way Python's repr writes a list of strings.
func quoted(items []string) string {
	parts := make([]string, len(items))
	for i, s := range items {
		parts[i] = "'" + s + "'"
	}
	return "[" + strings.Join(parts, ", ") + "]"
}

// LinkedMessage is the 409 detail for an auth config still in use.
func LinkedMessage(id string, linked []string) string {
	return "Cannot delete auth config " + id + ": linked to connections " + quoted(linked)
}

// ErrLinkNotFound is the 404 of a link the workspace does not have.
func ErrLinkNotFound() error { return &NotFound{Msg: "OAuth link not found"} }

// ErrConnectionNotFound is the 404 of an OpenAPI connection the workspace does not have.
func ErrConnectionNotFound() error { return &NotFound{Msg: "Connection not found"} }

// Forbidden is a refusal the caller cannot get past by asking again: 403 with its message.
type Forbidden struct{ Msg string }

func (e *Forbidden) Error() string { return e.Msg }

// Unavailable is a dependency that did not answer: 503 with its message.
type Unavailable struct{ Msg string }

func (e *Unavailable) Error() string { return e.Msg }

// ReauthRequired is OAuthReauthRequiredError: the OAuth session cannot be
// renewed unattended; the user must reconnect.
type ReauthRequired struct{ Msg string }

func (e *ReauthRequired) Error() string { return e.Msg }
