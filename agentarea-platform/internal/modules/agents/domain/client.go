package domain

import (
	"fmt"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"unicode"
	"unicode/utf8"
)

// ClientPlatformToolset is a platform toolset a client can carry.
type ClientPlatformToolset struct {
	Namespace   string
	Name        string
	DisplayName string
	Description string
	Methods     []ClientPlatformToolsetMethod
}

// ClientPlatformToolsetMethod is one tool method of a platform toolset.
type ClientPlatformToolsetMethod struct {
	Name        string
	DisplayName string
	Description string
	Effect      string
}

// ClientToolsetError is UnknownToolsetError.
type ClientToolsetError struct{ Msg string }

func (e *ClientToolsetError) Error() string { return e.Msg }

// ClientAttachableToolset is platform_mcp.attachable_toolset: the namespace of
// the toolset ref names (by name or namespace), refusing methods it lacks.
func ClientAttachableToolset(ref string, disabled []string) (string, error) {
	all := ClientPlatformToolsets()
	var found *ClientPlatformToolset
	for i := range all {
		if all[i].Name == ref {
			found = &all[i]
			break
		}
	}
	if found == nil {
		for i := range all {
			if all[i].Namespace == ref {
				found = &all[i]
				break
			}
		}
	}
	if found == nil {
		names := make([]string, len(all))
		for i, t := range all {
			names[i] = t.Name
		}
		return "", &ClientToolsetError{Msg: fmt.Sprintf("Unknown toolset '%s'. Available: %s", ref, strings.Join(names, ", "))}
	}
	has := map[string]bool{}
	for _, m := range found.Methods {
		has[m.Name] = true
	}
	unknown := map[string]bool{}
	for _, d := range disabled {
		if !has[d] {
			unknown[d] = true
		}
	}
	if len(unknown) > 0 {
		names := make([]string, 0, len(unknown))
		for n := range unknown {
			names = append(names, n)
		}
		sort.Strings(names)
		return "", &ClientToolsetError{Msg: fmt.Sprintf("Toolset '%s' has no method(s) %s", found.Namespace, strings.Join(names, ", "))}
	}
	return found.Namespace, nil
}

// clientHost is client_dto._HOST: re.IGNORECASE, \d any decimal digit, $ before a final newline.
var clientHost = regexp.MustCompile(`(?i)^(\*\.)?[a-z\p{Nd}]([a-z\p{Nd}-]*[a-z\p{Nd}])?(\.[a-z\p{Nd}]([a-z\p{Nd}-]*[a-z\p{Nd}])?)*\n?\z`)

// ClientCheckDomains is ClientUpdate._check_domains: "" when every entry is a host name.
func ClientCheckDomains(domains []string) string {
	for _, d := range domains {
		if utf8.RuneCountInString(d) > 253 || !clientHost.MatchString(d) {
			return "not a host name: " + ClientPyRepr(d)
		}
	}
	return ""
}

// ClientPyRepr is repr() of a str.
func ClientPyRepr(s string) string {
	quote := '\''
	if strings.ContainsRune(s, '\'') && !strings.ContainsRune(s, '"') {
		quote = '"'
	}
	var b strings.Builder
	b.WriteRune(quote)
	for _, r := range s {
		switch {
		case r == quote || r == '\\':
			b.WriteRune('\\')
			b.WriteRune(r)
		case r == '\n':
			b.WriteString(`\n`)
		case r == '\r':
			b.WriteString(`\r`)
		case r == '\t':
			b.WriteString(`\t`)
		case r < 0x20 || r == 0x7f:
			b.WriteString(`\x` + pad(strconv.FormatInt(int64(r), 16), 2))
		case !unicode.IsPrint(r) && r != ' ':
			switch {
			case r <= 0xff:
				b.WriteString(`\x` + pad(strconv.FormatInt(int64(r), 16), 2))
			case r <= 0xffff:
				b.WriteString(`\u` + pad(strconv.FormatInt(int64(r), 16), 4))
			default:
				b.WriteString(`\U` + pad(strconv.FormatInt(int64(r), 16), 8))
			}
		default:
			b.WriteRune(r)
		}
	}
	b.WriteRune(quote)
	return b.String()
}

func pad(s string, n int) string {
	for len(s) < n {
		s = "0" + s
	}
	return s
}
