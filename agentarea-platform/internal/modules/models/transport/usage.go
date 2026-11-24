package transport

import (
	"encoding/json"
	"math"
	"strconv"
	"strings"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/money"
)

// Usage is LLMUsage: Prompt counts every prompt token, cached or not.
type Usage struct {
	Prompt, Completion, Total, CachedPrompt, CacheCreation int64
}

// Prices are a model spec's USD prices per token; nil is unknown.
type Prices struct {
	Input, Output, CachedInput, CacheCreation *money.Decimal
}

// tokens is _tokens over a JSON value decoded with UseNumber: a number
// (int truncated from a float) floored at 0; anything else 0.
func tokens(v any) int64 {
	n, ok := v.(json.Number)
	if !ok {
		return 0
	}
	if i, err := strconv.ParseInt(string(n), 10, 64); err == nil {
		return max(i, 0)
	}
	f, err := strconv.ParseFloat(string(n), 64)
	if err != nil || math.IsNaN(f) || math.IsInf(f, 0) {
		return 0
	}
	return max(int64(f), 0)
}

func fields(v any) map[string]any {
	m, _ := v.(map[string]any)
	return m
}

// UsageFromProvider is usage_from_provider: an OpenAI- or Anthropic-shaped
// usage block. Zero everywhere means none was reported.
func UsageFromProvider(raw map[string]any) Usage {
	details := fields(raw["prompt_tokens_details"])
	cacheRead := tokens(raw["cache_read_input_tokens"])
	cacheWrite := tokens(raw["cache_creation_input_tokens"])
	var prompt, completion int64
	if raw["prompt_tokens"] == nil && raw["input_tokens"] != nil {
		prompt = tokens(raw["input_tokens"]) + cacheRead + cacheWrite
		completion = tokens(raw["output_tokens"])
	} else {
		prompt = tokens(raw["prompt_tokens"])
		completion = tokens(raw["completion_tokens"])
	}
	cached := tokens(details["cached_tokens"])
	if cached == 0 {
		cached = cacheRead
	}
	if cached == 0 {
		cached = tokens(raw["prompt_cache_hit_tokens"])
	}
	total := tokens(raw["total_tokens"])
	if total == 0 {
		total = prompt + completion
	}
	creation := tokens(details["cache_creation_tokens"])
	if creation == 0 {
		creation = tokens(details["cache_write_tokens"])
	}
	if creation == 0 {
		creation = cacheWrite
	}
	return Usage{Prompt: prompt, Completion: completion, Total: total, CachedPrompt: min(cached, prompt), CacheCreation: creation}
}

// ProviderReportedCost is provider_reported_cost: usage.cost when it is a
// finite non-negative number or numeric string; nil otherwise.
func ProviderReportedCost(raw map[string]any) *money.Decimal {
	var text string
	switch v := raw["cost"].(type) {
	case json.Number:
		text = PyNumberStr(v)
	case string:
		text = v
	default:
		return nil
	}
	d, err := money.Parse(text)
	if err != nil || d.Sign() < 0 {
		return nil
	}
	return &d
}

// PyNumberStr is str() of the value Python's json.loads gives for n: the
// literal for an integer, else repr(float).
func PyNumberStr(n json.Number) string {
	s := string(n)
	if !strings.ContainsAny(s, ".eE") {
		if strings.TrimLeft(strings.TrimPrefix(s, "-"), "0") == "" {
			return "0"
		}
		return s
	}
	f, err := strconv.ParseFloat(s, 64)
	if err != nil && !math.IsInf(f, 0) {
		return s
	}
	return PyFloatRepr(f)
}

// PyFloatRepr is Python's repr(float): the shortest round-trip digits, fixed
// notation for exponents in [-4, 16), scientific with a two-digit exponent otherwise.
func PyFloatRepr(f float64) string {
	switch {
	case math.IsNaN(f):
		return "nan"
	case math.IsInf(f, 1):
		return "inf"
	case math.IsInf(f, -1):
		return "-inf"
	}
	e := strconv.FormatFloat(f, 'e', -1, 64)
	mant, expStr, _ := strings.Cut(e, "e")
	exp, _ := strconv.Atoi(expStr)
	neg := strings.HasPrefix(mant, "-")
	mant = strings.TrimPrefix(mant, "-")
	digits := strings.Replace(mant, ".", "", 1)
	sign := ""
	if neg {
		sign = "-"
	}
	if exp < -4 || exp >= 16 {
		m := digits[:1]
		if len(digits) > 1 {
			m += "." + digits[1:]
		}
		es := "+"
		if exp < 0 {
			es = "-"
			exp = -exp
		}
		return sign + m + "e" + es + leftPad(strconv.Itoa(exp), 2)
	}
	if exp < 0 {
		return sign + "0." + strings.Repeat("0", -exp-1) + digits
	}
	if len(digits) <= exp+1 {
		return sign + digits + strings.Repeat("0", exp+1-len(digits)) + ".0"
	}
	return sign + digits[:exp+1] + "." + digits[exp+1:]
}

func leftPad(s string, n int) string {
	for len(s) < n {
		s = "0" + s
	}
	return s
}

// ConfiguredCost is LLMModel._configured_cost: unknown base prices cost 0;
// cache read and write rates apply only when the spec declares them.
func ConfiguredCost(p Prices, u Usage) money.Decimal {
	if p.Input == nil || p.Output == nil {
		return money.FromInt(0)
	}
	var cached, written int64
	cachedRate, writtenRate := money.FromInt(0), money.FromInt(0)
	if p.CachedInput != nil {
		cached = min(u.CachedPrompt, u.Prompt)
		if cached != 0 {
			cachedRate = *p.CachedInput
		}
	}
	if p.CacheCreation != nil {
		written = min(u.CacheCreation, u.Prompt-cached)
		if written != 0 {
			writtenRate = *p.CacheCreation
		}
	}
	return money.FromInt(u.Prompt - cached - written).Mul(*p.Input).
		Add(money.FromInt(cached).Mul(cachedRate)).
		Add(money.FromInt(written).Mul(writtenRate)).
		Add(money.FromInt(u.Completion).Mul(*p.Output))
}
