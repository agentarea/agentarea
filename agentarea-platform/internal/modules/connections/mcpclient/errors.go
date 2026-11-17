package mcpclient

import (
	"context"
	"errors"
	"fmt"
	"net"
	"net/url"
	"regexp"
	"strings"
	"syscall"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/netguard"
)

// JSON-RPC and MCP error codes the client reads or synthesizes.
const (
	CodeParseError         = -32700
	CodeInvalidRequest     = -32600
	CodeMethodNotFound     = -32601
	CodeInternalError      = -32603
	CodeRequestTimeout     = -32001
	CodeUnsupportedVersion = -32022
)

// RPCError is a JSON-RPC error the server answered with, or the transport's
// reading of an HTTP status as one (MCPError): the server answered in MCP.
type RPCError struct {
	Code    int    `json:"code"`
	Message string `json:"message"`
	Data    any    `json:"data,omitempty"`
}

func (e *RPCError) Error() string { return e.Message }

// IsTimeout reports a request that got no result within its own limit.
func IsTimeout(err error) bool {
	var rpc *RPCError
	return errors.As(err, &rpc) && rpc.Code == CodeRequestTimeout
}

// IsTerminatedSession is the transport's reading of a 404 on a session the
// server no longer knows.
func IsTerminatedSession(err error) bool {
	var rpc *RPCError
	return errors.As(err, &rpc) && rpc.Code == CodeInvalidRequest && rpc.Message == "Session terminated"
}

// MaxRequiredScopes bounds the scopes an insufficient_scope challenge may name.
const MaxRequiredScopes = 20

// UnauthorizedError is an upstream that refused the credentials with HTTP 401
// or 403 (MCPUpstreamUnauthorizedError). A 403 whose Bearer challenge says
// insufficient_scope refused a credential granted too little.
type UnauthorizedError struct {
	URL               string
	Status            int
	InsufficientScope bool
	RequiredScopes    []string
}

// NewUnauthorizedError reads the challenge of a refusal.
func NewUnauthorizedError(rawURL string, status int, challenge string) *UnauthorizedError {
	e := &UnauthorizedError{URL: rawURL, Status: status}
	bearer := bearerParams(challenge)
	e.InsufficientScope = status == 403 && bearer["error"] == "insufficient_scope"
	if e.InsufficientScope {
		scopes := strings.Fields(bearer["scope"])
		if len(scopes) > MaxRequiredScopes {
			scopes = scopes[:MaxRequiredScopes]
		}
		e.RequiredScopes = scopes
	}
	return e
}

// Refusal is what the server refused, after its name.
func (e *UnauthorizedError) Refusal() string {
	if !e.InsufficientScope {
		return "rejected the credentials"
	}
	short := make([]string, 0, len(e.RequiredScopes))
	for _, s := range e.RequiredScopes {
		short = append(short, ScopeShortName(s))
	}
	missing := ""
	if len(short) > 0 {
		missing = " (" + strings.Join(short, ", ") + ")"
	}
	return "needs access it was not granted" + missing + ": reconnect it and allow that access"
}

// Data is the error's data: the status, and for insufficient_scope the scopes.
func (e *UnauthorizedError) Data() map[string]any {
	d := map[string]any{"status": e.Status}
	if e.InsufficientScope {
		scopes := make([]any, 0, len(e.RequiredScopes))
		for _, s := range e.RequiredScopes {
			scopes = append(scopes, s)
		}
		d["error"] = "insufficient_scope"
		d["required_scopes"] = scopes
	}
	return d
}

func (e *UnauthorizedError) Error() string {
	host := e.URL
	if u, err := url.Parse(e.URL); err == nil && u.Hostname() != "" {
		host = u.Hostname()
	}
	return fmt.Sprintf("%s %s (HTTP %d)", host, e.Refusal(), e.Status)
}

// ScopeShortName is gmail.send for https://www.googleapis.com/auth/gmail.send.
func ScopeShortName(scope string) string {
	trimmed := strings.TrimRight(scope, "/")
	if i := strings.LastIndex(trimmed, "/"); i >= 0 && i < len(trimmed)-1 {
		return trimmed[i+1:]
	}
	if trimmed == "" {
		return scope
	}
	return trimmed
}

var authItem = regexp.MustCompile(`([!#$%&'*+.^_` + "`" + `|~0-9A-Za-z-]+)\s*=\s*("(?:[^"\\]|\\.)*"|[^\s,]*)|([!#$%&'*+.^_` + "`" + `|~0-9A-Za-z-]+)`)

var quotedPair = regexp.MustCompile(`\\(.)`)

// bearerParams is the auth-params of the Bearer challenge in a
// WWW-Authenticate value; names compare case-insensitively.
func bearerParams(challenge string) map[string]string {
	params := map[string]string{}
	scheme := ""
	for _, m := range authItem.FindAllStringSubmatch(challenge, -1) {
		if m[3] != "" {
			scheme = strings.ToLower(m[3])
			continue
		}
		if scheme != "bearer" {
			continue
		}
		value := m[2]
		if strings.HasPrefix(value, `"`) && len(value) >= 2 {
			value = quotedPair.ReplaceAllString(value[1:len(value)-1], "$1")
		}
		name := strings.ToLower(m[1])
		if _, ok := params[name]; !ok {
			params[name] = value
		}
	}
	return params
}

// StartupFailureError is a classified startup failure the demand gateway
// answered with (X-AgentArea-MCP-Start-Failure).
type StartupFailureError struct{ Detail string }

func (e *StartupFailureError) Error() string {
	return "MCP workload failed during startup: " + e.Detail
}

// HTTPError is an HTTP status a non-MCP exchange (the SSE stream) answered with.
type HTTPError struct {
	URL    string
	Status int
}

func (e *HTTPError) Error() string {
	return fmt.Sprintf("Server error '%d' for url '%s'", e.Status, e.URL)
}

// IsTransient reports a failure to reach the server at all: a refused or
// reset connection, a timeout, a name that does not resolve yet. The server
// answering anything, an MCP error or an HTTP status, is not one.
func IsTransient(err error) bool {
	if err == nil {
		return false
	}
	var rpc *RPCError
	var un *UnauthorizedError
	var sf *StartupFailureError
	var he *HTTPError
	if errors.As(err, &rpc) || errors.As(err, &un) || errors.As(err, &sf) || errors.As(err, &he) {
		return false
	}
	if errors.Is(err, netguard.ErrUnsafe) {
		return false
	}
	if errors.Is(err, context.DeadlineExceeded) || errors.Is(err, syscall.ECONNREFUSED) ||
		errors.Is(err, syscall.ECONNRESET) {
		return true
	}
	var op *net.OpError
	var dns *net.DNSError
	if errors.As(err, &op) || errors.As(err, &dns) {
		return true
	}
	var ne net.Error
	return errors.As(err, &ne) && ne.Timeout()
}
