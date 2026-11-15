package netguard

import (
	"fmt"
	"regexp"
	"strings"
)

// compileGlob is fnmatch.translate: "*" any run (dots and slashes too),
// "?" one character, "[seq]" and "[!seq]" a set with ranges; a "[" with
// no closing "]" is literal. The match is whole and case-sensitive, as
// fnmatch.fnmatch on POSIX; callers lowercase both sides.
func compileGlob(pattern string) *regexp.Regexp {
	var b strings.Builder
	b.WriteString(`(?s)^`)
	p := []rune(pattern)
	for i := 0; i < len(p); i++ {
		c := p[i]
		switch c {
		case '*':
			for i+1 < len(p) && p[i+1] == '*' {
				i++
			}
			b.WriteString(`.*`)
		case '?':
			b.WriteString(`.`)
		case '[':
			j := i + 1
			if j < len(p) && p[j] == '!' {
				j++
			}
			if j < len(p) && p[j] == ']' {
				j++
			}
			for j < len(p) && p[j] != ']' {
				j++
			}
			if j >= len(p) {
				b.WriteString(`\[`)
				continue
			}
			b.WriteString(globSet(p[i+1 : j]))
			i = j
		default:
			b.WriteString(regexp.QuoteMeta(string(c)))
		}
	}
	b.WriteString(`$`)
	return regexp.MustCompile(b.String())
}

func globSet(set []rune) string {
	negate := len(set) > 0 && set[0] == '!'
	if negate {
		set = set[1:]
	}
	var items []string
	for k := 0; k < len(set); k++ {
		lo := set[k]
		if k+2 < len(set) && set[k+1] == '-' {
			hi := set[k+2]
			k += 2
			if lo > hi {
				continue
			}
			items = append(items, fmt.Sprintf(`\x{%x}-\x{%x}`, lo, hi))
			continue
		}
		items = append(items, fmt.Sprintf(`\x{%x}`, lo))
	}
	if len(items) == 0 {
		if negate {
			return `.`
		}
		return `[^\x00-\x{10ffff}]`
	}
	if negate {
		return `[^` + strings.Join(items, "") + `]`
	}
	return `[` + strings.Join(items, "") + `]`
}

// Fnmatch is fnmatch.fnmatch(name, pattern) on POSIX.
func Fnmatch(name, pattern string) bool { return compileGlob(pattern).MatchString(name) }
