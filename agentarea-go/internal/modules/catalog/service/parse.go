package service

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"math"
	"regexp"
	"slices"
	"strconv"
	"strings"
	"unicode/utf8"

	"go.yaml.in/yaml/v3"

	"github.com/agentarea/agentarea/agentarea-go/internal/modules/catalog/domain"
)

// Index source limits (service.py).
const (
	MaxSourceBytes     = 5 * 1024 * 1024
	MaxYAMLSourceBytes = 1024 * 1024
	MaxYAMLNodes       = 200_000
	MaxSourceItems     = 2000
	unpinnedVersion    = "latest"
)

// SourceError is RegistrySourceError: the source is unreadable or not an
// index; its message is safe to show the registry's owner.
type SourceError struct{ Msg string }

func (e *SourceError) Error() string { return e.Msg }

// Entry is one parsed catalog entry.
type Entry struct {
	ExternalID  string
	Name        string
	Description *string
	Version     *string
	Spec        map[string]any
	Tags        []any
	Rank        *int
}

func strp(s string) *string { return &s }

func size(n int) string {
	if n >= 1024*1024 {
		return fmt.Sprintf("%d MB", n/(1024*1024))
	}
	return fmt.Sprintf("%d KB", n/1024)
}

// DecodeJSON decodes one JSON document with numbers kept as json.Number.
func DecodeJSON(body []byte) (any, error) {
	dec := json.NewDecoder(bytes.NewReader(body))
	dec.UseNumber()
	var v any
	if err := dec.Decode(&v); err != nil {
		return nil, err
	}
	if _, err := dec.Token(); !errors.Is(err, io.EOF) {
		return nil, errors.New("trailing data")
	}
	return v, nil
}

// ParseUntrusted is _parse_untrusted: JSON, else YAML within its caps
// (no aliases, at most MaxYAMLNodes nodes).
func ParseUntrusted(body []byte) (any, error) {
	if !utf8.Valid(body) {
		return nil, &SourceError{Msg: "the source is not a valid JSON or YAML index"}
	}
	if v, err := DecodeJSON(body); err == nil {
		return v, nil
	}
	if len(body) > MaxYAMLSourceBytes {
		return nil, &SourceError{Msg: "the source is a YAML index over " + size(MaxYAMLSourceBytes) + "; publish it as JSON"}
	}
	v, err := loadYAML(body, MaxYAMLNodes)
	if err != nil {
		return nil, &SourceError{Msg: "the source is not a valid JSON or YAML index"}
	}
	return v, nil
}

func loadYAML(body []byte, maxNodes int) (any, error) {
	var doc yaml.Node
	dec := yaml.NewDecoder(bytes.NewReader(body))
	if err := dec.Decode(&doc); err != nil {
		if errors.Is(err, io.EOF) {
			return nil, nil
		}
		return nil, err
	}
	var more yaml.Node
	if err := dec.Decode(&more); !errors.Is(err, io.EOF) {
		return nil, errors.New("more than one YAML document")
	}
	nodes := 0
	return yamlValue(&doc, &nodes, maxNodes)
}

func yamlValue(n *yaml.Node, nodes *int, maxNodes int) (any, error) {
	*nodes++
	if *nodes > maxNodes {
		return nil, fmt.Errorf("YAML holds more than %d nodes", maxNodes)
	}
	switch n.Kind {
	case yaml.DocumentNode:
		if len(n.Content) == 0 {
			return nil, nil
		}
		return yamlValue(n.Content[0], nodes, maxNodes)
	case yaml.AliasNode:
		return nil, errors.New("YAML aliases are not accepted")
	case yaml.SequenceNode:
		out := make([]any, 0, len(n.Content))
		for _, c := range n.Content {
			v, err := yamlValue(c, nodes, maxNodes)
			if err != nil {
				return nil, err
			}
			out = append(out, v)
		}
		return out, nil
	case yaml.ScalarNode:
		return yamlScalar(n)
	case yaml.MappingNode:
		out := make(map[string]any, len(n.Content)/2)
		for i := 0; i+1 < len(n.Content); i += 2 {
			k, err := yamlValue(n.Content[i], nodes, maxNodes)
			if err != nil {
				return nil, err
			}
			v, err := yamlValue(n.Content[i+1], nodes, maxNodes)
			if err != nil {
				return nil, err
			}
			out[fmt.Sprint(k)] = v
		}
		return out, nil
	}
	return nil, fmt.Errorf("unknown YAML node kind %d", n.Kind)
}

func yamlScalar(n *yaml.Node) (any, error) {
	switch n.ShortTag() {
	case "!!null":
		return nil, nil
	case "!!bool":
		var b bool
		err := n.Decode(&b)
		return b, err
	case "!!int":
		var i int64
		if err := n.Decode(&i); err != nil {
			return nil, err
		}
		return json.Number(strconv.FormatInt(i, 10)), nil
	case "!!float":
		var f float64
		if err := n.Decode(&f); err != nil {
			return nil, err
		}
		if math.IsInf(f, 0) || math.IsNaN(f) {
			return n.Value, nil
		}
		return json.Number(strconv.FormatFloat(f, 'g', -1, 64)), nil
	}
	return n.Value, nil
}

func typeByKey() []struct{ key, typ string } {
	return []struct{ key, typ string }{
		{"servers", domain.TypeMCPServers}, {"skills", domain.TypeSkills}, {"providers", domain.TypeLLMProviders},
		{"models", domain.TypeLLMModels}, {"agents", domain.TypeAgents}, {"bundles", domain.TypeBundles},
		{"source_types", domain.TypeSourceTypes},
	}
}

// DetectType is _detect_type: the registry type from the top-level key.
func DetectType(data any) (string, error) {
	m, ok := data.(map[string]any)
	if !ok {
		return "", errors.New("cannot detect registry type: source root is not a mapping")
	}
	var matched []string
	for _, k := range typeByKey() {
		if _, ok := m[k.key].([]any); ok {
			matched = append(matched, k.typ)
		}
	}
	switch len(matched) {
	case 1:
		return matched[0], nil
	case 0:
		keys := make([]string, len(typeByKey()))
		for i, k := range typeByKey() {
			keys[i] = k.key
		}
		return "", fmt.Errorf("cannot detect registry type: expected one top-level key of %s", strings.Join(keys, ", "))
	}
	return "", fmt.Errorf("ambiguous registry type: multiple catalog keys present %s", strings.Join(matched, ", "))
}

func mapping(v any) map[string]any {
	m, _ := v.(map[string]any)
	return m
}

func list(v any) []any {
	l, _ := v.([]any)
	return l
}

func sget(m map[string]any, k string) string {
	s, _ := m[k].(string)
	return s
}

func or(v any, d any) any {
	if v == nil {
		return d
	}
	return v
}

// truthyStr is `x or default` over a decoded value that should be a string.
func truthyStr(v any, d string) string {
	if s, ok := v.(string); ok && s != "" {
		return s
	}
	if v != nil && PyTruthy(v) {
		return fmt.Sprint(v)
	}
	return d
}

func optStr(v any) *string {
	switch t := v.(type) {
	case nil:
		return nil
	case string:
		return &t
	}
	s := fmt.Sprint(v)
	return &s
}

func cut500(v any) *string {
	s := truthyStr(v, "")
	if utf8.RuneCountInString(s) > 500 {
		s = string([]rune(s)[:500])
	}
	return &s
}

func nonNegInt(v any) (int, bool) {
	n, ok := v.(json.Number)
	if !ok {
		return 0, false
	}
	i, err := strconv.Atoi(string(n))
	return i, err == nil && i >= 0
}

// rankFields is rank_fields: a declared non-negative int rank.
func rankFields(ms ...map[string]any) *int {
	for _, m := range ms {
		if m == nil {
			continue
		}
		for _, k := range []string{"recommendation_rank", "agentarea:recommendation_rank"} {
			if i, ok := nonNegInt(m[k]); ok {
				return &i
			}
		}
	}
	return nil
}

func tagsOf(v any) []any {
	if l, ok := v.([]any); ok {
		return l
	}
	return []any{}
}

// ParseSource is _parse_source: entries in publication order, each with its rank.
func ParseSource(registryType string, data any) ([]Entry, error) {
	m := mapping(data)
	if m == nil {
		return nil, errors.New("the source root is not a mapping")
	}
	var items []Entry
	var err error
	switch registryType {
	case domain.TypeMCPServers:
		items, err = parseMCPServers(m)
	case domain.TypeSkills:
		items, err = parseSkills(m)
	case domain.TypeLLMProviders:
		items, err = parseProviders(m)
	case domain.TypeLLMModels:
		items, err = parseModels(m)
	case domain.TypeAgents:
		items = parseAgents(m)
	case domain.TypeBundles:
		items = parseBundles(m)
	case domain.TypeSourceTypes:
		items, err = parseSourceTypes(m)
	default:
		return nil, valueErr("Unknown registry_type: %s", registryType)
	}
	if err != nil {
		return nil, err
	}
	for i := range items {
		if items[i].Rank == nil {
			p := i
			items[i].Rank = &p
		}
	}
	return items, nil
}

// Dedupe is _dedupe: one entry per external_id, the last at the first's position.
func Dedupe(items []Entry) []Entry {
	pos := map[string]int{}
	var out []Entry
	for _, it := range items {
		if i, ok := pos[it.ExternalID]; ok {
			out[i] = it
			continue
		}
		pos[it.ExternalID] = len(out)
		out = append(out, it)
	}
	return out
}

func parseMCPServers(m map[string]any) ([]Entry, error) {
	servers := list(m["servers"])
	if len(servers) == 0 {
		return nil, nil
	}
	formats := map[string]bool{}
	for i, e := range servers {
		entry, ok := e.(map[string]any)
		if !ok {
			return nil, valueErr("Unrecognized MCP registry format: each entry of 'servers' must be a mapping (entry %d is not)", i)
		}
		_, isStd := entry["server"].(map[string]any)
		_, hasID := entry["registry_id"].(string)
		_, hasConn := entry["connection_type"].(string)
		_, hasSpec := entry["json_spec"].(map[string]any)
		switch {
		case isStd:
			formats["standard"] = true
		case hasID && hasConn && hasSpec:
			formats["agentarea"] = true
		default:
			return nil, valueErr("Unrecognized MCP registry format: each entry of 'servers' must contain either a mapping 'server' key or the AgentArea keys 'registry_id', 'connection_type', and 'json_spec' (entry %d)", i)
		}
	}
	if len(formats) != 1 {
		return nil, valueErr("Unrecognized MCP registry format: official and AgentArea entries cannot be mixed")
	}
	if formats["standard"] {
		return parseStandardMCP(servers), nil
	}
	return parseAgentAreaMCP(servers), nil
}

func authHeader(env []any) bool {
	for _, h := range env {
		switch strings.ToLower(sget(mapping(h), "name")) {
		case "authorization", "api_key", "x-api-key", "token":
			return true
		}
	}
	return false
}

func parseStandardMCP(servers []any) []Entry {
	var items []Entry
	for _, e := range servers {
		entry := mapping(e)
		server := mapping(entry["server"])
		meta := mapping(mapping(entry["_meta"])["io.modelcontextprotocol.registry/official"])
		if latest, ok := meta["isLatest"]; ok && !PyTruthy(latest) {
			continue
		}
		id := sget(server, "name")
		if id == "" {
			continue
		}
		title := truthyStr(server["title"], humanize(id))
		desc := cut500(server["description"])
		version := fmt.Sprint(or(server["version"], "latest"))
		rank := rankFields(server, mapping(server["metadata"]))
		for _, r := range list(server["remotes"]) {
			remote := mapping(r)
			transport := fmt.Sprint(or(remote["type"], "streamable-http"))
			url := sget(remote, "url")
			if url == "" {
				continue
			}
			env := NormalizeMCPEnvSchema(or(remote["headers"], []any{}))
			tags := []any{transport}
			if authHeader(env) {
				tags = append(tags, "requires-auth")
			}
			items = append(items, Entry{ExternalID: id, Name: title, Description: desc, Version: strp(version), Rank: rank, Tags: tags,
				Spec: map[string]any{"connection_type": "url", "url": url, "transport": transport, "env_schema": env, "raw_spec": server}})
		}
		for _, p := range list(server["packages"]) {
			pkg := mapping(p)
			if sget(pkg, "registryType") != "oci" {
				continue
			}
			image := truthyStr(pkg["name"], truthyStr(pkg["identifier"], ""))
			if image == "" {
				continue
			}
			pv := truthyStr(pkg["version"], version)
			ref := image
			if !strings.Contains(image, ":") {
				ref = image + ":" + pv
			}
			items = append(items, Entry{ExternalID: id + "/docker", Name: title, Description: desc, Version: strp(pv), Rank: rank,
				Tags: []any{"docker", "oci"}, Spec: map[string]any{
					"connection_type": "docker", "image": ref, "transport": "stdio",
					"env_schema": NormalizeMCPEnvSchema(or(pkg["environmentVariables"], []any{})), "package_registry": "oci",
					"package_name": image, "raw_spec": server}})
		}
		for _, p := range list(server["packages"]) {
			pkg := mapping(p)
			reg := sget(pkg, "registryType")
			if !slices.Contains([]string{"npm", "pypi", "nuget", "mcpb"}, reg) {
				continue
			}
			name := truthyStr(pkg["name"], truthyStr(pkg["identifier"], ""))
			if name == "" {
				continue
			}
			pv := truthyStr(pkg["version"], version)
			cmd, args, ok := commandPackageArgs(pkg, reg, version)
			if !ok {
				continue
			}
			items = append(items, Entry{ExternalID: id + "/command", Name: title, Description: desc, Version: strp(pv), Rank: rank,
				Tags: []any{"command", reg}, Spec: map[string]any{
					"connection_type": "command", "command": cmd, "args": args, "transport": "stdio",
					"package_registry": reg, "package_name": name,
					"env_schema": NormalizeMCPEnvSchema(or(pkg["environmentVariables"], []any{})), "raw_spec": server}})
		}
	}
	return items
}

func parseAgentAreaMCP(servers []any) []Entry {
	var items []Entry
	for _, e := range servers {
		entry := mapping(e)
		id, conn := sget(entry, "registry_id"), sget(entry, "connection_type")
		ext := id
		if conn != "url" {
			ext = id + "/" + conn
		}
		var tags []any
		if PyTruthy(entry["package_registry"]) {
			tags = append(tags, entry["package_registry"])
		}
		if PyTruthy(entry["requires_auth"]) {
			tags = append(tags, "requires-auth")
		}
		jsonSpec := mapping(entry["json_spec"])
		transport := truthyStr(entry["transport"], truthyStr(jsonSpec["transport"], ""))
		if transport != "" {
			tags = append(tags, transport)
		}
		spec := make(map[string]any, len(jsonSpec)+1)
		for k, v := range jsonSpec {
			spec[k] = v
		}
		spec["connection_type"] = conn
		if PyTruthy(entry["env_schema"]) {
			spec["env_schema"] = NormalizeMCPEnvSchema(entry["env_schema"])
		} else if _, ok := spec["env_schema"]; ok {
			spec["env_schema"] = NormalizeMCPEnvSchema(spec["env_schema"])
		} else if d := DeriveMCPEnvSchema(spec); len(d) > 0 {
			spec["env_schema"] = d
		}
		if tags == nil {
			tags = []any{}
		}
		items = append(items, Entry{ExternalID: ext, Name: truthyStr(entry["name"], id), Description: cut500(entry["description"]),
			Version: strp(truthyStr(entry["version"], "latest")), Spec: spec, Tags: tags, Rank: rankFields(entry)})
	}
	return items
}

// argTokens is _registry_argument_tokens.
func argTokens(arguments any) (tokens, positional []string, ok bool) {
	if arguments == nil {
		return nil, nil, true
	}
	args, isList := arguments.([]any)
	if !isList {
		return nil, nil, false
	}
	for _, a := range args {
		arg, isMap := a.(map[string]any)
		if !isMap {
			return nil, nil, false
		}
		value := arg["value"]
		if value == nil {
			value = arg["default"]
		}
		required := arg["isRequired"]
		if required == nil {
			required = or(arg["required"], false)
		}
		if value == nil {
			if PyTruthy(required) {
				return nil, nil, false
			}
			continue
		}
		var s string
		b, isBool := value.(bool)
		switch t := value.(type) {
		case bool:
			s = strconv.FormatBool(b)
		case string:
			s = t
		case json.Number:
			s = string(t)
		default:
			return nil, nil, false
		}
		if s == "" {
			if PyTruthy(required) {
				return nil, nil, false
			}
			continue
		}
		switch typ := or(arg["type"], "positional"); typ {
		case "positional":
			tokens = append(tokens, s)
			if !strings.HasPrefix(s, "-") {
				positional = append(positional, s)
			}
		case "named":
			name, _ := arg["name"].(string)
			if name == "" {
				return nil, nil, false
			}
			if isBool {
				if s == "true" {
					tokens = append(tokens, name)
				}
			} else {
				tokens = append(tokens, name+"="+s)
			}
		default:
			return nil, nil, false
		}
	}
	return tokens, positional, true
}

// commandPackageArgs is _command_package_args: a pinned command or false.
func commandPackageArgs(pkg map[string]any, registryType, serverVersion string) (string, []any, bool) {
	name, _ := or(pkg["name"], pkg["identifier"]).(string)
	if n, _ := pkg["name"].(string); n == "" {
		name, _ = pkg["identifier"].(string)
	}
	version, _ := pkg["version"].(string)
	if version == "" {
		version = serverVersion
	}
	runtime := sget(pkg, "runtimeHint")
	if runtime == "" {
		runtime = map[string]string{"pypi": "uvx", "npm": "npx", "mcpb": "npx", "nuget": "dotnet"}[registryType]
	}
	if name == "" || version == "" || strings.ToLower(version) == "latest" || !slices.Contains([]string{"uvx", "npx", "bunx"}, runtime) {
		return "", nil, false
	}
	rt, entrypoints, ok := argTokens(or(pkg["runtimeArguments"], []any{}))
	if !ok {
		return "", nil, false
	}
	pt, _, ok := argTokens(or(pkg["packageArguments"], []any{}))
	if !ok || len(entrypoints) > 1 {
		return "", nil, false
	}
	entry := ""
	if len(entrypoints) == 1 {
		entry = entrypoints[0]
		if strings.ContainsAny(entry, "/\\") || entry == "." || entry == ".." {
			return "", nil, false
		}
		rt = slices.DeleteFunc(slices.Clone(rt), func(t string) bool { return t == entry })
	}
	if slices.Contains(rt, "--from") || slices.Contains(rt, "--package") {
		return "", nil, false
	}
	out := func(parts ...[]string) []any {
		var r []any
		for _, p := range parts {
			for _, s := range p {
				r = append(r, s)
			}
		}
		if r == nil {
			r = []any{}
		}
		return r
	}
	if runtime == "uvx" {
		if registryType != "pypi" {
			return "", nil, false
		}
		if entry == "" {
			return runtime, out(rt, []string{name + "@" + version}, pt), true
		}
		return runtime, out(rt, []string{"--from", name + "==" + version, entry}, pt), true
	}
	if registryType != "npm" && registryType != "mcpb" {
		return "", nil, false
	}
	if entry == "" {
		if registryType != "npm" {
			return "", nil, false
		}
		yes := []string{"-y"}
		if slices.Contains(rt, "-y") || slices.Contains(rt, "--yes") {
			yes = nil
		}
		return runtime, out(yes, rt, []string{name + "@" + version}, pt), true
	}
	return runtime, out(rt, []string{"--package", name + "@" + version, entry}, pt), true
}

// humanize is _humanize_identifier.
func humanize(id string) string {
	if i := strings.LastIndex(id, "/"); i >= 0 {
		id = id[i+1:]
	}
	abbrevs := map[string]bool{"mcp": true, "api": true, "ai": true, "db": true, "sql": true, "ssh": true, "aws": true,
		"gcp": true, "cli": true, "sdk": true, "llm": true}
	parts := strings.Fields(strings.NewReplacer("-", " ", "_", " ").Replace(id))
	for i, p := range parts {
		if abbrevs[strings.ToLower(p)] {
			parts[i] = strings.ToUpper(p)
		} else {
			r := []rune(strings.ToLower(p))
			r[0] = []rune(strings.ToUpper(string(r[0])))[0]
			parts[i] = string(r)
		}
	}
	if len(parts) == 0 {
		return id
	}
	return strings.Join(parts, " ")
}

var (
	githubRepoPointer = regexp.MustCompile(`^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$`)
	gitSHA            = regexp.MustCompile(`^[0-9a-f]{40}$`)
)

func skillSource(name string, raw any) (map[string]any, error) {
	if raw == nil {
		return nil, nil
	}
	m, ok := raw.(map[string]any)
	if !ok || m["type"] != "github" {
		return nil, valueErr("skill %s: source must be a mapping with type 'github'", PyRepr(name))
	}
	repo, _ := m["repo"].(string)
	if !githubRepoPointer.MatchString(repo) || slices.ContainsFunc(strings.Split(repo, "/"), func(p string) bool { return p == "." || p == ".." }) {
		return nil, valueErr("skill %s: source.repo must be 'owner/name'", PyRepr(name))
	}
	path := ""
	if p, has := m["path"]; has {
		s, ok := p.(string)
		if !ok {
			return nil, valueErr("skill %s: source.path must be a plain relative path", PyRepr(name))
		}
		path = strings.Trim(s, "/")
	}
	if path != "" && slices.ContainsFunc(strings.Split(path, "/"), func(p string) bool { return p == "" || p == "." || p == ".." }) {
		return nil, valueErr("skill %s: source.path must be a plain relative path", PyRepr(name))
	}
	src := map[string]any{"type": "github", "repo": repo, "path": path}
	for _, k := range []string{"ref", "tree_sha"} {
		v, has := m[k]
		if !has || v == nil {
			continue
		}
		s, ok := v.(string)
		if !ok || !gitSHA.MatchString(s) {
			return nil, valueErr("skill %s: source.%s must be a 40-hex git sha", PyRepr(name), k)
		}
		src[k] = s
	}
	return src, nil
}

func parseSkills(m map[string]any) ([]Entry, error) {
	var items []Entry
	for _, e := range list(m["skills"]) {
		entry := mapping(e)
		name := sget(entry, "name")
		if name == "" {
			continue
		}
		src, err := skillSource(name, entry["source"])
		if err != nil {
			return nil, err
		}
		var spec map[string]any
		var version string
		if src == nil {
			url, _ := entry["source_url"].(string)
			var su any
			if strings.HasPrefix(url, "https://") {
				su = url
			}
			spec = map[string]any{"source_type": or(entry["source_type"], "content"), "content": entry["content"], "source_url": su}
			version = truthyStr(entry["version"], "1.0.0")
		} else {
			folder := ""
			if p := src["path"].(string); p != "" {
				folder = "/" + p
			}
			ref := "HEAD"
			if r, ok := src["ref"].(string); ok {
				ref = r
			}
			spec = map[string]any{"source_type": "github", "source": src,
				"source_url": "https://github.com/" + src["repo"].(string) + "/tree/" + ref + folder}
			version = unpinnedVersion
			if t, ok := src["tree_sha"].(string); ok {
				version = t
			}
			if _, has := entry["provenance"]; !has {
				prov := map[string]any{"repo": src["repo"], "path": src["path"]}
				for _, k := range []string{"stars", "license"} {
					if v, ok := entry[k]; ok {
						prov[k] = v
					}
				}
				entry = copyWith(entry, "provenance", prov)
			}
		}
		if on, ok := entry["original_name"].(string); ok && on != "" {
			spec["original_name"] = on
		}
		if raw, ok := entry["provenance"].(map[string]any); ok {
			prov := map[string]any{}
			for _, k := range []string{"repo", "path", "branch", "stars", "license", "distribution", "source", "duplicate_count"} {
				if v, ok := raw[k]; ok {
					prov[k] = v
				}
			}
			if len(prov) > 0 {
				spec["provenance"] = prov
			}
		}
		items = append(items, Entry{ExternalID: name, Name: name, Description: optStr(entry["description"]), Version: strp(version),
			Spec: spec, Tags: tagsOf(or(entry["tags"], []any{})), Rank: rankFields(entry)})
	}
	return items, nil
}

func copyWith(m map[string]any, k string, v any) map[string]any {
	out := make(map[string]any, len(m)+1)
	for a, b := range m {
		out[a] = b
	}
	out[k] = v
	return out
}

// ProviderContractFields are PROVIDER_CONTRACT_FIELDS.
func ProviderContractFields() []string {
	return []string{"base_url", "transport", "auth", "models_path", "list_shape", "models_query",
		"reasoning_param", "reasoning_efforts", "cache_breakpoints"}
}

func parseProviders(m map[string]any) ([]Entry, error) {
	var items []Entry
	for _, e := range list(m["providers"]) {
		entry := mapping(e)
		key := truthyStr(entry["provider_key"], "")
		if key == "" {
			continue
		}
		fp := or(entry["first_party"], false)
		if _, ok := fp.(bool); !ok {
			return nil, valueErr("Provider %s has first_party %v; expected a bool", PyRepr(key), fp)
		}
		spec := map[string]any{"provider_key": key, "provider_type": or(entry["provider_type"], key), "icon": entry["icon"],
			"is_builtin": or(entry["is_builtin"], true), "first_party": fp}
		for _, f := range ProviderContractFields() {
			if v, ok := entry[f]; ok {
				spec[f] = v
			}
		}
		items = append(items, Entry{ExternalID: key, Name: truthyStr(entry["name"], key), Description: optStr(entry["description"]),
			Version: strp(truthyStr(entry["version"], "1.0.0")), Spec: spec, Tags: tagsOf(or(entry["tags"], []any{}))})
	}
	return items, nil
}

// ModelKinds are ModelKind's values.
func ModelKinds() []string { return []string{"chat", "embedding", "image", "video", "decision"} }

func parseModels(m map[string]any) ([]Entry, error) {
	var items []Entry
	for _, e := range list(m["models"]) {
		entry := mapping(e)
		key, model := truthyStr(entry["provider_key"], ""), truthyStr(entry["model_name"], "")
		if key == "" || model == "" {
			continue
		}
		kind := or(entry["kind"], "chat")
		if k, ok := kind.(string); !ok || !slices.Contains(ModelKinds(), k) {
			return nil, valueErr("Model '%s/%s' has unknown kind %v; expected one of %s", key, model, kind, strings.Join(ModelKinds(), ", "))
		}
		spec := map[string]any{"provider_key": key, "model_name": model, "kind": kind}
		for _, f := range []string{"context_window", "max_output_tokens", "input_cost_per_token", "output_cost_per_token",
			"cached_input_cost_per_token", "cache_creation_input_cost_per_token", "reasoning_efforts"} {
			spec[f] = entry[f]
		}
		for _, f := range []string{"supports_function_calling", "supports_vision", "supports_reasoning"} {
			spec[f] = or(entry[f], false)
		}
		spec["is_active"] = or(entry["is_active"], true)
		items = append(items, Entry{ExternalID: key + "/" + model, Name: truthyStr(entry["display_name"], model),
			Description: optStr(entry["description"]), Version: strp(truthyStr(entry["version"], "1.0.0")), Spec: spec,
			Tags: tagsOf(or(entry["tags"], []any{}))})
	}
	return items, nil
}

func parseAgents(m map[string]any) []Entry {
	var items []Entry
	for _, e := range list(m["agents"]) {
		entry := mapping(e)
		name := truthyStr(entry["name"], "")
		if name == "" {
			continue
		}
		id := entry["id"]
		ext := name
		if PyTruthy(id) {
			ext = fmt.Sprint(id)
		}
		tools, ok := entry["tools"].([]any)
		if !ok {
			tools = []any{}
		}
		preferred := []any{}
		for _, p := range list(entry["preferred_models"]) {
			if s, ok := p.(string); ok && s != "" {
				preferred = append(preferred, s)
			}
		}
		skills := entry["skills"]
		if !PyTruthy(skills) {
			skills = []any{}
		}
		triggers := entry["triggers"]
		if !PyTruthy(triggers) {
			triggers = []any{}
		}
		spec := map[string]any{"id": id, "name": name, "description": entry["description"],
			"instruction": or(entry["instruction"], ""), "preferred_models": preferred, "tools": tools,
			"planning": or(entry["planning"], false), "skills": skills, "triggers": triggers}
		items = append(items, Entry{ExternalID: ext, Name: name, Description: optStr(entry["description"]),
			Version: strp(truthyStr(entry["version"], "1.0.0")), Spec: spec, Tags: tagsOf(or(entry["tags"], []any{})), Rank: rankFields(entry)})
	}
	return items
}

func parseSourceTypes(m map[string]any) ([]Entry, error) {
	var items []Entry
	for _, e := range list(m["source_types"]) {
		entry := mapping(e)
		slug := truthyStr(entry["slug"], "")
		if slug == "" {
			return nil, valueErr("source type entry %v has no slug", entry["name"])
		}
		tags := []any{}
		if PyTruthy(entry["delivery"]) {
			tags = []any{entry["delivery"]}
		}
		items = append(items, Entry{ExternalID: slug, Name: truthyStr(entry["name"], slug), Description: cut500(entry["description"]),
			Version: strp(truthyStr(entry["version"], "1.0.0")), Spec: entry, Tags: tags, Rank: rankFields(entry)})
	}
	return items, nil
}

func parseBundles(m map[string]any) []Entry {
	var items []Entry
	for _, e := range list(m["bundles"]) {
		entry := mapping(e)
		name := truthyStr(entry["name"], "")
		if name == "" {
			continue
		}
		meta := mapping(entry["metadata"])
		tags := entry["tags"]
		if !PyTruthy(tags) {
			tags = meta["capabilities"]
		}
		version := truthyStr(entry["schema_version"], truthyStr(entry["version"], "0.1.0"))
		items = append(items, Entry{ExternalID: name, Name: truthyStr(entry["display_name"], name),
			Description: optStr(entry["description"]), Version: strp(version), Spec: entry, Tags: tagsOf(tags),
			Rank: rankFields(entry, meta)})
	}
	return items
}
