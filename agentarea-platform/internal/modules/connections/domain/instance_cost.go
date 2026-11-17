package domain

import (
	"encoding/json"
	"math/big"
	"regexp"
	"strings"
)

var (
	currencyCode = regexp.MustCompile(`^[A-Z]{3}$`)
	costPath     = regexp.MustCompile(`^\$(?:\.[A-Za-z_][A-Za-z0-9_\-]*|\[\d+\])*$`)
	decimalText  = regexp.MustCompile(`^[+-]?(?:\d+(?:_\d+)*(?:\.(?:\d+(?:_\d+)*)?)?|\.\d+(?:_\d+)*)(?:[eE][+-]?\d+(?:_\d+)*)?$`)
	specialText  = regexp.MustCompile(`^(?i)[+-]?(?:inf|infinity|s?nan\d*)$`)
)

func costDecimal(v any, where string) string {
	if _, ok := v.(bool); ok {
		return where + " must be a number"
	}
	text := pyStr(v)
	switch v.(type) {
	case json.Number, float64:
		text = PyRepr(v)
	}
	text = strings.TrimSpace(text)
	if specialText.MatchString(text) {
		return where + " must be a non-negative number, got " + PyRepr(v)
	}
	if !decimalText.MatchString(text) {
		return where + " must be a number, got " + PyRepr(v)
	}
	r, ok := new(big.Rat).SetString(strings.ReplaceAll(text, "_", ""))
	if !ok {
		return where + " must be a number, got " + PyRepr(v)
	}
	if r.Sign() < 0 {
		return where + " must be a non-negative number, got " + PyRepr(v)
	}
	return ""
}

func costCurrency(v any, where string) string {
	if s, ok := v.(string); ok && s == "USDC" {
		return ""
	}
	if s, ok := v.(string); !ok || !currencyCode.MatchString(s) {
		return where + " must be an ISO 4217 code like RUB, got " + PyRepr(v)
	}
	return ""
}

func costValidPath(v any, where string) string {
	if s, ok := v.(string); !ok || !costPath.MatchString(s) {
		return where + " must be a path like $.field, got " + PyRepr(v)
	}
	return ""
}

func costQuantity(raw any) string {
	if raw == nil {
		return ""
	}
	m, ok := raw.(map[string]any)
	if !ok {
		return costDecimal(raw, "rate.quantity")
	}
	others := 0
	for k := range m {
		switch k {
		case "arg", "count", "path":
			others++
		case "default":
		default:
			return "rate.quantity must be one of arg, count, path; got " + PyRepr(raw)
		}
	}
	if others != 1 {
		return "rate.quantity must be one of arg, count, path; got " + PyRepr(raw)
	}
	if a, has := m["arg"]; has {
		if s, ok := a.(string); !ok || s == "" {
			return "rate.quantity.arg must name an argument"
		}
		if d := m["default"]; d != nil {
			return costDecimal(d, "rate.quantity.default")
		}
		return ""
	}
	if _, has := m["default"]; has {
		return "rate.quantity.default applies only to arg"
	}
	if c, has := m["count"]; has {
		return costValidPath(c, "rate.quantity.count")
	}
	return costValidPath(m["path"], "rate.quantity.path")
}

// ConnectionCostError is parse_connection_cost: why a member-set cost is
// refused, "" when it is a valid rate, reported field or free cost.
func ConnectionCostError(raw map[string]any) string {
	source, _ := raw["source"].(string)
	switch source {
	case "free", "rate", "reported", "settled", "unknown":
	default:
		return "unknown cost source " + PyRepr(raw["source"])
	}
	if u, has := raw["unit"]; has && Truthy(u) {
		if _, ok := u.(string); !ok {
			return "unit must be a string"
		}
	}
	if e, has := raw["exact"]; has {
		if _, ok := e.(bool); !ok {
			return "exact must be true or false"
		}
	}
	if est, has := raw["estimate"]; has && est != nil {
		e, ok := est.(map[string]any)
		if !ok {
			return "estimate declares {amount, currency}"
		}
		if msg := costDecimal(e["amount"], "estimate.amount"); msg != "" {
			return msg
		}
		if msg := costCurrency(e["currency"], "estimate.currency"); msg != "" {
			return msg
		}
	}
	switch source {
	case "rate":
		rate, ok := raw["rate"].(map[string]any)
		if !ok {
			return "a rate cost declares rate: {amount, currency}"
		}
		if msg := costDecimal(rate["amount"], "rate.amount"); msg != "" {
			return msg
		}
		if msg := costCurrency(rate["currency"], "rate.currency"); msg != "" {
			return msg
		}
		return costQuantity(rate["quantity"])
	case "reported":
		rep, ok := raw["reported"].(map[string]any)
		_, hasPath := rep["path"]
		meta, hasMeta := rep["meta"]
		if !ok || (!hasPath && !hasMeta) {
			return "a reported cost declares reported: {path | meta [+ path], currency}"
		}
		if hasMeta {
			if s, ok := meta.(string); !ok || s == "" {
				return "reported.meta must name a _meta key"
			}
		}
		if msg := costCurrency(rep["currency"], "reported.currency"); msg != "" {
			return msg
		}
		if hasPath {
			return costValidPath(rep["path"], "reported.path")
		}
		return ""
	case "free":
		return ""
	}
	return "a connection's own cost is a rate, a reported field or free, not " + source
}
