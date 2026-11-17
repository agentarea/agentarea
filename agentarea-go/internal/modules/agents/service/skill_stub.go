package service

import (
	"path"
	"regexp"
	"slices"
	"strings"
	"unicode"
	"unicode/utf8"

	"github.com/agentarea/agentarea/agentarea-go/internal/modules/agents/domain"
)

// skillStubMarker is STUB_MARKER: the line an old index's stub SKILL.md carries (ADR-0044).
const skillStubMarker = "Imported system skill metadata. The original SKILL.md should be reviewed before execution."

var (
	stubRepoName = regexp.MustCompile(`^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$`)
	stubWord     = regexp.MustCompile(`^\S+$`)
)

// stubField is one of the lines a stub names the original with.
func stubField(key string) bool { return key == "Source" || key == "Repository" || key == "Path" }

// stubOneWord is a one-word line a stub may end with.
func stubOneWord(key string) bool { return key == "License" || key == "Distribution" }

// skillStub is StubSource: where a stub says the original SKILL.md is.
type skillStub struct{ sourceURL, repo, path string }

// folder is the folder that holds the original.
func (s skillStub) folder() string {
	p := strings.Trim(s.path, "/")
	if strings.ToLower(path.Base(p)) != "skill.md" {
		return p
	}
	if d := path.Dir(p); d != "." {
		return d
	}
	return ""
}

// stubLines is str.splitlines() with each line stripped.
func stubLines(s string) []string {
	var out []string
	start := 0
	for i := 0; i < len(s); {
		r, size := utf8.DecodeRuneInString(s[i:])
		switch r {
		case '\n', '\r', '\v', '\f', 0x1c, 0x1d, 0x1e, 0x85, 0x2028, 0x2029:
			out = append(out, s[start:i])
			i += size
			if r == '\r' && i < len(s) && s[i] == '\n' {
				i++
			}
			start = i
			continue
		}
		i += size
	}
	if start < len(s) {
		out = append(out, s[start:])
	}
	return out
}

func stripped(lines []string) []string {
	out := make([]string, len(lines))
	for i, l := range lines {
		out[i] = domain.SkillPyStrip(l)
	}
	return out
}

// stubWords is _words: the words joined by one space; false when v is no string.
func stubWords(v any) (string, bool) {
	s, ok := v.(string)
	if !ok {
		return "", false
	}
	return strings.Join(strings.FieldsFunc(s, func(r rune) bool { return unicode.IsSpace(r) || (r >= 0x1c && r <= 0x1f) }), " "), true
}

// parseStub is parse_stub: the original a stub points at, when text carries the
// marker line followed by its Source, Repository and Path lines.
func parseStub(text string) (skillStub, bool) {
	lines := stripped(stubLines(text))
	at := slices.Index(lines, skillStubMarker)
	if at < 0 {
		return skillStub{}, false
	}
	fields := map[string]string{}
	for _, line := range lines[at+1:] {
		key, value, sep := strings.Cut(line, ": ")
		if _, seen := fields[key]; sep && stubField(key) && !seen {
			fields[key] = domain.SkillPyStrip(value)
		}
	}
	for _, k := range []string{"Source", "Repository", "Path"} {
		if fields[k] == "" {
			return skillStub{}, false
		}
	}
	return skillStub{sourceURL: fields["Source"], repo: fields["Repository"], path: fields["Path"]}, true
}

// bareStub is bare_stub: what parseStub finds, when text is exactly the stub
// an index wrote for the skill name with description.
func bareStub(text, name string, description *string) (skillStub, bool) {
	stub, ok := parseStub(text)
	if !ok || description == nil {
		return skillStub{}, false
	}
	raw := stubLines(text)
	lines := stripped(raw)
	if len(lines) == 0 || lines[0] != "---" || !slices.Contains(lines[1:], "---") {
		return skillStub{}, false
	}
	closing := slices.Index(lines[1:], "---") + 1
	doc, err := skillLoadYAML(strings.Join(raw[1:closing], "\n"))
	if err != nil || doc == nil {
		return skillStub{}, false
	}
	var meta map[string]any
	if err := doc.Decode(&meta); err != nil || len(meta) != 2 {
		return skillStub{}, false
	}
	want, _ := stubWords(*description)
	if n, ok := meta["name"].(string); !ok || n != name {
		return skillStub{}, false
	}
	if got, ok := stubWords(meta["description"]); !ok || got != want {
		return skillStub{}, false
	}
	marker := slices.Index(lines, skillStubMarker)
	if got, _ := stubWords(strings.Join(lines[min(closing+1, marker):marker], " ")); closing > marker || got != want {
		return skillStub{}, false
	}
	seen := map[string]bool{}
	for _, line := range lines[marker+1:] {
		if line == "" {
			continue
		}
		key, value, sep := strings.Cut(line, ": ")
		if !sep || seen[key] || (!stubField(key) && !stubOneWord(key)) {
			return skillStub{}, false
		}
		if stubOneWord(key) && !stubWord.MatchString(value) {
			return skillStub{}, false
		}
		seen[key] = true
	}
	if !stubRepoName.MatchString(stub.repo) ||
		!regexp.MustCompile(`^https://github\.com/`+regexp.QuoteMeta(stub.repo)+`(/\S*)?$`).MatchString(stub.sourceURL) {
		return skillStub{}, false
	}
	if strings.HasPrefix(stub.path, "/") || slices.Contains(strings.Split(stub.path, "/"), "..") || strings.Contains(stub.path, " ") {
		return skillStub{}, false
	}
	return stub, true
}
