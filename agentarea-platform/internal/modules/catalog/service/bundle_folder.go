package service

import (
	"encoding/json"
	"fmt"
	"path"
	"regexp"
	"sort"
	"strings"

	"go.yaml.in/yaml/v3"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx/wirejson"
)

// EntryFile is the root file of a bundle folder (ADR-0060).
const EntryFile = "agentarea.yaml"

const folderSchemaVersion = "1"

// folderSections are the entry file's sections in the order objects are read.
func folderSections() []string {
	return []string{"agents", "mcp", "skills", "policies", "schedules", "channels"}
}

var (
	limitKeyRe = regexp.MustCompile(`^(monthly|run)_([a-z]{3})$`)
)

func agentFileFields() []string {
	return []string{"name", "display_name", "description", "model", "reasoning_effort", "reasoning_max_tokens", "client", "toolsets",
		"skills", "mcp", "delegates", "limits", "builtin_tools", "renamed_from"}
}

func mcpFileFields() []string {
	return []string{"name", "display_name", "catalog", "json_spec", "bindings", "context_secret", "renamed_from"}
}

func policyFileFields() []string {
	return []string{"name", "subject", "target", "effect", "params", "condition", "priority", "enabled", "message", "renamed_from"}
}

func scheduleFields() []string {
	return []string{"name", "agent", "cron", "timezone", "enabled", "renamed_from"}
}

func channelFields() []string {
	return []string{"name", "display_name", "type", "agent", "bindings", "prompt", "enabled", "renamed_from"}
}

func skillInlineKeys() []string {
	return []string{"name", "source_type", "content", "files", "source_url", "renamed_from"}
}

// source is where an object of the folder was written: a file, or an inline
// object of the entry file. text is the YAML its locations refer to.
type source struct {
	path, text string
	offset     int
	loc        []any
	inline     bool
}

func (s source) label() string {
	if s.inline {
		return fmt.Sprintf("%s (%s)", s.path, locText(s.loc))
	}
	return s.path
}

func locText(loc []any) string {
	parts := make([]string, len(loc))
	for i, p := range loc {
		parts[i] = fmt.Sprint(p)
	}
	return strings.Join(parts, ".")
}

// fail is a parse error naming the file and, when the YAML holds loc, its line.
func (s source) fail(loc []any, format string, a ...any) error {
	msg := fmt.Sprintf(format, a...)
	if loc != nil {
		if line := yamlLine(s.text, join(s.loc, loc...)); line > 0 {
			return &BundleParseError{fmt.Sprintf("%s:%d: %s", s.path, line+s.offset, msg)}
		}
	}
	return &BundleParseError{s.path + ": " + msg}
}

func (s source) checked(model string, c *checker) error {
	loc := []any{}
	if len(c.errs) > 0 && len(c.errs[0].Loc) > 0 {
		loc = c.errs[0].Loc
	}
	return s.fail(loc, "%s", validationText(model, c.errs))
}

// yamlLine is the 1-based line of the node at loc in text, the deepest one found; 0 when text does not parse.
func yamlLine(text string, loc []any) int {
	var doc yaml.Node
	if yaml.Unmarshal([]byte(text), &doc) != nil || len(doc.Content) == 0 {
		return 0
	}
	n := doc.Content[0]
	line := n.Line
	for _, k := range loc {
		switch n.Kind {
		case yaml.MappingNode:
			key, ok := k.(string)
			if !ok {
				return line
			}
			found := false
			for i := 0; i+1 < len(n.Content); i += 2 {
				if n.Content[i].Value == key {
					line, n, found = n.Content[i].Line, n.Content[i+1], true
					break
				}
			}
			if !found {
				return line
			}
		case yaml.SequenceNode:
			i, ok := k.(int)
			if !ok || i < 0 || i >= len(n.Content) {
				return line
			}
			n = n.Content[i]
			line = n.Line
		case yaml.DocumentNode, yaml.ScalarNode, yaml.AliasNode:
			return line
		}
	}
	return line
}

// globRegexp is a path glob relative to the folder root: '*' and '?' within a
// segment, '**' across segments, an optional './' prefix and trailing '/'.
func globRegexp(pattern string) (*regexp.Regexp, error) {
	p := strings.TrimSuffix(strings.TrimPrefix(pattern, "./"), "/")
	if p == "" || strings.HasPrefix(p, "/") || strings.Contains(p, "\\") {
		return nil, fmt.Errorf("must be a relative path")
	}
	segs := strings.Split(p, "/")
	var b strings.Builder
	b.WriteString("^")
	for i, s := range segs {
		last := i == len(segs)-1
		switch s {
		case "", ".", "..":
			return nil, fmt.Errorf("must stay inside the folder")
		case "**":
			if last {
				b.WriteString(".*")
			} else {
				b.WriteString("(?:[^/]+/)*")
			}
			continue
		}
		for _, r := range s {
			switch r {
			case '*':
				b.WriteString("[^/]*")
			case '?':
				b.WriteString("[^/]")
			default:
				b.WriteString(regexp.QuoteMeta(string(r)))
			}
		}
		if !last {
			b.WriteString("/")
		}
	}
	b.WriteString("$")
	return regexp.Compile(b.String())
}

// folderLoad reads a folder whose root holds agentarea.yaml.
type folderLoad struct {
	files   StrPairs
	entry   source
	claimed map[string]string
	issues  []PreviewIssue

	defaults folderDefaults
	b        Bundle
	sources  map[EntityKind]map[string]source
	// policies wait for every agent to be read: their subjects name agents.
	policies      []pendingPolicy
	agentPolicies []BundlePolicy
}

type pendingPolicy struct {
	src  source
	name string
	data wirejson.Object
}

type folderDefaults struct {
	model, reasoningEffort, reasoningMaxTokens any
	hasModel, hasReasoning                     bool
	limits                                     wirejson.Object
}

func (l *folderLoad) warn(key *string, format string, a ...any) {
	l.issues = append(l.issues, PreviewIssue{Severity: SeverityWarn, Message: fmt.Sprintf(format, a...), EntityKey: key})
}

func loadEntryFolder(files StrPairs) (Bundle, []PreviewIssue, error) {
	text, _ := files.Get(EntryFile)
	l := &folderLoad{files: files, entry: source{path: EntryFile, text: text}, claimed: map[string]string{EntryFile: "entry"},
		sources: map[EntityKind]map[string]source{}}
	if err := l.load(); err != nil {
		return Bundle{}, nil, err
	}
	return l.b, l.issues, nil
}

func (l *folderLoad) load() error {
	data, err := yamlMapping(EntryFile, l.entry.text)
	if err != nil {
		return err
	}
	known := append([]string{"name", "schema_version", "display_name", "description", "setup", "defaults", "targets"}, folderSections()...)
	for _, m := range data {
		if !containsString(known, m.Key) {
			return l.entry.fail([]any{m.Key}, "unknown key '%s'; agentarea.yaml takes %s", m.Key, strings.Join(known, ", "))
		}
	}
	v, ok := data.Get("schema_version")
	if !ok {
		return l.entry.fail(nil, "schema_version is required; this platform reads schema_version: %s", folderSchemaVersion)
	}
	if n, isNumber := v.(json.Number); !isNumber || string(n) != folderSchemaVersion {
		return l.entry.fail([]any{"schema_version"}, "schema_version %s is not supported; this platform reads schema_version: %s", pyStr(v), folderSchemaVersion)
	}
	l.b = Bundle{SchemaVersion: BundleSchemaVersion, Metadata: BundleMetadata{Capabilities: []string{}}, Setup: []SetupField{},
		MCPs: []BundleMCP{}, Skills: []BundleSkill{}, Agents: []BundleAgent{}, Channels: []BundleChannel{}, Automations: []BundleAutomation{},
		Policies: []BundlePolicy{}}
	var c checker
	f := fields{data, nil}
	if _, ok := data.Get("name"); !ok {
		return l.entry.fail(nil, "name is required: the bundle's name in the workspace")
	}
	l.b.Name = c.requiredStr(f, "name", 1, BundleMaxNameLength)
	if v, ok := f.get("display_name"); ok {
		l.b.DisplayName, _ = c.optStr(v, BundleMaxNameLength, f.at("display_name"))
	}
	if v, ok := f.get("description"); ok && v != nil {
		l.b.Description, _ = c.str(v, 0, 0, f.at("description"))
	}
	if len(c.errs) > 0 {
		return l.entry.checked("Bundle", &c)
	}
	if err := l.readSetup(data); err != nil {
		return err
	}
	if err := l.readDefaults(data); err != nil {
		return err
	}
	declared := false
	for _, section := range folderSections() {
		got, err := l.readSection(data, section)
		if err != nil {
			return err
		}
		declared = declared || got
	}
	if !declared {
		return l.entry.fail(nil, "selects no files and declares no objects; add includes, e.g. agents: {include: ./agents/*.md}")
	}
	if err := l.finishAgents(); err != nil {
		return err
	}
	for _, f := range sortedFiles(l.files) {
		if _, ok := l.claimed[f.Key]; !ok {
			l.warn(nil, "%s: ignored: no include in agentarea.yaml selects it; not deployed", f.Key)
		}
	}
	return nil
}

func sortedFiles(files StrPairs) StrPairs {
	out := append(StrPairs{}, files...)
	sort.SliceStable(out, func(i, j int) bool { return out[i].Key < out[j].Key })
	return out
}

func (l *folderLoad) readSetup(data wirejson.Object) error {
	v, ok := data.Get("setup")
	if !ok || v == nil {
		return nil
	}
	o, ok := v.(wirejson.Object)
	if !ok {
		return l.entry.fail([]any{"setup"}, "setup must be a mapping of setup key to field")
	}
	for _, m := range o {
		field, ok := m.Value.(wirejson.Object)
		if !ok {
			return l.entry.fail([]any{"setup", m.Key}, "setup.%s must be a mapping", m.Key)
		}
		if _, has := field.Get("key"); has {
			return l.entry.fail([]any{"setup", m.Key, "key"}, "setup.%s: the key is the map key; remove 'key'", m.Key)
		}
		var c checker
		s, ok := setupFieldFrom(&c, objectWith(wirejson.Object{{Key: "key", Value: m.Key}}, field), nil)
		if !ok {
			return source{path: EntryFile, text: l.entry.text, loc: []any{"setup", m.Key}}.checked("SetupField", &c)
		}
		l.b.Setup = append(l.b.Setup, s)
	}
	return nil
}

func (l *folderLoad) readDefaults(data wirejson.Object) error {
	v, ok := data.Get("defaults")
	if !ok || v == nil {
		return nil
	}
	o, ok := v.(wirejson.Object)
	if !ok {
		return l.entry.fail([]any{"defaults"}, "defaults must be a mapping")
	}
	for _, m := range o {
		loc := []any{"defaults", m.Key}
		switch m.Key {
		case "model":
			l.defaults.model, l.defaults.hasModel = m.Value, true
		case "reasoning_effort":
			l.defaults.reasoningEffort, l.defaults.hasReasoning = m.Value, true
		case "reasoning_max_tokens":
			l.defaults.reasoningMaxTokens, l.defaults.hasReasoning = m.Value, true
		case "limits":
			limits, ok := m.Value.(wirejson.Object)
			if !ok {
				return l.entry.fail(loc, "defaults.limits must be a mapping")
			}
			l.defaults.limits = limits
		case "skills", "mcp", "delegates", "toolsets":
			return l.entry.fail(loc, "defaults may not carry '%s'; list %s on each agent, where a reviewer sees the access", m.Key, m.Key)
		default:
			return l.entry.fail(loc, "defaults take only model, reasoning_effort, reasoning_max_tokens and limits, not '%s'", m.Key)
		}
	}
	return nil
}

func globsOf(v any) ([]string, bool) {
	switch x := v.(type) {
	case string:
		return []string{x}, true
	case []any:
		out := make([]string, len(x))
		for i, g := range x {
			s, ok := g.(string)
			if !ok {
				return nil, false
			}
			out[i] = s
		}
		return out, true
	}
	return nil, false
}

func (l *folderLoad) compile(section, key string, v any) ([]*regexp.Regexp, []string, error) {
	globs, ok := globsOf(v)
	if !ok {
		return nil, nil, l.entry.fail([]any{section, key}, "%s.%s must be a glob or a list of globs", section, key)
	}
	out := make([]*regexp.Regexp, len(globs))
	for i, g := range globs {
		re, err := globRegexp(g)
		if err != nil {
			return nil, nil, l.entry.fail([]any{section, key}, "%s.%s '%s' %s", section, key, g, err.Error())
		}
		out[i] = re
	}
	return out, globs, nil
}

func anyMatch(res []*regexp.Regexp, p string) bool {
	for _, re := range res {
		if re.MatchString(p) {
			return true
		}
	}
	return false
}

// readSection reads a section's inline objects and the files its globs select;
// false when it declares nothing.
func (l *folderLoad) readSection(data wirejson.Object, section string) (bool, error) {
	v, ok := data.Get(section)
	if !ok || v == nil {
		return false, nil
	}
	o, ok := v.(wirejson.Object)
	if !ok {
		return false, l.entry.fail([]any{section}, "%s must be a mapping: include/exclude globs and objects by key", section)
	}
	var include, exclude []*regexp.Regexp
	var includeGlobs []string
	declared := false
	for _, m := range o {
		switch m.Key {
		case "include":
			res, globs, err := l.compile(section, m.Key, m.Value)
			if err != nil {
				return false, err
			}
			include, includeGlobs = res, globs
		case "exclude":
			res, _, err := l.compile(section, m.Key, m.Value)
			if err != nil {
				return false, err
			}
			exclude = res
		default:
			declared = true
			obj, ok := m.Value.(wirejson.Object)
			if !ok {
				return false, l.entry.fail([]any{section, m.Key}, "%s.%s must be a mapping: an inline object keyed '%s'", section, m.Key, m.Key)
			}
			src := source{path: EntryFile, text: l.entry.text, loc: []any{section, m.Key}, inline: true}
			if err := l.readInline(section, m.Key, obj, src); err != nil {
				return false, err
			}
		}
	}
	if len(include) == 0 {
		return declared, nil
	}
	selected := 0
	if section == "skills" {
		dirs, err := l.selectSkillDirs(include, exclude)
		if err != nil {
			return true, err
		}
		for _, dir := range dirs {
			if err := l.readSkillDir(dir); err != nil {
				return true, err
			}
		}
		selected = len(dirs)
	} else {
		for _, f := range sortedFiles(l.files) {
			if f.Key == EntryFile || !anyMatch(include, f.Key) || anyMatch(exclude, f.Key) {
				continue
			}
			if other, taken := l.claimed[f.Key]; taken {
				return true, &BundleParseError{fmt.Sprintf("%s: selected by both %s and %s", f.Key, other, section)}
			}
			l.claimed[f.Key] = section
			selected++
			if err := l.readFile(section, f.Key, f.Value); err != nil {
				return true, err
			}
		}
	}
	if selected == 0 {
		l.warn(nil, "agentarea.yaml: %s.include %s selects no file", section, strings.Join(includeGlobs, ", "))
	}
	return true, nil
}

func (l *folderLoad) selectSkillDirs(include, exclude []*regexp.Regexp) ([]string, error) {
	var dirs []string
	for _, f := range sortedFiles(l.files) {
		if path.Base(f.Key) != "SKILL.md" || !strings.Contains(f.Key, "/") {
			continue
		}
		dir := path.Dir(f.Key)
		if (anyMatch(include, dir) || anyMatch(include, f.Key)) && !anyMatch(exclude, dir) && !anyMatch(exclude, f.Key) {
			dirs = append(dirs, dir)
		}
	}
	for _, a := range dirs {
		for _, b := range dirs {
			if a != b && strings.HasPrefix(a, b+"/") {
				return nil, &BundleParseError{fmt.Sprintf("%s: skill directory %s is inside skill directory %s", a+"/SKILL.md", a, b)}
			}
		}
	}
	return dirs, nil
}

func stem(p string) string {
	base := path.Base(p)
	if i := strings.LastIndex(base, "."); i > 0 {
		return base[:i]
	}
	return base
}

func (l *folderLoad) readFile(section, p, text string) error {
	src := source{path: p, text: text}
	markdown := strings.HasSuffix(p, ".md")
	switch section {
	case "agents", "schedules":
		if !markdown {
			return &BundleParseError{fmt.Sprintf("%s: %s are Markdown files (.md) with front matter", p, section)}
		}
		meta, body, err := folderFrontmatter(p, text)
		if err != nil {
			return err
		}
		src.text, src.offset = frontmatterText(text), 1
		if section == "agents" {
			return l.readAgent(meta, body, src)
		}
		return l.readSchedule(meta, body, src)
	}
	if _, isYAML := yamlStem(path.Base(p)); !isYAML {
		return &BundleParseError{fmt.Sprintf("%s: %s are YAML files (.yaml or .yml)", p, section)}
	}
	data, err := yamlMapping(p, text)
	if err != nil {
		return err
	}
	switch section {
	case "mcp":
		return l.readMCP(data, src)
	case "policies":
		return l.readPolicy(data, src)
	}
	return l.readChannel(data, src)
}

func frontmatterText(text string) string {
	if m := frontmatterRe.FindStringSubmatch(text); m != nil {
		return m[1]
	}
	return ""
}

func (l *folderLoad) readInline(section, key string, o wirejson.Object, src source) error {
	if n, ok := o.Get("name"); ok && n != key {
		return src.fail([]any{"name"}, "%s.%s: name '%s' differs from its key '%s'; drop name or make them equal", section, key, pyStr(n), key)
	}
	meta := objectWith(wirejson.Object{{Key: "name", Value: key}}, o)
	switch section {
	case "agents":
		body, _ := meta.Get("instruction")
		text, ok := body.(string)
		if body != nil && !ok {
			return src.fail([]any{"instruction"}, "instruction must be text")
		}
		return l.readAgent(omit(meta, "instruction"), text, src)
	case "schedules":
		body, _ := meta.Get("prompt")
		text, ok := body.(string)
		if !ok {
			return src.fail(nil, "schedule '%s' needs prompt, the text the agent is asked", key)
		}
		return l.readSchedule(omit(meta, "prompt"), text, src)
	case "mcp":
		return l.readMCP(meta, src)
	case "skills":
		return l.readInlineSkill(meta, src, key)
	case "policies":
		return l.readPolicy(meta, src)
	}
	return l.readChannel(meta, src)
}

func omit(o wirejson.Object, key string) wirejson.Object {
	out := wirejson.Object{}
	for _, m := range o {
		if m.Key != key {
			out = append(out, m)
		}
	}
	return out
}

func unknownField(o wirejson.Object, allowed []string, src source, kind string) error {
	for _, m := range o {
		if !containsString(allowed, m.Key) {
			return src.fail([]any{m.Key}, "unknown %s field '%s'; %s takes %s", kind, m.Key, kind, strings.Join(allowed, ", "))
		}
	}
	return nil
}

// objectName is the object's key: its name, required, in the shape of an entity key.
func (l *folderLoad) objectName(o wirejson.Object, src source, kind EntityKind, missing string) (string, error) {
	v, ok := o.Get("name")
	name, isString := v.(string)
	if !ok || !isString || name == "" {
		return "", src.fail(nil, "%s", missing)
	}
	if !entityKeyRe.MatchString(name) {
		return "", src.fail([]any{"name"}, "%s name '%s' must match [a-zA-Z][a-zA-Z0-9_-]*; it is the object's key", kind, name)
	}
	if l.sources[kind] == nil {
		l.sources[kind] = map[string]source{}
	}
	if first, dup := l.sources[kind][name]; dup {
		return "", &BundleParseError{fmt.Sprintf("two %ss are named '%s': %s and %s", kind, name, first.label(), src.label())}
	}
	l.sources[kind][name] = src
	file := stem(src.path)
	if kind == KindSkill {
		file = path.Base(path.Dir(src.path))
	}
	if !src.inline && file != name {
		l.warn(strp(name), "%s: file name '%s' differs from name '%s'; the object's key is '%s'", src.path, file, name, name)
	}
	return name, nil
}

func (l *folderLoad) readAgent(meta wirejson.Object, body string, src source) error {
	if err := unknownField(meta, agentFileFields(), src, "agent"); err != nil {
		return err
	}
	key, err := l.objectName(meta, src, KindAgent, "front matter must set name, the agent's key")
	if err != nil {
		return err
	}
	get := func(k string) (any, bool) { return meta.Get(k) }
	displayName := any(key)
	if v, ok := get("display_name"); ok && v != nil {
		displayName = v
	}
	data := wirejson.Object{{Key: "key", Value: key}, {Key: "name", Value: displayName}, {Key: "instruction", Value: pyStrip(body)}}
	for _, k := range []struct{ from, to string }{{"description", "description"}, {"client", "client"}, {"toolsets", "toolsets"},
		{"skills", "skills"}, {"mcp", "mcps"}, {"delegates", "delegates"}, {"renamed_from", "renamed_from"}} {
		if v, ok := get(k.from); ok && v != nil {
			data.Set(k.to, v)
		}
	}
	if v, ok := get("model"); ok {
		data.Set("model", v)
	} else if l.defaults.hasModel {
		data.Set("model", l.defaults.model)
	}
	_, ownEffort := get("reasoning_effort")
	_, ownTokens := get("reasoning_max_tokens")
	switch {
	case ownEffort || ownTokens:
		for _, k := range []string{"reasoning_effort", "reasoning_max_tokens"} {
			if v, ok := get(k); ok {
				data.Set(k, v)
			}
		}
	case l.defaults.hasReasoning:
		data.Set("reasoning_effort", l.defaults.reasoningEffort)
		data.Set("reasoning_max_tokens", l.defaults.reasoningMaxTokens)
	}
	var c checker
	agent, ok := bundleAgentFrom(&c, data, nil)
	if !ok {
		for i, e := range c.errs {
			if len(e.Loc) > 0 {
				loc := append([]any{}, e.Loc...)
				switch loc[0] {
				case "mcps":
					loc[0] = "mcp"
				case "key":
					loc[0] = "name"
				case "name":
					loc[0] = "display_name"
				}
				c.errs[i].Loc = loc
			}
		}
		return src.checked("BundleAgent", &c)
	}
	l.b.Agents = append(l.b.Agents, agent)
	limits := wirejson.Object{}
	for _, m := range l.defaults.limits {
		limits.Set(m.Key, m.Value)
	}
	if v, ok := get("limits"); ok && v != nil {
		own, ok := v.(wirejson.Object)
		if !ok {
			return src.fail([]any{"limits"}, "limits must be a mapping")
		}
		for _, m := range own {
			if m.Value == nil {
				limits = omit(limits, m.Key)
				continue
			}
			limits.Set(m.Key, m.Value)
		}
	}
	policies, err := agentLimitPolicies(key, limits, src)
	if err != nil {
		return err
	}
	tools, err := builtinToolPolicies(key, meta, src)
	if err != nil {
		return err
	}
	l.agentPolicies = append(l.agentPolicies, append(policies, tools...)...)
	return nil
}

func positiveAmount(v any) bool {
	switch x := v.(type) {
	case json.Number:
		f, err := x.Float64()
		return err == nil && f > 0
	case wirejson.Float:
		return x > 0
	}
	return false
}

// agentLimitPolicies are the cap rules an agent's limits install: monthly_<cur>
// is the agent's monthly spend cap, run_<cur> the budget of one run, both in
// the billing currency <cur>.
func agentLimitPolicies(agent string, limits wirejson.Object, src source) ([]BundlePolicy, error) {
	var out []BundlePolicy
	for _, m := range limits {
		match := limitKeyRe.FindStringSubmatch(m.Key)
		if match == nil {
			return nil, src.fail([]any{"limits"}, "limits.%s is not supported yet; the runtime has no per-agent %s", m.Key, m.Key)
		}
		if !positiveAmount(m.Value) {
			return nil, src.fail([]any{"limits"}, "limits.%s must be a number greater than 0", m.Key)
		}
		params := wirejson.Object{{Key: "amount_usd", Value: m.Value}}
		if match[1] == "run" {
			params.Set("period", "run")
		}
		currency := strings.ToUpper(match[2])
		out = append(out, BundlePolicy{Key: agent + "-" + match[1] + "-cap", Subject: agent, Target: "spend", Effect: "cap", Params: params,
			Enabled: true, BillingCurrency: &currency})
	}
	sort.SliceStable(out, func(i, j int) bool { return out[i].Key < out[j].Key })
	return out, nil
}

// builtinToolPolicies are the deny rules switching off an agent's built-in tools.
func builtinToolPolicies(agent string, meta wirejson.Object, src source) ([]BundlePolicy, error) {
	v, ok := meta.Get("builtin_tools")
	if !ok || v == nil {
		return nil, nil
	}
	o, ok := v.(wirejson.Object)
	if !ok {
		return nil, src.fail([]any{"builtin_tools"}, "builtin_tools must be a mapping of tool to true or false")
	}
	var out []BundlePolicy
	for _, m := range o {
		if m.Key != "ask_human_form" {
			return nil, src.fail([]any{"builtin_tools"}, "builtin_tools.%s is not supported yet; only ask_human_form can be switched off", m.Key)
		}
		on, isBool := m.Value.(bool)
		if !isBool {
			return nil, src.fail([]any{"builtin_tools"}, "builtin_tools.%s must be true or false", m.Key)
		}
		if !on {
			out = append(out, BundlePolicy{Key: agent + "-no-ask-human-form", Subject: agent, Target: "tool:request_user_input", Effect: "deny",
				Params: wirejson.Object{}, Enabled: true})
		}
	}
	return out, nil
}

func (l *folderLoad) readSchedule(meta wirejson.Object, body string, src source) error {
	if err := unknownField(meta, scheduleFields(), src, "schedule"); err != nil {
		return err
	}
	key, err := l.objectName(meta, src, KindAutomation, "front matter must set name, the schedule's key")
	if err != nil {
		return err
	}
	if v, ok := meta.Get("agent"); !ok || v == nil || v == "" {
		return src.fail(nil, "schedule '%s' needs agent, the key of the agent it runs", key)
	}
	data := objectWith(omit(meta, "name"), wirejson.Object{{Key: "key", Value: key}, {Key: "prompt", Value: pyStrip(body)}})
	var c checker
	a, ok := bundleAutomationFrom(&c, data, nil)
	if !ok {
		return src.checked("BundleAutomation", &c)
	}
	l.b.Automations = append(l.b.Automations, a)
	return nil
}

// displayed is o keyed by its name, with display_name as the entity's name.
func displayed(o wirejson.Object, key string) wirejson.Object {
	name := any(key)
	if v, ok := o.Get("display_name"); ok && v != nil {
		name = v
	}
	return objectWith(omit(omit(o, "name"), "display_name"), wirejson.Object{{Key: "key", Value: key}, {Key: "name", Value: name}})
}

func (l *folderLoad) readMCP(data wirejson.Object, src source) error {
	if err := unknownField(data, mcpFileFields(), src, "mcp"); err != nil {
		return err
	}
	key, err := l.objectName(data, src, KindMCP, "name is required: the MCP server's key")
	if err != nil {
		return err
	}
	var c checker
	m, ok := bundleMCPFrom(&c, displayed(data, key), nil)
	if !ok {
		return src.checked("BundleMcp", &c)
	}
	l.b.MCPs = append(l.b.MCPs, m)
	return nil
}

func (l *folderLoad) readChannel(data wirejson.Object, src source) error {
	if err := unknownField(data, channelFields(), src, "channel"); err != nil {
		return err
	}
	key, err := l.objectName(data, src, KindChannel, "name is required: the channel's key")
	if err != nil {
		return err
	}
	if v, ok := data.Get("agent"); !ok || v == nil || v == "" {
		return src.fail(nil, "channel '%s' needs agent, the key of the agent it runs", key)
	}
	var c checker
	ch, ok := bundleChannelFrom(&c, displayed(data, key), nil)
	if !ok {
		return src.checked("BundleChannel", &c)
	}
	l.b.Channels = append(l.b.Channels, ch)
	return nil
}

func (l *folderLoad) readPolicy(data wirejson.Object, src source) error {
	if err := unknownField(data, policyFileFields(), src, "policy"); err != nil {
		return err
	}
	key, err := l.objectName(data, src, KindPolicy, "name is required: the policy's key")
	if err != nil {
		return err
	}
	subject, ok := data.Get("subject")
	if !ok || subject == nil || subject == "" {
		return src.fail(nil, "policy '%s' needs a subject: an agent key of this bundle, a list of them, or \"*\"", key)
	}
	if subject == "workspace" {
		return src.fail([]any{"subject"}, "%s", policySubjectRefused(key))
	}
	if effect, _ := data.Get("effect"); effect == "allow" {
		return src.fail([]any{"effect"}, "%s", policyEffectRefused(key))
	}
	l.policies = append(l.policies, pendingPolicy{src: src, name: key,
		data: objectWith(omit(data, "name"), wirejson.Object{{Key: "key", Value: key}})})
	return nil
}

func (l *folderLoad) readSkillDir(dir string) error {
	var entries StrPairs
	for _, f := range sortedFiles(l.files) {
		if !strings.HasPrefix(f.Key, dir+"/") {
			continue
		}
		if other, taken := l.claimed[f.Key]; taken {
			return &BundleParseError{fmt.Sprintf("%s: selected by both %s and skills", f.Key, other)}
		}
		l.claimed[f.Key] = "skills"
		entries = append(entries, StrPair{Key: strings.TrimPrefix(f.Key, dir+"/"), Value: f.Value})
	}
	skillPath := dir + "/SKILL.md"
	content, _ := l.files.Get(skillPath)
	meta, _, err := folderFrontmatter(skillPath, content)
	if err != nil {
		return err
	}
	src := source{path: skillPath, text: frontmatterText(content), offset: 1}
	key, err := l.objectName(meta, src, KindSkill, "front matter must set name, the skill's key")
	if err != nil {
		return err
	}
	data := wirejson.Object{{Key: "key", Value: key}, {Key: "name", Value: key}}
	if v, ok := meta.Get("renamed_from"); ok && v != nil {
		data.Set("renamed_from", v)
	}
	if len(entries) == 1 {
		data = append(data, wirejson.Member{Key: "source_type", Value: "content"}, wirejson.Member{Key: "content", Value: content})
	} else {
		data = append(data, wirejson.Member{Key: "source_type", Value: "files"}, wirejson.Member{Key: "files", Value: entries.object()})
	}
	var c checker
	s, ok := bundleSkillFrom(&c, data, nil)
	if !ok {
		return src.checked("BundleSkill", &c)
	}
	l.b.Skills = append(l.b.Skills, s)
	return nil
}

func (l *folderLoad) readInlineSkill(meta wirejson.Object, src source, key string) error {
	if err := unknownField(meta, skillInlineKeys(), src, "skill"); err != nil {
		return err
	}
	if _, err := l.objectName(meta, src, KindSkill, "name is required: the skill's key"); err != nil {
		return err
	}
	var c checker
	s, ok := bundleSkillFrom(&c, objectWith(meta, wirejson.Object{{Key: "key", Value: key}}), nil)
	if !ok {
		return src.checked("BundleSkill", &c)
	}
	l.b.Skills = append(l.b.Skills, s)
	return nil
}

// finishAgents checks delegation and builds the policies, whose subjects name agents.
func (l *folderLoad) finishAgents() error {
	keys := map[string]bool{}
	ordered := make([]string, len(l.b.Agents))
	for i, a := range l.b.Agents {
		keys[a.Key] = true
		ordered[i] = a.Key
	}
	for _, a := range l.b.Agents {
		if problem := delegateProblem(a, keys); problem != "" {
			return l.sources[KindAgent][a.Key].fail(nil, "%s", problem)
		}
	}
	if _, cycle := agentOrder(l.b.Agents); cycle != nil {
		return l.sources[KindAgent][cycle[0]].fail(nil, "%s", cycleText(cycle))
	}
	for _, p := range l.policies {
		subjects, keyed, problem := policySubjects(p.data, ordered)
		if problem != "" {
			return p.src.fail([]any{"subject"}, "policy '%s': %s", p.name, problem)
		}
		expand := subjects != nil
		if !expand {
			s, _ := p.data.Get("subject")
			name, isString := s.(string)
			if !isString {
				return p.src.fail([]any{"subject"}, "policy '%s' needs a subject: an agent key of this bundle, a list of them, or \"*\"", p.name)
			}
			subjects = []string{name}
		}
		for _, s := range subjects {
			if !keys[s] {
				return p.src.fail([]any{"subject"}, "%s", policyStranger(p.name, s))
			}
			data := p.data
			if expand {
				data = perSubject(p.data, s, keyed)
			}
			var c checker
			got, ok := bundlePolicyFrom(&c, data, nil)
			if !ok {
				return p.src.checked("BundlePolicy", &c)
			}
			l.b.Policies = append(l.b.Policies, got)
		}
	}
	l.b.Policies = append(l.b.Policies, l.agentPolicies...)
	return nil
}
