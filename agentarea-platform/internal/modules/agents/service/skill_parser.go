package service

import (
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"regexp"
	"strconv"
	"strings"

	"go.yaml.in/yaml/v3"

	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/agents/domain"
)

// SkillFrontmatterError is a SKILL.md frontmatter block that cannot be read (422).
type SkillFrontmatterError struct{ Msg string }

func (e *SkillFrontmatterError) Error() string { return e.Msg }

// skillYAMLRefused is UntrustedYamlError.
type skillYAMLRefused struct{ msg string }

func (e *skillYAMLRefused) Error() string { return e.msg }

// skillYAMLSyntax is any other yaml.YAMLError: line is 0-based when known.
type skillYAMLSyntax struct {
	problem string
	line    int
}

func (e *skillYAMLSyntax) Error() string { return e.problem }

// The frontmatter budgets (skill_parser.py FRONTMATTER_MAX_*; untrusted_yaml.py depth).
const (
	skillFMMaxNodes = 2000
	skillFMMaxBytes = 64 * 1024
	skillFMMaxDepth = 64
)

var (
	skillYAMLBoundary = regexp.MustCompile(`(?m)^-{3,}\s*$`)
	skillJSONBoundary = regexp.MustCompile(`(?m)^(?:\{|\})$`)
	skillEntryRE      = regexp.MustCompile(`^([A-Za-z_][A-Za-z0-9_.-]*):(?:[ \t]+(.*))?$`)
	skillBlockScalar  = regexp.MustCompile(`^[|>][+-]?[0-9]?[+-]?\s*(#.*)?$`)
	skillYAMLLine     = regexp.MustCompile(`^yaml: line (\d+): (.*)$`)
	skillYAMLBool     = regexp.MustCompile(`^(?:yes|Yes|YES|no|No|NO|true|True|TRUE|false|False|FALSE|on|On|ON|off|Off|OFF)$`)
	skillYAMLInt      = regexp.MustCompile(`^(?:[-+]?0b[0-1_]+|[-+]?0[0-7_]+|[-+]?(?:0|[1-9][0-9_]*)|[-+]?0x[0-9a-fA-F_]+|[-+]?[1-9][0-9_]*(?::[0-5]?[0-9])+)$`)
	skillYAMLFloat    = regexp.MustCompile(`^(?:[-+]?(?:[0-9][0-9_]*)\.[0-9_]*(?:[eE][-+][0-9]+)?|\.[0-9][0-9_]*(?:[eE][-+][0-9]+)?|[-+]?[0-9][0-9_]*(?::[0-5]?[0-9])+\.[0-9_]*|[-+]?\.(?:inf|Inf|INF)|\.(?:nan|NaN|NAN))$`)
	skillYAMLNull     = regexp.MustCompile(`^(?:~|null|Null|NULL|)$`)
	skillYAMLStamp    = regexp.MustCompile(`^(?:[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]|[0-9][0-9][0-9][0-9]-[0-9][0-9]?-[0-9][0-9]?(?:[Tt]|[ \t]+)[0-9][0-9]?:[0-9][0-9]:[0-9][0-9](?:\.[0-9]*)?(?:[ \t]*(?:Z|[-+][0-9][0-9]?(?::[0-9][0-9])?))?)$`)
)

// SkillParsed is ParsedSkill: the metadata the service reads and the markdown body.
type SkillParsed struct {
	Name        string
	Description *string
	Body        string
}

// skillMeta is the frontmatter mapping: a str value, or a value of another type.
type skillMeta map[string]skillValue

type skillValue struct {
	str   string
	isStr bool
}

func (m skillMeta) str(key string) (string, bool) {
	v, ok := m[key]
	if !ok || !v.isStr {
		return "", false
	}
	return v.str, true
}

// SkillParse is SkillParser.parse_content.
func SkillParse(content string) (SkillParsed, error) {
	meta, body, err := skillFrontmatter(content)
	if err != nil {
		var fe *SkillFrontmatterError
		if errors.As(err, &fe) {
			return SkillParsed{}, err
		}
		return SkillParsed{}, &domain.SkillValueError{Msg: "Failed to parse skill content: " + err.Error()}
	}
	name, _ := meta.str("name")
	if name == "" {
		for _, line := range strings.Split(domain.SkillPyStrip(body), "\n") {
			if strings.HasPrefix(line, "# ") {
				name = domain.SkillPyStrip(line[2:])
				break
			}
		}
	}
	if name == "" {
		name = "Unnamed Skill"
	}
	out := SkillParsed{Name: name, Body: body}
	if d, ok := meta.str("description"); ok {
		out.Description = &d
	}
	return out, nil
}

func skillMatchesAtStart(re *regexp.Regexp, s string) bool {
	loc := re.FindStringIndex(s)
	return loc != nil && loc[0] == 0
}

// skillFrontmatter is parse_frontmatter over python-frontmatter's loads.
func skillFrontmatter(content string) (skillMeta, string, error) {
	text := domain.SkillPyStrip(content)
	switch {
	case skillMatchesAtStart(skillYAMLBoundary, text):
		fm, body, ok := skillSplit(skillYAMLBoundary, text)
		if !ok {
			return skillMeta{}, text, nil
		}
		root, err := skillLoadYAML(fm)
		var refused *skillYAMLRefused
		var syntax *skillYAMLSyntax
		switch {
		case errors.As(err, &refused):
			return nil, "", &SkillFrontmatterError{Msg: "SKILL.md frontmatter is refused: " + refused.msg}
		case errors.As(err, &syntax):
			lead := content[:len(content)-len(strings.TrimLeftFunc(content, skillIsPySpace))]
			first := strings.Count(lead, "\n") + strings.Count(text[:strings.Index(text, fm)], "\n") + 1
			meta, err := skillEntries(fm, first)
			return meta, domain.SkillPyStrip(body), err
		case err != nil:
			return nil, "", err
		}
		return skillMapping(root), domain.SkillPyStrip(body), nil
	case skillMatchesAtStart(skillJSONBoundary, text):
		fm, body, ok := skillSplit(skillJSONBoundary, text)
		if !ok {
			return skillMeta{}, text, nil
		}
		var v any
		if err := json.Unmarshal([]byte("{"+fm+"}"), &v); err != nil {
			return nil, "", err
		}
		meta := skillMeta{}
		if obj, isObj := v.(map[string]any); isObj {
			for k, x := range obj {
				s, isStr := x.(string)
				meta[k] = skillValue{str: s, isStr: isStr}
			}
		}
		return meta, domain.SkillPyStrip(body), nil
	}
	return skillMeta{}, text, nil
}

func skillIsPySpace(r rune) bool { return domain.SkillPyStrip(string(r)) == "" }

// skillSplit is FM_BOUNDARY.split(text, 2): the block between the first two
// boundaries and what follows, false when there are fewer than two.
func skillSplit(re *regexp.Regexp, text string) (string, string, bool) {
	locs := re.FindAllStringIndex(text, 2)
	if len(locs) < 2 {
		return "", "", false
	}
	return text[locs[0][1]:locs[1][0]], text[locs[1][1]:], true
}

// skillLoadYAML is load_untrusted_yaml: the single document, nil when empty.
func skillLoadYAML(text string) (*yaml.Node, error) {
	if len(text) > skillFMMaxBytes {
		return nil, &skillYAMLRefused{msg: fmt.Sprintf("YAML is larger than %d bytes", skillFMMaxBytes)}
	}
	dec := yaml.NewDecoder(strings.NewReader(text))
	var doc yaml.Node
	if err := dec.Decode(&doc); err != nil {
		if errors.Is(err, io.EOF) {
			return nil, nil
		}
		return nil, skillSyntax(err)
	}
	var more yaml.Node
	if err := dec.Decode(&more); err == nil {
		return nil, &skillYAMLSyntax{problem: "expected a single document in the stream", line: -1}
	} else if !errors.Is(err, io.EOF) {
		return nil, skillSyntax(err)
	}
	if len(doc.Content) == 0 {
		return nil, nil
	}
	root := doc.Content[0]
	nodes := 0
	if err := skillCompose(root, 1, &nodes); err != nil {
		return nil, err
	}
	if skillHasMerge(root) {
		return nil, &skillYAMLRefused{msg: "YAML merge keys are not accepted here"}
	}
	return root, nil
}

func skillSyntax(err error) error {
	msg := err.Error()
	if m := skillYAMLLine.FindStringSubmatch(msg); m != nil {
		n, _ := strconv.Atoi(m[1])
		return &skillYAMLSyntax{problem: m[2], line: n - 1}
	}
	return &skillYAMLSyntax{problem: strings.TrimPrefix(msg, "yaml: "), line: -1}
}

// skillCompose walks the nodes as _BoundedLoader.compose_node does.
func skillCompose(n *yaml.Node, depth int, nodes *int) error {
	if n.Kind == yaml.AliasNode {
		return &skillYAMLRefused{msg: "YAML aliases are not accepted here"}
	}
	*nodes++
	if *nodes > skillFMMaxNodes {
		return &skillYAMLRefused{msg: fmt.Sprintf("YAML holds at most %d nodes here", skillFMMaxNodes)}
	}
	if depth > skillFMMaxDepth {
		return &skillYAMLRefused{msg: fmt.Sprintf("YAML is nested deeper than %d levels", skillFMMaxDepth)}
	}
	for _, c := range n.Content {
		if err := skillCompose(c, depth+1, nodes); err != nil {
			return err
		}
	}
	return nil
}

func skillHasMerge(n *yaml.Node) bool {
	if n.Kind == yaml.MappingNode {
		for i := 0; i+1 < len(n.Content); i += 2 {
			if n.Content[i].Kind == yaml.ScalarNode && n.Content[i].ShortTag() == "!!merge" {
				return true
			}
		}
	}
	for _, c := range n.Content {
		if skillHasMerge(c) {
			return true
		}
	}
	return false
}

// skillScalar is what PyYAML's SafeLoader constructs a scalar as: a str or not.
func skillScalar(n *yaml.Node) skillValue {
	if n == nil || n.Kind != yaml.ScalarNode {
		return skillValue{}
	}
	if n.Style&yaml.TaggedStyle != 0 {
		if n.Tag == "!" || n.ShortTag() == "!!str" {
			return skillValue{str: n.Value, isStr: true}
		}
		return skillValue{}
	}
	if n.Style&(yaml.SingleQuotedStyle|yaml.DoubleQuotedStyle|yaml.LiteralStyle|yaml.FoldedStyle) != 0 {
		return skillValue{str: n.Value, isStr: true}
	}
	v := n.Value
	for _, re := range []*regexp.Regexp{skillYAMLBool, skillYAMLInt, skillYAMLFloat, skillYAMLNull, skillYAMLStamp} {
		if re.MatchString(v) {
			return skillValue{}
		}
	}
	if v == "<<" || v == "=" {
		return skillValue{}
	}
	return skillValue{str: v, isStr: true}
}

// skillMapping is the top-level dict; anything else is {}. A later key wins.
func skillMapping(n *yaml.Node) skillMeta {
	meta := skillMeta{}
	if n == nil || n.Kind != yaml.MappingNode {
		return meta
	}
	for i := 0; i+1 < len(n.Content); i += 2 {
		k := skillScalar(n.Content[i])
		if !k.isStr {
			continue
		}
		meta[k.str] = skillScalar(n.Content[i+1])
	}
	return meta
}

// skillEntries is _parse_frontmatter_entries: the lenient per-entry read.
func skillEntries(block string, firstLine int) (skillMeta, error) {
	lines := strings.Split(block, "\n")
	meta := skillMeta{}
	for i := 0; i < len(lines); {
		line := lines[i]
		if domain.SkillPyStrip(line) == "" || strings.HasPrefix(strings.TrimLeftFunc(line, skillIsPySpace), "#") {
			i++
			continue
		}
		m := skillEntryRE.FindStringSubmatch(strings.TrimRightFunc(line, skillIsPySpace))
		if m == nil {
			return nil, &SkillFrontmatterError{Msg: fmt.Sprintf("SKILL.md frontmatter line %d is not a 'key: value' entry: %s",
				firstLine+i, domain.SkillRepr(domain.SkillPyStrip(line)))}
		}
		end := i + 1
		for end < len(lines) && (domain.SkillPyStrip(lines[end]) == "" || lines[end][0] == ' ' || lines[end][0] == '\t' || strings.HasPrefix(lines[end], "-")) {
			end++
		}
		for end > i+1 && domain.SkillPyStrip(lines[end-1]) == "" {
			end--
		}
		v, err := skillEntry(m[1], m[2], lines[i:end], firstLine+i)
		if err != nil {
			return nil, err
		}
		meta[m[1]] = v
		i = end
	}
	return meta, nil
}

func skillEntry(key, value string, entry []string, lineNumber int) (skillValue, error) {
	root, err := skillLoadYAML(strings.Join(entry, "\n"))
	var refused *skillYAMLRefused
	var syntax *skillYAMLSyntax
	switch {
	case errors.As(err, &refused):
		return skillValue{}, &SkillFrontmatterError{Msg: fmt.Sprintf("SKILL.md frontmatter line %d ('%s') is refused: %s", lineNumber, key, refused.msg)}
	case errors.As(err, &syntax):
		plain := value != "" && !strings.ContainsAny(value[:1], `'"[{`) && !skillBlockScalar.MatchString(value)
		for _, l := range entry[1:] {
			if domain.SkillPyStrip(l) != "" && l[0] != ' ' && l[0] != '\t' {
				plain = false
			}
		}
		if plain {
			parts := []string{domain.SkillPyStrip(value)}
			for _, l := range entry[1:] {
				if s := domain.SkillPyStrip(l); s != "" {
					parts = append(parts, s)
				}
			}
			return skillValue{str: strings.Join(parts, " "), isStr: true}, nil
		}
		offset := 0
		if syntax.line >= 0 {
			offset = min(syntax.line, len(entry)-1)
		}
		return skillValue{}, &SkillFrontmatterError{Msg: fmt.Sprintf("SKILL.md frontmatter line %d ('%s') is not valid YAML: %s: %s",
			lineNumber+offset, key, syntax.problem, domain.SkillRepr(domain.SkillPyStrip(entry[offset])))}
	case err != nil:
		return skillValue{}, err
	}
	if root == nil || root.Kind != yaml.MappingNode || len(root.Content) != 2 {
		return skillValue{}, errors.New("not enough values to unpack (expected 1, got 0)")
	}
	return skillScalar(root.Content[1]), nil
}
