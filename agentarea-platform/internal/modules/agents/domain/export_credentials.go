package domain

import (
	"errors"
	"net/netip"
	"net/url"
	"regexp"
	"strconv"
	"strings"
	"unicode"
)

var (
	exportNonAlnumRunRE = regexp.MustCompile(`[^a-zA-Z0-9]+`)
	exportNonAlnumRE    = regexp.MustCompile(`[^a-zA-Z0-9]`)
	exportCredWordsRE   = regexp.MustCompile(`(?i)token|secret|passw|pwd|api[_-]?key|apikey|access[_-]?key|private[_-]?key|` +
		`credential|bearer|cookie|session|authorization|auth[_-]?key|signature`)
	exportHeaderKeyRE = regexp.MustCompile(`^[A-Za-z0-9_-]+$`)
	exportIPvFutureRE = regexp.MustCompile(`^v[a-fA-F0-9]+\..+$`)
)

func exportCredentialExactName(n string) bool {
	switch n {
	case "key", "sig", "auth", "pass", "code":
		return true
	}
	return false
}

// exportPySpace is str.isspace().
func exportPySpace(r rune) bool { return unicode.IsSpace(r) || (r >= 0x1c && r <= 0x1f) }

func exportPyStrip(s string) string { return strings.TrimFunc(s, exportPySpace) }

// ExportBundleKey is _bundle_key.
func ExportBundleKey(kind, name, identifier string) string {
	slug := strings.ToLower(strings.Trim(exportNonAlnumRunRE.ReplaceAllString(name, "_"), "_"))
	if len(slug) > 64 {
		slug = slug[:64]
	}
	slug = strings.TrimRight(slug, "_")
	if slug == "" {
		slug = "resource"
	}
	suffix := strings.ToLower(exportNonAlnumRE.ReplaceAllString(identifier, ""))
	if suffix != "" {
		return kind + "_" + slug + "_" + suffix
	}
	return kind + "_" + slug
}

// ExportSetupKey is _setup_key.
func ExportSetupKey(name string) string {
	n := strings.ToLower(strings.Trim(exportNonAlnumRunRE.ReplaceAllString(name, "_"), "_"))
	if n == "" {
		n = "value"
	}
	return "setup_" + n
}

// ExportIsCredentialName is _is_credential_name.
func ExportIsCredentialName(name string) bool {
	n := strings.TrimLeft(exportPyStrip(name), "-")
	return exportCredWordsRE.MatchString(n) || exportCredentialExactName(strings.ToLower(n))
}

func exportIsURL(v string) bool { return strings.Contains(v, "://") }

type exportURLParts struct {
	hasPassword bool
	path, query string
}

var errExportBadURL = errors.New("invalid URL")

// exportURLSplit is the part of urllib.parse.urlsplit the screening reads.
func exportURLSplit(raw string) (exportURLParts, error) {
	raw = strings.TrimLeftFunc(raw, func(r rune) bool { return r <= ' ' })
	raw = strings.Map(func(r rune) rune {
		if r == '\t' || r == '\r' || r == '\n' {
			return -1
		}
		return r
	}, raw)
	if i := strings.IndexByte(raw, ':'); i > 0 && exportSchemeOK(raw[:i]) {
		raw = raw[i+1:]
	}
	var p exportURLParts
	if strings.HasPrefix(raw, "//") {
		rest := raw[2:]
		end := strings.IndexAny(rest, "/?#")
		if end < 0 {
			end = len(rest)
		}
		netloc := rest[:end]
		raw = rest[end:]
		open, closed := strings.Contains(netloc, "["), strings.Contains(netloc, "]")
		if open != closed {
			return p, errExportBadURL
		}
		if open && closed {
			if err := exportCheckBracketed(netloc); err != nil {
				return p, err
			}
		}
		if at := strings.LastIndexByte(netloc, '@'); at >= 0 {
			p.hasPassword = strings.Contains(netloc[:at], ":")
		}
	}
	if i := strings.IndexByte(raw, '#'); i >= 0 {
		raw = raw[:i]
	}
	if i := strings.IndexByte(raw, '?'); i >= 0 {
		p.query = raw[i+1:]
		raw = raw[:i]
	}
	p.path = raw
	return p, nil
}

func exportSchemeOK(s string) bool {
	if !exportAlpha(s[0]) {
		return false
	}
	for i := 0; i < len(s); i++ {
		c := s[i]
		if !exportAlpha(c) && (c < '0' || c > '9') && c != '+' && c != '-' && c != '.' {
			return false
		}
	}
	return true
}

func exportAlpha(c byte) bool { return c >= 'a' && c <= 'z' || c >= 'A' && c <= 'Z' }

func exportCheckBracketed(netloc string) error {
	hostPort := netloc[strings.LastIndexByte(netloc, '@')+1:]
	before, bracketed, found := strings.Cut(hostPort, "[")
	if !found {
		return nil
	}
	if before != "" {
		return errExportBadURL
	}
	host, port, _ := strings.Cut(bracketed, "]")
	if port != "" && !strings.HasPrefix(port, ":") {
		return errExportBadURL
	}
	if strings.HasPrefix(host, "v") {
		if !exportIPvFutureRE.MatchString(host) {
			return errExportBadURL
		}
		return nil
	}
	addr, err := netip.ParseAddr(host)
	if err != nil || addr.Is4() {
		return errExportBadURL
	}
	return nil
}

// exportQueryNames are the names parse_qsl yields (blank values dropped).
func exportQueryNames(q string) []string {
	var names []string
	for _, field := range strings.Split(q, "&") {
		if field == "" {
			continue
		}
		name, value, ok := strings.Cut(field, "=")
		if !ok || value == "" {
			continue
		}
		if n, err := url.QueryUnescape(strings.ReplaceAll(name, "+", " ")); err == nil {
			name = n
		} else {
			name = exportUnquoteLoose(strings.ReplaceAll(name, "+", " "))
		}
		names = append(names, name)
	}
	return names
}

// exportUnquoteLoose is urllib's unquote: a malformed escape stays as written.
func exportUnquoteLoose(s string) string {
	var b strings.Builder
	for i := 0; i < len(s); i++ {
		if s[i] == '%' && i+2 < len(s) && exportHex(s[i+1]) && exportHex(s[i+2]) {
			if v, err := url.PathUnescape(s[i : i+3]); err == nil {
				b.WriteString(v)
				i += 2
				continue
			}
		}
		b.WriteByte(s[i])
	}
	return strings.ToValidUTF8(b.String(), "�")
}

func exportHex(c byte) bool {
	return c >= '0' && c <= '9' || c >= 'a' && c <= 'f' || c >= 'A' && c <= 'F'
}

func exportOpaqueSegment(s string) bool {
	if len(s) < 24 {
		return false
	}
	digit, letter := false, false
	for i := 0; i < len(s); i++ {
		c := s[i]
		switch {
		case c >= '0' && c <= '9':
			digit = true
		case c >= 'a' && c <= 'z' || c >= 'A' && c <= 'Z':
			letter = true
		case c == '_' || c == '-':
		default:
			return false
		}
	}
	return digit && letter
}

// ExportURLCarriesCredentials is _url_carries_credentials.
func ExportURLCarriesCredentials(v string) bool {
	p, err := exportURLSplit(v)
	if err != nil {
		return true
	}
	if p.hasPassword {
		return true
	}
	for _, n := range exportQueryNames(p.query) {
		if ExportIsCredentialName(n) {
			return true
		}
	}
	for _, seg := range strings.Split(p.path, "/") {
		if exportOpaqueSegment(seg) {
			return true
		}
	}
	return false
}

// exportCredentialValue is _CREDENTIAL_VALUE_RE: bearer|basic|token, whitespace, a non-space.
func exportCredentialValue(v string) bool {
	low := strings.ToLower(v)
	for _, w := range []string{"bearer", "basic", "token"} {
		if !strings.HasPrefix(low, w) {
			continue
		}
		rest := []rune(v[len(w):])
		i := 0
		for i < len(rest) && exportPySpace(rest[i]) {
			i++
		}
		if i > 0 && i < len(rest) {
			return true
		}
	}
	return false
}

// ExportValueCarriesCredentials is _value_carries_credentials.
func ExportValueCarriesCredentials(v string) bool {
	if exportIsURL(v) {
		return ExportURLCarriesCredentials(v)
	}
	return exportCredentialValue(exportPyStrip(v))
}

// exportHeaderArg is _HEADER_ARG_RE: name, spaces, ':', spaces, a non-space then the rest.
func exportHeaderArg(arg string) (name, value string, ok bool) {
	n, rest, found := strings.Cut(arg, ":")
	if !found {
		return "", "", false
	}
	n = strings.TrimRightFunc(n, exportPySpace)
	if !exportHeaderKeyRE.MatchString(n) {
		return "", "", false
	}
	rest = strings.TrimLeftFunc(rest, exportPySpace)
	if rest == "" || strings.ContainsRune(strings.TrimSuffix(rest, "\n"), '\n') {
		return "", "", false
	}
	return n, strings.TrimSuffix(rest, "\n"), true
}

// ExportTemplateArgs is _template_args: credential-carrying arguments become
// secret setup references made by ref(field, what).
func ExportTemplateArgs(args []any, mcpKey string, ref func(field, what string) string) []any {
	out := make([]any, 0, len(args))
	valueIsCredential := false
	for i, a := range args {
		arg, isStr := a.(string)
		if !isStr {
			out = append(out, a)
			valueIsCredential = false
			continue
		}
		field := mcpKey + "_arg_" + strconv.Itoa(i)
		what := "command argument " + strconv.Itoa(i+1)
		if valueIsCredential && !strings.HasPrefix(arg, "-") {
			out = append(out, ref(field, what))
			valueIsCredential = false
			continue
		}
		valueIsCredential = false
		flag, value, sep := strings.Cut(arg, "=")
		hName, hValue, header := exportHeaderArg(arg)
		switch {
		case exportIsURL(arg) && (!sep || exportIsURL(flag)):
			if ExportURLCarriesCredentials(arg) {
				out = append(out, ref(field, what))
			} else {
				out = append(out, arg)
			}
		case sep && value != "":
			if ExportIsCredentialName(flag) || ExportValueCarriesCredentials(value) {
				out = append(out, flag+"="+ref(field, what))
			} else {
				out = append(out, arg)
			}
		case header && (ExportIsCredentialName(hName) || ExportValueCarriesCredentials(hValue)):
			out = append(out, hName+": "+ref(field, what))
		default:
			valueIsCredential = strings.HasPrefix(arg, "-") && ExportIsCredentialName(arg)
			out = append(out, arg)
		}
	}
	return out
}
