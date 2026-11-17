package obs

import (
	"log/slog"
	"regexp"
)

// pySpace is Python's \s on str: ASCII whitespace plus \x1c-\x1f and the
// Unicode spaces str.isspace() admits; RE2's \s is ASCII only.
const pySpace = `\t\n\v\f\r \x1c-\x1f\x{85}\x{a0}\x{1680}\x{2000}-\x{200a}\x{2028}\x{2029}\x{202f}\x{205f}\x{3000}`

type redaction struct {
	re   *regexp.Regexp
	repl string
}

// redactions are filters.py's _REDACTIONS, matched by the shape of the
// string a credential sits in, never by a nearby name.
func redactions() []redaction {
	return []redaction{
		{regexp.MustCompile(`(/bot)\p{Nd}+:[A-Za-z0-9_-]{20,}`), `${1}<redacted>`},
		{regexp.MustCompile(`(://[^:/` + pySpace + `@]+:)[^@/` + pySpace + `]+(@)`), `${1}<redacted>${2}`},
		{regexp.MustCompile(`(?i)\b(bearer[` + pySpace + `]+)[A-Za-z0-9._~+/=-]{8,}`), `${1}<redacted>`},
		{regexp.MustCompile(`(?i)([?&](?:api[_-]?key|access[_-]?token|token|password)=)[^&` + pySpace + `"']+`), `${1}<redacted>`},
	}
}

// controlChars are what LogSanitizerFilter turns into spaces in a message:
// CR, LF and the other C0 controls except tab.
var controlChars = regexp.MustCompile(`[\r\n\x00-\x08\x0b\x0c\x0e-\x1f]`)

// SecretRedactor is SecretRedactingFilter: it rewrites strings only, at the
// top level of a record (Python's extra= values), as the filter does.
type SecretRedactor struct{ rules []redaction }

// NewSecretRedactor builds the redactor.
func NewSecretRedactor() *SecretRedactor { return &SecretRedactor{rules: redactions()} }

// RedactString applies every rule to s.
func (r *SecretRedactor) RedactString(s string) string {
	for _, rule := range r.rules {
		s = rule.re.ReplaceAllString(s, rule.repl)
	}
	return s
}

// Redact masks a string attribute; other kinds pass unchanged.
func (r *SecretRedactor) Redact(_ string, v slog.Value) slog.Value {
	if v.Kind() != slog.KindString {
		return v
	}
	if s := v.String(); s != "" {
		if red := r.RedactString(s); red != s {
			return slog.StringValue(red)
		}
	}
	return v
}

// Sanitize is LogSanitizerFilter on a message.
func Sanitize(msg string) string { return controlChars.ReplaceAllString(msg, " ") }
