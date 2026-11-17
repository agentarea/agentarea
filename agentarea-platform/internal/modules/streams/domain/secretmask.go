package domain

import (
	"regexp"
	"strings"
	"unicode"
	"unicode/utf8"
)

const redacted = "[redacted]"

// maskValue is redaction._VALUE.
const maskValue = `(?:"[^"]*"|'[^']*'|[^\s,;&'"}\]]+)`

var (
	maskAuthorization = regexp.MustCompile(`(?i)\b((?:proxy-)?authorization\s*[:=]\s*)(?:(bearer|basic|token|digest)\s+)?([^\s'",]+)`)
	maskBearer        = regexp.MustCompile(`(?i)\b(bearer\s+)([A-Za-z0-9._~+/=-]{8,})`)
	// maskFlag is _FLAG without its (?<![\w-]) lookbehind, checked by hand.
	maskFlag = regexp.MustCompile(`(--?)([A-Za-z][\w-]*)(=|\s+)(` + maskValue + `)`)
	// maskAssignment is _ASSIGNMENT with its \1 backreference spelled out per quote.
	maskAssignment = regexp.MustCompile(`"([A-Za-z_][\w.-]*)"(\s*[:=]\s*)(` + maskValue + `)` +
		`|'([A-Za-z_][\w.-]*)'(\s*[:=]\s*)(` + maskValue + `)` +
		`|([A-Za-z_][\w.-]*)(\s*[:=]\s*)(` + maskValue + `)`)
	maskURLUserinfo = regexp.MustCompile(`(\b[a-zA-Z][\w+.-]*://[^/\s:@]+:)([^/\s@]+)(@)`)
	// maskUserFlag is _USER_FLAG without its (?<!\S) lookbehind, checked by hand.
	maskUserFlag      = regexp.MustCompile(`((?:-u|--user)[\s=]+['"]?[^:\s'"]+:)([^\s'"]+)`)
	maskMySQLPassword = regexp.MustCompile(`(\b(?:mysql|mysqldump|mysqladmin|mariadb)\b[^|;&\n]*?\s-p)(\S+)`)
	maskSSHPass       = regexp.MustCompile(`(\bsshpass\s+-p\s+)(\S+)`)
	maskTokenShapes   = regexp.MustCompile(`\b(?:(?:sk|rk)-[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9]{20,}|xox[abposr]-[A-Za-z0-9-]{10,}|AKIA[0-9A-Z]{16})\b`)
)

// replaceAll is re.sub: repl gets the text and the submatch indexes of each
// match; accept, when set, is a lookbehind on the text before a match, and a
// refused match is retried one character later as Python's engine would.
func replaceAll(re *regexp.Regexp, s string, accept func(before string) bool, repl func(s string, m []int) string) string {
	var b strings.Builder
	last, pos := 0, 0
	for pos <= len(s) {
		loc := re.FindStringSubmatchIndex(s[pos:])
		if loc == nil {
			break
		}
		for i := range loc {
			if loc[i] >= 0 {
				loc[i] += pos
			}
		}
		if accept != nil && !accept(s[:loc[0]]) {
			_, size := utf8.DecodeRuneInString(s[loc[0]:])
			pos = loc[0] + max(size, 1)
			continue
		}
		b.WriteString(s[last:loc[0]])
		b.WriteString(repl(s, loc))
		last = loc[1]
		if loc[1] == loc[0] {
			_, size := utf8.DecodeRuneInString(s[loc[1]:])
			pos = loc[1] + max(size, 1)
		} else {
			pos = loc[1]
		}
	}
	b.WriteString(s[last:])
	return b.String()
}

func group(s string, m []int, i int) string {
	if m[2*i] < 0 {
		return ""
	}
	return s[m[2*i]:m[2*i+1]]
}

func lastRune(s string) (rune, bool) {
	if s == "" {
		return 0, false
	}
	r, _ := utf8.DecodeLastRuneInString(s)
	return r, true
}

func wordRune(r rune) bool { return r == '_' || unicode.IsLetter(r) || unicode.IsDigit(r) }

func maskedValue(v string) string {
	if len(v) >= 2 && v[0] == v[len(v)-1] && (v[0] == '\'' || v[0] == '"') {
		return v[:1] + redacted + v[:1]
	}
	return redacted
}

// maskNamed is _mask_named: the value group masked when the name group is secret-shaped.
func maskNamed(s string, m []int, nameGroup, valueGroup int) string {
	whole := s[m[0]:m[1]]
	name := strings.ToLower(group(s, m, nameGroup))
	if !secretName(name) || strings.HasSuffix(name, "authorization") {
		return whole
	}
	start, end := m[2*valueGroup]-m[0], m[2*valueGroup+1]-m[0]
	return whole[:start] + maskedValue(whole[start:end]) + whole[end:]
}

// MaskInlineSecrets is mask_inline_secrets (agentarea_common/events/redaction.py): the secret-shaped parts of a text
// masked in place, everything else kept.
func MaskInlineSecrets(text string) string {
	out := replaceAll(maskAuthorization, text, nil, func(s string, m []int) string {
		scheme := ""
		if g := group(s, m, 2); g != "" {
			scheme = g + " "
		}
		return group(s, m, 1) + scheme + redacted
	})
	out = replaceAll(maskBearer, out, nil, func(s string, m []int) string { return group(s, m, 1) + redacted })
	out = replaceAll(maskFlag, out, func(before string) bool {
		r, ok := lastRune(before)
		return !ok || (!wordRune(r) && r != '-')
	}, func(s string, m []int) string { return maskNamed(s, m, 2, 4) })
	out = replaceAll(maskAssignment, out, nil, func(s string, m []int) string {
		switch {
		case m[2] >= 0:
			return maskNamed(s, m, 1, 3)
		case m[8] >= 0:
			return maskNamed(s, m, 4, 6)
		}
		return maskNamed(s, m, 7, 9)
	})
	out = replaceAll(maskURLUserinfo, out, nil, func(s string, m []int) string { return group(s, m, 1) + redacted + group(s, m, 3) })
	out = replaceAll(maskUserFlag, out, func(before string) bool {
		r, ok := lastRune(before)
		return !ok || unicode.IsSpace(r)
	}, func(s string, m []int) string { return group(s, m, 1) + redacted })
	out = replaceAll(maskMySQLPassword, out, nil, func(s string, m []int) string { return group(s, m, 1) + redacted })
	out = replaceAll(maskSSHPass, out, nil, func(s string, m []int) string { return group(s, m, 1) + redacted })
	return maskTokenShapes.ReplaceAllString(out, redacted)
}

func secretName(name string) bool {
	n := strings.ReplaceAll(strings.ToLower(name), "-", "_")
	if strings.Contains(n, "passwd") {
		return true
	}
	for _, f := range []string{"api_key", "authorization", "credential", "password", "secret", "token"} {
		if strings.Contains(n, f) {
			return true
		}
	}
	return false
}
