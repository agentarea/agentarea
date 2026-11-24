package transport

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net"
	"strings"
	"unicode/utf8"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/netguard"
)

// EndpointRefused is what a caller sees when the outbound policy refuses an
// endpoint; the guard's own words name the resolved address and go to the log only.
const EndpointRefused = "the endpoint URL points to an address this deployment does not call"

// ProviderHTTPError is LLMProviderHTTPError: the provider answered with an error status.
type ProviderHTTPError struct {
	StatusCode      int
	ProviderMessage string
}

// HTTPStatus is the status the provider answered.
func (e *ProviderHTTPError) HTTPStatus() int { return e.StatusCode }

func (e *ProviderHTTPError) Error() string {
	return fmt.Sprintf("Provider returned HTTP %d: %s", e.StatusCode, e.ProviderMessage)
}

// UnsafeURLError is UnsafeUrlError raised by a model call: the endpoint was refused.
type UnsafeURLError struct {
	Msg   string
	Cause error
}

func (e *UnsafeURLError) Error() string { return e.Msg }
func (e *UnsafeURLError) Unwrap() error { return e.Cause }

// NoAddressError is the ValueError of a provider with no base_url and no endpoint.
type NoAddressError struct{ ProviderType string }

func (e *NoAddressError) Error() string {
	return fmt.Sprintf("Provider '%s' has no public address and no endpoint_url is configured", e.ProviderType)
}

// TransportError is an httpx transport failure: Kind is the httpx class name
// (ConnectError, ReadTimeout, ...), Timeout marks httpx.TimeoutException.
type TransportError struct {
	Kind    string
	Timeout bool
	Err     error
}

func (e *TransportError) Error() string { return e.Err.Error() }
func (e *TransportError) Unwrap() error { return e.Err }

// classifyTransport turns a client error into what httpx would have raised.
func classifyTransport(err error, phase string) error {
	if errors.Is(err, netguard.ErrUnsafe) {
		return &UnsafeURLError{Msg: EndpointRefused, Cause: err}
	}
	if errors.Is(err, context.Canceled) {
		return err
	}
	var nerr net.Error
	timeout := errors.Is(err, context.DeadlineExceeded) || errors.Is(err, errIdle) || (errors.As(err, &nerr) && nerr.Timeout())
	kind := "ConnectError"
	switch {
	case timeout && phase == "connect":
		kind = "ConnectTimeout"
	case timeout && phase == "write":
		kind = "WriteTimeout"
	case timeout:
		kind = "ReadTimeout"
	case phase == "write":
		kind = "WriteError"
	case phase == "read":
		kind = "ReadError"
	}
	return &TransportError{Kind: kind, Timeout: timeout, Err: err}
}

// replaceInvalid is decode("utf-8", errors="replace"): one U+FFFD per byte that starts no valid sequence.
func replaceInvalid(b []byte) string {
	if utf8.Valid(b) {
		return string(b)
	}
	var sb strings.Builder
	for len(b) > 0 {
		r, size := utf8.DecodeRune(b)
		sb.WriteRune(r)
		b = b[size:]
	}
	return sb.String()
}

// errorBodyMessage is _error_body_message: the provider's own words from an
// error body, at most 500 characters.
func errorBodyMessage(body []byte) string {
	text := strings.TrimSpace(replaceInvalid(body))
	var parsed any
	if err := json.Unmarshal([]byte(text), &parsed); err != nil {
		return truncate(text, 500)
	}
	obj, isObj := parsed.(map[string]any)
	if isObj {
		switch e := obj["error"].(type) {
		case map[string]any:
			if m, ok := e["message"].(string); ok {
				return truncate(m, 500)
			}
		case string:
			return truncate(e, 500)
		}
		if m, ok := obj["message"].(string); ok {
			return truncate(m, 500)
		}
	}
	return truncate(text, 500)
}

// truncate keeps the first n characters (Python slices code points).
func truncate(s string, n int) string {
	if utf8.RuneCountInString(s) <= n {
		return s
	}
	r := []rune(s)
	return string(r[:n])
}
