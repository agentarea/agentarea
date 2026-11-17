package openapispec

import (
	"regexp"
	"sort"
	"strings"
)

// MaxSpecBytes is _SPEC_MAX_SIZE: the largest spec fetched or accepted.
const MaxSpecBytes = 5 * 1024 * 1024

// VariableName is URL_VARIABLE_NAME_RE.
var VariableName = regexp.MustCompile(`^[A-Za-z_][A-Za-z0-9_]*$`)

var placeholder = regexp.MustCompile(`\{([^{}]*)\}`)

// urlParts is urllib.parse.urlparse's split.
type urlParts struct {
	scheme, netloc, path, params, query, fragment string
}

func isSchemeChar(c byte, first bool) bool {
	switch {
	case c >= 'a' && c <= 'z', c >= 'A' && c <= 'Z':
		return true
	case first:
		return false
	case c >= '0' && c <= '9', c == '+', c == '-', c == '.':
		return true
	}
	return false
}

func splitURL(u string) urlParts {
	var p urlParts
	if i := strings.IndexByte(u, ':'); i > 0 {
		valid := true
		for j := 0; j < i; j++ {
			if !isSchemeChar(u[j], j == 0) {
				valid = false
				break
			}
		}
		if valid {
			p.scheme, u = strings.ToLower(u[:i]), u[i+1:]
		}
	}
	if strings.HasPrefix(u, "//") {
		rest := u[2:]
		end := len(rest)
		if i := strings.IndexAny(rest, "/?#"); i >= 0 {
			end = i
		}
		p.netloc, u = rest[:end], rest[end:]
	}
	if i := strings.IndexByte(u, '#'); i >= 0 {
		p.fragment, u = u[i+1:], u[:i]
	}
	if i := strings.IndexByte(u, '?'); i >= 0 {
		p.query, u = u[i+1:], u[:i]
	}
	if i := strings.LastIndexByte(u, '/'); strings.Contains(u[i+1:], ";") {
		j := i + 1 + strings.IndexByte(u[i+1:], ';')
		p.params, u = u[j+1:], u[:j]
	}
	p.path = u
	return p
}

// Origin is scheme://netloc of u, as resolve_headers compares it.
func Origin(u string) string {
	p := splitURL(u)
	return p.scheme + "://" + p.netloc
}

// TemplateVariables is url_template_variables: the {name} placeholders of
// a base URL, allowed only in its path.
func TemplateVariables(u string) (map[string]bool, error) {
	p := splitURL(u)
	outside := p.scheme + p.netloc + p.params + p.query + p.fragment
	if strings.ContainsAny(outside, "{}") {
		return nil, errorf("URL variables are only allowed in the base URL path; the scheme, host, port and query must be literal.")
	}
	names := map[string]bool{}
	var ordered []string
	for _, m := range placeholder.FindAllStringSubmatch(p.path, -1) {
		if !names[m[1]] {
			ordered = append(ordered, m[1])
		}
		names[m[1]] = true
	}
	for _, n := range ordered {
		if !VariableName.MatchString(n) {
			return nil, errorf("Invalid URL variable name '%s'.", n)
		}
	}
	if strings.ContainsAny(placeholder.ReplaceAllString(p.path, ""), "{}") {
		return nil, errorf("Base URL path has an unmatched '{' or '}'.")
	}
	return names, nil
}

// CheckURLVariables is check_url_variables: every placeholder has a
// variable and every variable a placeholder.
func CheckURLVariables(u string, names []string) error {
	placeholders, err := TemplateVariables(u)
	if err != nil {
		return err
	}
	set := map[string]bool{}
	for _, n := range names {
		set[n] = true
	}
	if len(set) != len(names) {
		return errorf("URL variable names must be unique.")
	}
	var missing, unused []string
	for n := range placeholders {
		if !set[n] {
			missing = append(missing, n)
		}
	}
	for n := range set {
		if !placeholders[n] {
			unused = append(unused, n)
		}
	}
	sort.Strings(missing)
	sort.Strings(unused)
	if len(missing) > 0 {
		return errorf("Base URL placeholders have no URL variable: %s.", strings.Join(missing, ", "))
	}
	if len(unused) > 0 {
		return errorf("URL variable is not used in the base URL: %s.", strings.Join(unused, ", "))
	}
	return nil
}
