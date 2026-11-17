package service

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"math"
	"regexp"
	"sort"
	"strconv"
	"strings"

	"go.yaml.in/yaml/v3"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx/wirejson"
)

// BundleParseError is source text or a folder that is not a valid bundle.
type BundleParseError struct{ Msg string }

func (e *BundleParseError) Error() string { return e.Msg }

const (
	// BundleMaxBytes caps a bundle's source text and an agent folder.
	BundleMaxBytes  = 5 * 1024 * 1024
	bundleMaxNodes  = 200_000
	yamlMaxDepth    = 64
	folderYAMLBytes = 1024 * 1024
	// RootAgentKey is the key of the agent an agent folder declares.
	RootAgentKey = "agent"
)

var (
	frontmatterRe = regexp.MustCompile(`(?s)\A---\r?\n(?:---|(.*?)\r?\n---)\r?\n?(.*)\z`)
	driveLetterRe = regexp.MustCompile(`^[A-Za-z]:`)
)

// untrustedYAMLError is UntrustedYamlError and the YAML errors under it.
type untrustedYAMLError struct{ msg string }

func (e *untrustedYAMLError) Error() string { return e.msg }

// loadUntrustedYAML is load_untrusted_yaml: one document, no aliases or merge
// keys, at most maxNodes nodes and yamlMaxDepth levels; mappings keep their order.
func loadUntrustedYAML(text string, maxNodes, maxBytes int) (any, error) {
	if len(text) > maxBytes {
		return nil, &untrustedYAMLError{fmt.Sprintf("YAML is larger than %d bytes", maxBytes)}
	}
	dec := yaml.NewDecoder(bytes.NewReader([]byte(text)))
	var doc yaml.Node
	if err := dec.Decode(&doc); err != nil {
		if errors.Is(err, io.EOF) {
			return nil, nil
		}
		return nil, &untrustedYAMLError{err.Error()}
	}
	var more yaml.Node
	if err := dec.Decode(&more); !errors.Is(err, io.EOF) {
		return nil, &untrustedYAMLError{"expected a single document in the stream"}
	}
	if len(doc.Content) == 0 {
		return nil, nil
	}
	l := yamlLoad{max: maxNodes}
	return l.value(doc.Content[0], 1)
}

type yamlLoad struct{ nodes, max int }

func (l *yamlLoad) value(n *yaml.Node, depth int) (any, error) {
	if n.Kind == yaml.AliasNode {
		return nil, &untrustedYAMLError{"YAML aliases are not accepted here"}
	}
	l.nodes++
	if l.nodes > l.max {
		return nil, &untrustedYAMLError{fmt.Sprintf("YAML holds at most %d nodes here", l.max)}
	}
	if depth > yamlMaxDepth {
		return nil, &untrustedYAMLError{fmt.Sprintf("YAML is nested deeper than %d levels", yamlMaxDepth)}
	}
	switch n.Kind {
	case yaml.SequenceNode:
		out := make([]any, 0, len(n.Content))
		for _, c := range n.Content {
			v, err := l.value(c, depth+1)
			if err != nil {
				return nil, err
			}
			out = append(out, v)
		}
		return out, nil
	case yaml.MappingNode:
		for i := 0; i+1 < len(n.Content); i += 2 {
			if n.Content[i].ShortTag() == "!!merge" {
				return nil, &untrustedYAMLError{"YAML merge keys are not accepted here"}
			}
		}
		out := wirejson.Object{}
		for i := 0; i+1 < len(n.Content); i += 2 {
			k, err := l.value(n.Content[i], depth+1)
			if err != nil {
				return nil, err
			}
			v, err := l.value(n.Content[i+1], depth+1)
			if err != nil {
				return nil, err
			}
			out.Set(pyStr(k), v)
		}
		return out, nil
	case yaml.ScalarNode:
		return yamlScalarValue(n)
	case yaml.AliasNode:
		return nil, &untrustedYAMLError{"YAML aliases are not accepted here"}
	case yaml.DocumentNode:
	}
	return nil, &untrustedYAMLError{fmt.Sprintf("unknown YAML node kind %d", n.Kind)}
}

func yamlScalarValue(n *yaml.Node) (any, error) {
	switch n.ShortTag() {
	case "!!null":
		return nil, nil
	case "!!bool":
		var b bool
		if err := n.Decode(&b); err != nil {
			return nil, &untrustedYAMLError{err.Error()}
		}
		return b, nil
	case "!!int":
		var i int64
		if err := n.Decode(&i); err != nil {
			return nil, &untrustedYAMLError{err.Error()}
		}
		return jsonInt(i), nil
	case "!!float":
		var f float64
		if err := n.Decode(&f); err != nil {
			return nil, &untrustedYAMLError{err.Error()}
		}
		if math.IsInf(f, 0) || math.IsNaN(f) {
			return n.Value, nil
		}
		return wirejson.Float(f), nil
	}
	return n.Value, nil
}

func jsonInt(i int64) any { return json.Number(strconv.FormatInt(i, 10)) }

// validationText is str(ValidationError) without the input values.
func validationText(model string, errs []httpx.FieldError) string {
	noun := "error"
	if len(errs) != 1 {
		noun = "errors"
	}
	var b strings.Builder
	fmt.Fprintf(&b, "%d validation %s for %s", len(errs), noun, model)
	for _, e := range errs {
		if len(e.Loc) > 0 {
			parts := make([]string, len(e.Loc))
			for i, p := range e.Loc {
				parts[i] = fmt.Sprint(p)
			}
			fmt.Fprintf(&b, "\n%s", strings.Join(parts, "."))
		}
		fmt.Fprintf(&b, "\n  %s [type=%s]", e.Msg, e.Type)
	}
	return b.String()
}

// ParseBundle is parse_bundle: YAML or JSON source text into a bundle.
func ParseBundle(text string) (Bundle, error) {
	if pyStrip(text) == "" {
		return Bundle{}, &BundleParseError{"empty package source"}
	}
	data, err := loadUntrustedYAML(text, bundleMaxNodes, BundleMaxBytes)
	if err != nil {
		return Bundle{}, &BundleParseError{"invalid YAML/JSON: " + err.Error()}
	}
	if _, ok := data.(wirejson.Object); !ok {
		return Bundle{}, &BundleParseError{"package must be a mapping at the top level"}
	}
	var c checker
	b, ok := bundleFrom(&c, data, nil)
	if !ok {
		return Bundle{}, &BundleParseError{validationText("Bundle", c.errs)}
	}
	return b, nil
}

// CheckFolderPath is check_folder_path: a relative POSIX path without
// empty, '.' or '..' segments.
func CheckFolderPath(path string) error {
	if path == "" || strings.HasPrefix(path, "/") || strings.Contains(path, "\\") || driveLetterRe.MatchString(path) {
		return &BundleParseError{fmt.Sprintf("invalid path '%s': must be a relative POSIX path", path)}
	}
	for _, part := range strings.Split(path, "/") {
		if part == "" || part == "." || part == ".." {
			return &BundleParseError{fmt.Sprintf("invalid path '%s': empty, '.' or '..' segment", path)}
		}
	}
	return nil
}

// FolderSize is the bytes of an agent folder's paths and texts.
func FolderSize(files StrPairs) int {
	n := 0
	for _, f := range files {
		n += len(f.Key) + len(f.Value)
	}
	return n
}

func yamlMapping(path, text string) (wirejson.Object, error) {
	data, err := loadUntrustedYAML(text, bundleMaxNodes, folderYAMLBytes)
	if err != nil {
		return nil, &BundleParseError{path + ": " + err.Error()}
	}
	if data == nil {
		return wirejson.Object{}, nil
	}
	o, ok := data.(wirejson.Object)
	if !ok {
		return nil, &BundleParseError{path + ": must be a mapping at the top level"}
	}
	return o, nil
}

func folderFrontmatter(path, text string) (wirejson.Object, string, error) {
	m := frontmatterRe.FindStringSubmatch(text)
	if m == nil {
		return wirejson.Object{}, text, nil
	}
	meta, err := yamlMapping(path, m[1])
	return meta, m[2], err
}

func yamlStem(name string) (string, bool) {
	for _, suffix := range []string{".yaml", ".yml"} {
		if strings.HasSuffix(name, suffix) {
			return strings.TrimSuffix(name, suffix), true
		}
	}
	return "", false
}

func built[T any](path, model string, data wirejson.Object, from func(*checker, any, []any) (T, bool)) (T, error) {
	var c checker
	v, ok := from(&c, data, nil)
	if !ok {
		var zero T
		return zero, &BundleParseError{path + ": " + validationText(model, c.errs)}
	}
	return v, nil
}

func objectWith(base wirejson.Object, spec wirejson.Object, after ...wirejson.Member) wirejson.Object {
	out := append(wirejson.Object{}, base...)
	for _, m := range spec {
		out.Set(m.Key, m.Value)
	}
	for _, m := range after {
		out.Set(m.Key, m.Value)
	}
	return out
}

// LoadBundleFolder is load_folder: one bundle from an agent folder; entries
// outside the layout come back as WARN issues.
func LoadBundleFolder(files StrPairs) (Bundle, []PreviewIssue, error) {
	for _, f := range files {
		if err := CheckFolderPath(f.Key); err != nil {
			return Bundle{}, nil, err
		}
	}
	agentYAML, ok := files.Get("agent.yaml")
	if !ok {
		return Bundle{}, nil, &BundleParseError{"agent.yaml: missing; the folder root must hold agent.yaml"}
	}
	var issues []PreviewIssue
	warn := func(msg string) { issues = append(issues, PreviewIssue{Severity: SeverityWarn, Message: msg}) }
	reserved := func(path string, data wirejson.Object, names ...string) {
		for _, n := range names {
			if _, ok := data.Get(n); ok {
				warn(fmt.Sprintf("%s: '%s' is set by the folder layout; the value is ignored", path, n))
			}
		}
	}
	sorted := append(StrPairs{}, files...)
	sort.SliceStable(sorted, func(i, j int) bool { return sorted[i].Key < sorted[j].Key })
	skillFiles := map[string]StrPairs{}
	var skillKeys []string
	b := Bundle{SchemaVersion: BundleSchemaVersion, Metadata: BundleMetadata{Capabilities: []string{}},
		MCPs: []BundleMCP{}, Channels: []BundleChannel{}, Automations: []BundleAutomation{}, Policies: []BundlePolicy{}}
	for _, f := range sorted {
		path, text := f.Key, f.Value
		parts := strings.Split(path, "/")
		top := parts[0]
		if path == "agent.yaml" || path == "instructions.md" {
			continue
		}
		key, isYAML := "", false
		if len(parts) == 2 {
			key, isYAML = yamlStem(parts[1])
		}
		switch {
		case top == "skills" && len(parts) >= 3:
			if _, ok := skillFiles[parts[1]]; !ok {
				skillKeys = append(skillKeys, parts[1])
			}
			skillFiles[parts[1]] = append(skillFiles[parts[1]], StrPair{Key: strings.Join(parts[2:], "/"), Value: path})
		case top == "mcp" && isYAML:
			spec, err := yamlMapping(path, text)
			if err != nil {
				return Bundle{}, nil, err
			}
			reserved(path, spec, "key")
			m, err := built(path, "BundleMcp", objectWith(wirejson.Object{{Key: "name", Value: key}}, spec, wirejson.Member{Key: "key", Value: key}), bundleMCPFrom)
			if err != nil {
				return Bundle{}, nil, err
			}
			b.MCPs = append(b.MCPs, m)
		case top == "schedules" && len(parts) == 2 && strings.HasSuffix(parts[1], ".md"):
			meta, body, err := folderFrontmatter(path, text)
			if err != nil {
				return Bundle{}, nil, err
			}
			reserved(path, meta, "key", "agent", "prompt")
			data := objectWith(nil, meta, wirejson.Member{Key: "key", Value: strings.TrimSuffix(parts[1], ".md")},
				wirejson.Member{Key: "agent", Value: RootAgentKey}, wirejson.Member{Key: "prompt", Value: pyStrip(body)})
			a, err := built(path, "BundleAutomation", data, bundleAutomationFrom)
			if err != nil {
				return Bundle{}, nil, err
			}
			b.Automations = append(b.Automations, a)
		case top == "channels" && isYAML:
			spec, err := yamlMapping(path, text)
			if err != nil {
				return Bundle{}, nil, err
			}
			reserved(path, spec, "key", "agent")
			data := objectWith(wirejson.Object{{Key: "name", Value: key}}, spec, wirejson.Member{Key: "key", Value: key},
				wirejson.Member{Key: "agent", Value: RootAgentKey})
			ch, err := built(path, "BundleChannel", data, bundleChannelFrom)
			if err != nil {
				return Bundle{}, nil, err
			}
			b.Channels = append(b.Channels, ch)
		case top == "policies" && isYAML:
			spec, err := yamlMapping(path, text)
			if err != nil {
				return Bundle{}, nil, err
			}
			reserved(path, spec, "key")
			p, err := built(path, "BundlePolicy", objectWith(wirejson.Object{{Key: "subject", Value: RootAgentKey}}, spec,
				wirejson.Member{Key: "key", Value: key}), bundlePolicyFrom)
			if err != nil {
				return Bundle{}, nil, err
			}
			b.Policies = append(b.Policies, p)
		default:
			warn(path + ": not part of the agent folder layout; not installed")
		}
	}
	sort.Strings(skillKeys)
	b.Skills = []BundleSkill{}
	for _, key := range skillKeys {
		entries := skillFiles[key]
		skillPath := "skills/" + key + "/SKILL.md"
		if _, ok := entries.Get("SKILL.md"); !ok {
			return Bundle{}, nil, &BundleParseError{skillPath + ": missing; every skill directory needs one"}
		}
		content, _ := files.Get(skillPath)
		meta, _, err := folderFrontmatter(skillPath, content)
		if err != nil {
			return Bundle{}, nil, err
		}
		name := key
		if n, ok := meta.Get("name"); ok {
			if s, ok := n.(string); ok && s != "" {
				name = s
			}
		}
		data := wirejson.Object{{Key: "key", Value: key}, {Key: "name", Value: name}}
		if len(entries) == 1 {
			data = append(data, wirejson.Member{Key: "source_type", Value: "content"}, wirejson.Member{Key: "content", Value: content})
		} else {
			sort.SliceStable(entries, func(i, j int) bool { return entries[i].Key < entries[j].Key })
			pkg := wirejson.Object{}
			for _, e := range entries {
				text, _ := files.Get(e.Value)
				pkg.Set(e.Key, text)
			}
			data = append(data, wirejson.Member{Key: "source_type", Value: "files"}, wirejson.Member{Key: "files", Value: pkg})
		}
		s, err := built(skillPath, "BundleSkill", data, bundleSkillFrom)
		if err != nil {
			return Bundle{}, nil, err
		}
		b.Skills = append(b.Skills, s)
	}

	spec, err := yamlMapping("agent.yaml", agentYAML)
	if err != nil {
		return Bundle{}, nil, err
	}
	af, err := built("agent.yaml", "_AgentFile", spec, agentFileFrom)
	if err != nil {
		return Bundle{}, nil, err
	}
	instruction, _ := files.Get("instructions.md")
	mcpKeys := make([]any, len(b.MCPs))
	for i, m := range b.MCPs {
		mcpKeys[i] = m.Key
	}
	skillKeyList := make([]any, len(b.Skills))
	for i, s := range b.Skills {
		skillKeyList[i] = s.Key
	}
	agentData := wirejson.Object{{Key: "key", Value: RootAgentKey}, {Key: "name", Value: af.name}, {Key: "description", Value: af.description},
		{Key: "instruction", Value: instruction}, {Key: "model", Value: optStrValue(af.model)}, {Key: "toolsets", Value: strList(af.toolsets)},
		{Key: "reasoning_effort", Value: af.reasoningEffort}, {Key: "reasoning_max_tokens", Value: af.reasoningMaxTokens},
		{Key: "client", Value: optStrValue(af.client)}, {Key: "mcps", Value: mcpKeys}, {Key: "skills", Value: skillKeyList}}
	var c checker
	agent, ok := bundleAgentFrom(&c, agentData, nil)
	if !ok {
		onlyInstruction := true
		for _, e := range c.errs {
			if len(e.Loc) == 0 || e.Loc[0] != "instruction" {
				onlyInstruction = false
			}
		}
		path := "agent.yaml"
		if onlyInstruction {
			path = "instructions.md"
		}
		return Bundle{}, nil, &BundleParseError{path + ": " + validationText("BundleAgent", c.errs)}
	}
	b.Agents = []BundleAgent{agent}
	b.Name, b.DisplayName, b.Description, b.Setup = af.name, af.displayName, af.description, af.setup
	var bc checker
	bc.str(b.Name, 1, BundleMaxNameLength, []any{"name"})
	if b.DisplayName != nil {
		bc.str(*b.DisplayName, 0, BundleMaxNameLength, []any{"display_name"})
	}
	if len(bc.errs) > 0 {
		return Bundle{}, nil, &BundleParseError{"agent.yaml: " + validationText("Bundle", bc.errs)}
	}
	return b, issues, nil
}

// agentFile is _AgentFile: what agent.yaml declares.
type agentFile struct {
	name, description                   string
	displayName, model, client          *string
	toolsets                            []string
	reasoningEffort, reasoningMaxTokens any
	setup                               []SetupField
}

func agentFileFrom(c *checker, v any, loc []any) (agentFile, bool) {
	o, ok := c.model(v, "_AgentFile", loc)
	if !ok {
		return agentFile{}, false
	}
	f := fields{o, loc}
	before := c.count()
	out := agentFile{name: c.requiredStr(f, "name", 1, 0), toolsets: []string{}}
	if v, ok := f.get("display_name"); ok {
		out.displayName, _ = c.optStr(v, 0, f.at("display_name"))
	}
	if v, ok := f.get("description"); ok {
		out.description, _ = c.str(v, 0, 0, f.at("description"))
	}
	if v, ok := f.get("model"); ok {
		out.model, _ = c.optStr(v, 0, f.at("model"))
	}
	if v, ok := f.get("toolsets"); ok {
		if l, ok := c.strList(v, f.at("toolsets")); ok {
			out.toolsets = l
		}
	}
	out.reasoningEffort, _ = f.get("reasoning_effort")
	out.reasoningMaxTokens, _ = f.get("reasoning_max_tokens")
	if v, ok := f.get("client"); ok {
		out.client, _ = c.optStr(v, 0, f.at("client"))
	}
	out.setup = listOf(c, f, "setup", setupFieldFrom)
	c.extra(o, []string{"name", "display_name", "description", "model", "toolsets", "reasoning_effort", "reasoning_max_tokens",
		"client", "setup"}, loc)
	return out, c.count() == before
}
