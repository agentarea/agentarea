// Package analytics is how modules count failures that leave no row for the
// installation's usage analytics (analytics/counters.py). The sender that
// sends the counts is insights'; a module only holds a Counter, which counts
// nothing while analytics is off.
package analytics

import (
	"regexp"
	"strings"
	"sync/atomic"
)

// Counter adds one to the counter name under labels.
type Counter interface {
	Count(name string, labels map[string]string)
}

// Count adds one to name under labels; a nil c counts nothing. Each label value that is not
// enum-like is sent as "other" (EnumLabel).
func Count(c Counter, name string, labels map[string]string) {
	if c == nil {
		return
	}
	clean := make(map[string]string, len(labels))
	for k, v := range labels {
		clean[k] = EnumLabel(v)
	}
	c.Count(name, clean)
}

var labelValue = regexp.MustCompile(`^[a-z0-9][a-z0-9_.-]{0,63}$`)

// EnumLabel is enum_label: v lower-cased when enum-like, else "other"; "failed:<code>" keeps
// its prefix when only the code is not.
func EnumLabel(v string) string {
	parts := strings.SplitN(strings.ToLower(v), ":", 2)
	for i, p := range parts {
		if !labelValue.MatchString(p) {
			parts[i] = "other"
		}
	}
	return strings.Join(parts, ":")
}

// RunRefused is count_run_refused: a run the gate or billing refused. code is the entitlement
// code, nil for a policy denial; billing that could not answer refused nothing and is not counted.
func RunRefused(c Counter, code *string) {
	reason := "policy_denied"
	if code != nil {
		switch *code {
		case "billing_unavailable", "billing_error", "account_unresolved":
			return
		case "no_credits", "credit_limit_reached":
			reason = "no_credits"
		default:
			reason = "other"
		}
	}
	Count(c, "run_refused", map[string]string{"reason": reason})
}

// Handle is the process's Counter: it forwards to the sender attached to it and counts nothing
// before one is attached or after it is detached (runtime.py current_sender).
type Handle struct {
	to atomic.Pointer[box]
}

type box struct{ c Counter }

// Attach forwards every count from now on to c.
func (h *Handle) Attach(c Counter) { h.to.Store(&box{c}) }

// Detach stops forwarding.
func (h *Handle) Detach() { h.to.Store(nil) }

// Count implements Counter; a nil h counts nothing.
func (h *Handle) Count(name string, labels map[string]string) {
	if h == nil {
		return
	}
	if b := h.to.Load(); b != nil {
		b.c.Count(name, labels)
	}
}
