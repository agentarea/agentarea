// Package config loads typed configuration from the environment.
//
// Names follow .agents/skills/aa-env-vars: AGENTAREA_<DOMAIN>_<KEY> for ours,
// a standard's own name (PORT, TEMPORAL_ADDRESS, OTEL_*) where a library reads
// it. Every read goes through a Loader method whose name ends in Env with the
// variable name as a literal, so scripts/check_env_naming.py sees it.
//
// A Loader collects every problem instead of stopping at the first, and Err
// names each variable: configuration without which the process cannot work
// has no default and fails startup (no fallbacks, no aliases).
//
// Each kernel package and module owns its own settings struct and loads it
// from a Loader; there is no global settings container (rule 6).
package config

import (
	"errors"
	"fmt"
	"os"
	"strconv"
	"strings"
	"time"
)

// Lookup returns a variable's value and whether it is set (os.LookupEnv).
type Lookup func(name string) (string, bool)

// Loader reads variables through a Lookup and records every failure.
type Loader struct {
	lookup Lookup
	errs   []error
}

// New reads through lookup; tests pass a map's lookup.
func New(lookup Lookup) *Loader { return &Loader{lookup: lookup} }

// FromEnviron reads the process environment.
func FromEnviron() *Loader { return New(os.LookupEnv) }

// FromMap reads a fixed set of variables.
func FromMap(vars map[string]string) *Loader {
	return New(func(name string) (string, bool) {
		v, ok := vars[name]
		return v, ok
	})
}

// VarError names the variable a failure is about.
type VarError struct {
	Name string
	Err  error
}

func (e *VarError) Error() string { return e.Name + ": " + e.Err.Error() }

func (e *VarError) Unwrap() error { return e.Err }

// ErrMissing is wrapped by the error of a required variable that is unset.
var ErrMissing = errors.New("is required and not set")

// Fail records a failure about name, for validation the Loader cannot do.
func (l *Loader) Fail(name string, err error) {
	l.errs = append(l.errs, &VarError{Name: name, Err: err})
}

// Err is every recorded failure, joined; nil when there is none.
func (l *Loader) Err() error { return errors.Join(l.errs...) }

// raw returns the trimmed value; an empty value counts as unset.
func (l *Loader) raw(name string) (string, bool) {
	v, ok := l.lookup(name)
	v = strings.TrimSpace(v)
	return v, ok && v != ""
}

// RequiredEnv is a string that must be set.
func (l *Loader) RequiredEnv(name string) string {
	v, ok := l.raw(name)
	if !ok {
		l.Fail(name, ErrMissing)
	}
	return v
}

// StringEnv is a string with a default.
func (l *Loader) StringEnv(name, def string) string {
	if v, ok := l.raw(name); ok {
		return v
	}
	return def
}

// OptionalEnv is a string and whether it was set; no default.
func (l *Loader) OptionalEnv(name string) (string, bool) { return l.raw(name) }

// IntEnv is an integer with a default.
func (l *Loader) IntEnv(name string, def int) int {
	v, ok := l.raw(name)
	if !ok {
		return def
	}
	n, err := strconv.Atoi(strings.ReplaceAll(v, "_", ""))
	if err != nil {
		l.Fail(name, fmt.Errorf("must be an integer, got %q", v))
		return def
	}
	return n
}

// BoolEnv is a boolean with a default. It accepts what pydantic accepts, so a
// value Python reads reads the same here: 1/0, true/false, t/f, yes/no, y/n,
// on/off, in any case.
func (l *Loader) BoolEnv(name string, def bool) bool {
	v, ok := l.raw(name)
	if !ok {
		return def
	}
	b, err := ParseBool(v)
	if err != nil {
		l.Fail(name, err)
		return def
	}
	return b
}

// DurationEnv is a duration with a default, written with its unit as
// config/duration.py reads it: 30s, 500ms, 5m, 2h, 7d. A bare number is refused.
func (l *Loader) DurationEnv(name string, def time.Duration) time.Duration {
	v, ok := l.raw(name)
	if !ok {
		return def
	}
	d, err := ParseDuration(v)
	if err != nil {
		l.Fail(name, err)
		return def
	}
	return d
}

// ListEnv is a comma-separated list, entries trimmed, empty entries dropped.
func (l *Loader) ListEnv(name string, def []string) []string {
	v, ok := l.raw(name)
	if !ok {
		return def
	}
	var out []string
	for _, part := range strings.Split(v, ",") {
		if p := strings.TrimSpace(part); p != "" {
			out = append(out, p)
		}
	}
	return out
}

// OneOfEnv is a string restricted to allowed values (compared case-insensitively,
// returned as listed in allowed).
func (l *Loader) OneOfEnv(name, def string, allowed ...string) string {
	v, ok := l.raw(name)
	if !ok {
		return def
	}
	for _, a := range allowed {
		if strings.EqualFold(a, v) {
			return a
		}
	}
	l.Fail(name, fmt.Errorf("must be one of %s, got %q", strings.Join(allowed, ", "), v))
	return def
}

// ParseBool reads the boolean spellings pydantic accepts.
func ParseBool(v string) (bool, error) {
	switch strings.ToLower(strings.TrimSpace(v)) {
	case "1", "true", "t", "yes", "y", "on":
		return true, nil
	case "0", "false", "f", "no", "n", "off":
		return false, nil
	}
	return false, fmt.Errorf("must be true or false, got %q", v)
}

// ParseDuration reads number+unit with unit ms, s, m, h or d; the number may
// have a fraction ("1.5h"). Matches config/duration.py parse_duration.
func ParseDuration(v string) (time.Duration, error) {
	text := strings.TrimSpace(v)
	units := []struct {
		suffix string
		unit   time.Duration
	}{{"ms", time.Millisecond}, {"s", time.Second}, {"m", time.Minute}, {"h", time.Hour}, {"d", 24 * time.Hour}}
	for _, u := range units {
		num, ok := strings.CutSuffix(text, u.suffix)
		if !ok || !isDecimal(num) {
			continue
		}
		f, err := strconv.ParseFloat(num, 64)
		if err != nil {
			break
		}
		return time.Duration(f * float64(u.unit)), nil
	}
	return 0, fmt.Errorf("duration must be a number followed by ms/s/m/h/d (e.g. '30s', '500ms'), got %q", text)
}

// isDecimal matches \d+(\.\d+)?
func isDecimal(s string) bool {
	whole, frac, hasDot := strings.Cut(s, ".")
	return allDigits(whole) && (!hasDot || allDigits(frac))
}

func allDigits(s string) bool {
	if s == "" {
		return false
	}
	for i := range len(s) {
		if s[i] < '0' || s[i] > '9' {
			return false
		}
	}
	return true
}
