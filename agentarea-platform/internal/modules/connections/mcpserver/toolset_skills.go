package mcpserver

import (
	"archive/zip"
	"bytes"
	"context"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/url"
	"path"
	"sort"
	"strings"
	"unicode/utf8"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	agentsapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/agents/api"
)

// Limits of skills_toolset.py.
const (
	skillMaxFiles           = 200
	skillMaxInlineBytes     = 5 * 1024 * 1024
	skillMaxPathDepth       = 10
	skillMaxGitHubCandidate = 50
	skillMaxGitHubImports   = 10
	skillMultipleFound      = "Multiple skills found"
)

type skillIDArgs struct {
	SkillID string `json:"skill_id"`
}

func skillSummary(s agentsapi.SkillSummary) map[string]any {
	return map[string]any{"id": s.ID, "name": s.Name, "description": s.Description, "source_type": s.SourceType}
}

func skillNotFound(err error) error {
	if errors.Is(err, agentsapi.ErrSkillNotFound) {
		return &toolError{"Skill not found"}
	}
	return err
}

// orNil is `x or None` for an optional text argument.
func orNil(s string) *string {
	if s == "" {
		return nil
	}
	return &s
}

// skillFiles is _validate_files_payload and _normalize_files over a
// {path: text} map, in the order the caller wrote it.
func skillFiles(raw json.RawMessage) ([]agentsapi.SkillFileText, error) {
	const invalid = "files must be a non-empty {path: text} map"
	dec := json.NewDecoder(bytes.NewReader(raw))
	if tok, err := dec.Token(); err != nil || tok != json.Delim('{') {
		return nil, &toolError{invalid}
	}
	var files []agentsapi.SkillFileText
	total := 0
	for dec.More() {
		tok, err := dec.Token()
		if err != nil {
			return nil, &toolError{invalid}
		}
		p, _ := tok.(string)
		var v any
		if err := dec.Decode(&v); err != nil {
			return nil, &toolError{invalid}
		}
		text, ok := v.(string)
		if !ok {
			return nil, &toolError{fmt.Sprintf("file '%s' value must be a string", p)}
		}
		if strings.Count(p, "/")+1 > skillMaxPathDepth {
			return nil, &toolError{fmt.Sprintf("file '%s' exceeds max path depth %d", p, skillMaxPathDepth)}
		}
		total += len(text)
		if total > skillMaxInlineBytes {
			return nil, &toolError{fmt.Sprintf("Total inline content exceeds %d MB limit. Use create_from_archive for bulk uploads.", skillMaxInlineBytes/(1024*1024))}
		}
		files = append(files, agentsapi.SkillFileText{Path: strings.TrimLeft(p, "/"), Text: text})
	}
	if len(files) == 0 {
		return nil, &toolError{invalid}
	}
	if len(files) > skillMaxFiles {
		return nil, &toolError{fmt.Sprintf("Too many files (%d); limit is %d. Use create_from_archive for bulk.", len(files), skillMaxFiles)}
	}
	return files, nil
}

func isSkillMD(p string) bool {
	l := strings.ToLower(p)
	return l == "skill.md" || l == "skill.markdown"
}

func hasSkillMD(files []agentsapi.SkillFileText) bool {
	for _, f := range files {
		if isSkillMD(f.Path) {
			return true
		}
	}
	return false
}

// skillTools is agentarea_agents/tools/skills_toolset.py.
func skillTools(s agentsapi.Skills) map[string]toolDef {
	return map[string]toolDef{
		"list": {title: "List skills", effect: effectRead, call: func(ctx context.Context, c authn.Caller, _ json.RawMessage) (any, error) {
			skills, err := s.List(ctx, c)
			if err != nil {
				return nil, err
			}
			out := make([]map[string]any, len(skills))
			for i, sk := range skills {
				out[i] = skillSummary(sk)
			}
			return out, nil
		}},
		"get": {title: "Get skill", effect: effectRead, call: func(ctx context.Context, c authn.Caller, args json.RawMessage) (any, error) {
			in, err := decodeArgs[skillIDArgs](args)
			if err != nil {
				return nil, err
			}
			d, err := s.Get(ctx, c, in.SkillID)
			if err != nil {
				return nil, skillNotFound(err)
			}
			out := skillSummary(d.SkillSummary)
			out["source_url"], out["content"] = d.SourceURL, d.Content
			return out, nil
		}},
		"create": {title: "Create skill from files", effect: effectWrite, call: func(ctx context.Context, c authn.Caller, args json.RawMessage) (any, error) {
			in, err := decodeArgs[struct {
				Files       json.RawMessage `json:"files"`
				Name        string          `json:"name"`
				Description string          `json:"description"`
			}](args)
			if err != nil {
				return nil, err
			}
			files, err := skillFiles(in.Files)
			if err != nil {
				return nil, err
			}
			if !hasSkillMD(files) {
				return nil, &toolError{"files must include a SKILL.md at the root"}
			}
			sk, err := s.CreateFromFiles(ctx, c, files, agentsapi.SkillCreate{Name: orNil(in.Name), Description: orNil(in.Description)})
			if err != nil {
				return nil, err
			}
			out := skillSummary(sk)
			out["file_count"] = len(files)
			return out, nil
		}},
		"create_from_archive": {title: "Create skill from archive", effect: effectWrite, call: func(ctx context.Context, c authn.Caller, args json.RawMessage) (any, error) {
			in, err := decodeArgs[struct {
				ZipBase64   string `json:"zip_base64"`
				Name        string `json:"name"`
				Description string `json:"description"`
			}](args)
			if err != nil {
				return nil, err
			}
			archive, err := base64.StdEncoding.Strict().DecodeString(in.ZipBase64)
			if err != nil {
				return nil, &toolError{"Invalid base64: " + err.Error()}
			}
			sk, err := s.CreateFromArchive(ctx, c, archive, agentsapi.SkillCreate{Name: orNil(in.Name), Description: orNil(in.Description)})
			if err != nil {
				return nil, err
			}
			return skillSummary(sk), nil
		}},
		"import_from_github": {title: "Import skill from GitHub", effect: effectWrite, openWorld: true, call: func(ctx context.Context, c authn.Caller, args json.RawMessage) (any, error) {
			in, err := decodeArgs[githubImport](args)
			if err != nil {
				return nil, err
			}
			return in.run(ctx, c, s)
		}},
		"edit_metadata": {title: "Edit skill metadata", effect: effectWrite, call: func(ctx context.Context, c authn.Caller, args json.RawMessage) (any, error) {
			in, err := decodeArgs[struct {
				SkillID     string `json:"skill_id"`
				Name        string `json:"name"`
				Description string `json:"description"`
			}](args)
			if err != nil {
				return nil, err
			}
			sk, err := s.EditMetadata(ctx, c, in.SkillID, orNil(in.Name), orNil(in.Description))
			if err != nil {
				return nil, skillNotFound(err)
			}
			return map[string]any{"id": sk.ID, "name": sk.Name, "description": sk.Description}, nil
		}},
		"edit_content": {title: "Edit skill files", effect: effectWrite, idempotent: true, call: func(ctx context.Context, c authn.Caller, args json.RawMessage) (any, error) {
			in, err := decodeArgs[struct {
				SkillID string          `json:"skill_id"`
				Files   json.RawMessage `json:"files"`
			}](args)
			if err != nil {
				return nil, err
			}
			files, err := skillFiles(in.Files)
			if err != nil {
				return nil, err
			}
			current, err := s.Get(ctx, c, in.SkillID)
			if err != nil {
				return nil, skillNotFound(err)
			}
			if current.Package == "" {
				if len(files) != 1 || !isSkillMD(files[0].Path) {
					return nil, &toolError{"Skill is content-mode (single SKILL.md only). Multi-file edits are not supported. To migrate to a package, delete this skill and re-create with create()."}
				}
				sk, err := s.SetContent(ctx, c, in.SkillID, files[0].Text)
				if err != nil {
					return nil, skillNotFound(err)
				}
				return map[string]any{"id": sk.ID, "mode": "content", "files_written": []string{"SKILL.md"}}, nil
			}
			if !hasSkillMD(files) {
				return nil, &toolError{"files must include a SKILL.md at the root"}
			}
			sk, err := s.ReplaceFiles(ctx, c, in.SkillID, files)
			if err != nil {
				return nil, skillNotFound(err)
			}
			written := make([]string, len(files))
			for i, f := range files {
				written[i] = f.Path
			}
			sort.Strings(written)
			return map[string]any{"id": sk.ID, "mode": "package", "files_written": written}, nil
		}},
		"delete": {title: "Delete skill", effect: effectDestructive, idempotent: true, call: func(ctx context.Context, c authn.Caller, args json.RawMessage) (any, error) {
			in, err := decodeArgs[skillIDArgs](args)
			if err != nil {
				return nil, err
			}
			deleted, err := s.Delete(ctx, c, in.SkillID)
			if err != nil {
				return nil, err
			}
			return map[string]any{"deleted": deleted}, nil
		}},
		"list_files": {title: "List skill files", effect: effectRead, call: func(ctx context.Context, c authn.Caller, args json.RawMessage) (any, error) {
			in, err := decodeArgs[struct {
				SkillID     string `json:"skill_id"`
				IncludeURLs bool   `json:"include_urls"`
			}](args)
			if err != nil {
				return nil, err
			}
			files, err := s.ListFiles(ctx, c, in.SkillID, in.IncludeURLs)
			if err != nil {
				return nil, skillNotFound(err)
			}
			out := make([]map[string]any, len(files))
			for i, f := range files {
				out[i] = map[string]any{"path": f.Path, "size": f.Size}
				if f.URL != nil && *f.URL != "" {
					out[i]["url"] = *f.URL
				}
			}
			return out, nil
		}},
		"get_file": {title: "Read skill file", effect: effectRead, call: func(ctx context.Context, c authn.Caller, args json.RawMessage) (any, error) {
			in, err := decodeArgs[struct {
				SkillID   string `json:"skill_id"`
				Path      string `json:"path"`
				AsURL     bool   `json:"as_url"`
				ExpiresIn *int   `json:"expires_in"`
			}](args)
			if err != nil {
				return nil, err
			}
			if in.AsURL {
				expires := 3600
				if in.ExpiresIn != nil {
					expires = *in.ExpiresIn
				}
				expires = max(minURLExpiresIn, min(expires, maxURLExpiresIn))
				u, err := s.FileURL(ctx, c, in.SkillID, in.Path, expires)
				if err != nil {
					return nil, skillNotFound(err)
				}
				return map[string]any{"url": u, "path": in.Path, "expires_in": expires}, nil
			}
			raw, err := s.FileContent(ctx, c, in.SkillID, in.Path)
			if err != nil {
				return nil, skillNotFound(err)
			}
			if !utf8.Valid(raw) {
				msg, err := json.Marshal(map[string]any{"error": "binary file; retry with as_url=true", "size": len(raw)})
				if err != nil {
					return nil, err
				}
				return nil, &toolError{string(msg)}
			}
			return map[string]any{"path": in.Path, "content": string(raw)}, nil
		}},
	}
}

// githubImport is import_from_github's arguments.
type githubImport struct {
	GitHubURL   string `json:"github_url"`
	Name        string `json:"name"`
	Description string `json:"description"`
	SkillName   string `json:"skill_name"`
	ImportAll   bool   `json:"import_all"`
}

// skillCandidate is one SKILL.md of the repository in the URL's scope.
type skillCandidate struct {
	Name        *string `json:"name"`
	Description *string `json:"description"`
	Error       string  `json:"error,omitempty"`
	SkillPath   string  `json:"skill_path"`
	PackagePath string  `json:"package_path"`
	RawURL      string  `json:"raw_url"`
}

// githubRepo is parse_github_url: owner, repository, the branch and the
// path a tree or blob URL names.
type githubRepo struct{ owner, repo, branch, path string }

func parseGitHubURL(raw string) (githubRepo, error) {
	u, err := url.Parse(strings.TrimSpace(raw))
	if err != nil {
		return githubRepo{}, importErrorf("Invalid URL: %s", raw)
	}
	if u.Host != "github.com" && u.Host != "www.github.com" {
		return githubRepo{}, importErrorf("Not a GitHub URL: %s", raw)
	}
	parts := strings.Split(strings.Trim(u.Path, "/"), "/")
	if len(parts) < 2 {
		return githubRepo{}, importErrorf("Invalid GitHub repository URL: %s", raw)
	}
	r := githubRepo{owner: parts[0], repo: strings.TrimSuffix(parts[1], ".git")}
	if len(parts) >= 4 && (parts[2] == "tree" || parts[2] == "blob") {
		r.branch = parts[3]
		r.path = strings.Join(parts[4:], "/")
	}
	return r, nil
}

// importError is the ToolError import_from_github raises for a ValueError.
func importError(msg string, candidates []skillCandidate) error {
	payload := map[string]any{"error": msg}
	if msg == skillMultipleFound {
		payload["code"] = "multiple_skills_found"
		payload["candidates"] = candidates
		payload["hint"] = "Call import_from_github again with skill_name, a more specific GitHub tree URL, or import_all=true."
	}
	raw, err := json.Marshal(payload)
	if err != nil {
		return err
	}
	return &toolError{string(raw)}
}

func (in githubImport) run(ctx context.Context, c authn.Caller, s agentsapi.Skills) (any, error) {
	repo, err := parseGitHubURL(in.GitHubURL)
	if err != nil {
		return nil, &toolError{err.Error()}
	}
	repoZip, err := s.DownloadGitHubRepo(ctx, c, in.GitHubURL)
	if err != nil {
		return nil, err
	}
	candidates, err := githubCandidates(repoZip, repo, in.GitHubURL)
	if err != nil {
		return nil, importError(err.Error(), nil)
	}
	selector := in.SkillName
	if selector == "" {
		selector = in.Name
	}
	selected, err := selectCandidates(candidates, selector, in.ImportAll)
	if err != nil {
		return nil, importError(err.Error(), candidates)
	}
	if len(selected) > skillMaxGitHubImports {
		return nil, &toolError{fmt.Sprintf("Refusing to import %d GitHub skill packages; limit is %d. Use a more specific tree URL.", len(selected), skillMaxGitHubImports)}
	}
	var created []map[string]any
	for _, cand := range selected {
		pkg, err := s.ExtractGitHubPackage(repoZip, cand.PackagePath)
		if err != nil {
			return nil, &toolError{err.Error()}
		}
		create := agentsapi.SkillCreate{SourceURL: &in.GitHubURL}
		if len(selected) == 1 {
			create.Name, create.Description = orNil(in.Name), orNil(in.Description)
		}
		sk, err := s.CreateFromArchive(ctx, c, pkg, create)
		if err != nil {
			return nil, err
		}
		out := skillSummary(sk)
		out["source_url"], out["resolved_source_url"], out["package_path"] = in.GitHubURL, cand.RawURL, cand.PackagePath
		created = append(created, out)
	}
	if len(created) == 1 {
		return created[0], nil
	}
	return map[string]any{"created": created, "count": len(created)}, nil
}

// githubCandidates is _list_github_skill_candidates over the downloaded
// zipball instead of the GitHub tree API: the SKILL.md files in the URL's
// scope, the root one first. The raw URLs name the branch the URL gave,
// else the commit the zipball holds.
func githubCandidates(repoZip []byte, repo githubRepo, githubURL string) ([]skillCandidate, error) {
	zr, err := zip.NewReader(bytes.NewReader(repoZip), int64(len(repoZip)))
	if err != nil {
		return nil, err
	}
	ref := repo.branch
	files := map[string]*zip.File{}
	var all []string
	for _, f := range zr.File {
		root, rel, ok := strings.Cut(f.Name, "/")
		if !ok || rel == "" || f.FileInfo().IsDir() {
			continue
		}
		if ref == "" {
			if i := strings.LastIndex(root, "-"); i >= 0 {
				ref = root[i+1:]
			}
		}
		if strings.HasSuffix(strings.ToLower(rel), "skill.md") {
			all = append(all, rel)
			files[rel] = f
		}
	}
	scope := strings.Trim(repo.path, "/")
	var paths []string
	switch {
	case scope != "" && strings.HasSuffix(strings.ToLower(scope), "skill.md"):
		for _, p := range all {
			if p == scope {
				paths = append(paths, p)
			}
		}
	case scope != "":
		exact := scope + "/SKILL.md"
		if files[exact] != nil {
			paths = []string{exact}
		} else {
			for _, p := range all {
				if strings.HasPrefix(p, scope+"/") {
					paths = append(paths, p)
				}
			}
		}
	default:
		paths = all
	}
	if len(paths) == 0 {
		return nil, importErrorf("No SKILL.md found in GitHub repository: %s", githubURL)
	}
	if len(paths) > skillMaxGitHubCandidate {
		return nil, importErrorf("Repository contains %d SKILL.md candidates; limit is %d. Use a more specific tree URL.", len(paths), skillMaxGitHubCandidate)
	}
	sort.Slice(paths, func(i, j int) bool {
		ri, rj := strings.EqualFold(paths[i], "skill.md"), strings.EqualFold(paths[j], "skill.md")
		if ri != rj {
			return ri
		}
		return paths[i] < paths[j]
	})
	out := make([]skillCandidate, 0, len(paths))
	for _, p := range paths {
		content, err := readZipFile(files[p])
		if err != nil {
			return nil, err
		}
		cand := skillFrontmatter(content)
		pkg := path.Dir(p)
		if pkg == "." {
			pkg = ""
		}
		cand.SkillPath, cand.PackagePath = p, pkg
		cand.RawURL = "https://raw.githubusercontent.com/" + repo.owner + "/" + repo.repo + "/" + ref + "/" + p
		out = append(out, cand)
	}
	return out, nil
}

func readZipFile(f *zip.File) (string, error) {
	rc, err := f.Open()
	if err != nil {
		return "", err
	}
	defer func() { _ = rc.Close() }()
	raw, err := io.ReadAll(io.LimitReader(rc, skillMaxInlineBytes))
	return string(raw), err
}

// skillFrontmatter is _candidate_frontmatter: the name and description the
// YAML frontmatter's top-level scalars give, or why there is none.
func skillFrontmatter(content string) skillCandidate {
	content = strings.TrimPrefix(content, "\uFEFF")
	body, ok := strings.CutPrefix(strings.ReplaceAll(content, "\r\n", "\n"), "---\n")
	if !ok {
		return skillCandidate{Error: "SKILL.md has no YAML frontmatter"}
	}
	block, _, ok := strings.Cut(body, "\n---")
	if !ok {
		return skillCandidate{Error: "SKILL.md frontmatter is not closed"}
	}
	var cand skillCandidate
	for _, line := range strings.Split(block, "\n") {
		key, value, ok := strings.Cut(line, ":")
		if !ok || strings.HasPrefix(line, " ") || strings.HasPrefix(line, "\t") {
			continue
		}
		v := strings.TrimSpace(value)
		if len(v) >= 2 && (v[0] == '"' || v[0] == '\'') && v[len(v)-1] == v[0] {
			v = v[1 : len(v)-1]
		}
		switch strings.TrimSpace(key) {
		case "name":
			cand.Name = &v
		case "description":
			cand.Description = &v
		}
	}
	return cand
}

// selectCandidates is _select_github_candidates.
func selectCandidates(candidates []skillCandidate, selector string, importAll bool) ([]skillCandidate, error) {
	if importAll {
		return candidates, nil
	}
	if selector != "" {
		wanted := strings.ToLower(strings.TrimSpace(selector))
		var matches []skillCandidate
		for _, cand := range candidates {
			name := ""
			if cand.Name != nil {
				name = strings.ToLower(*cand.Name)
			}
			pkg := strings.ToLower(cand.PackagePath)
			if name == wanted || strings.HasSuffix(pkg, "/"+wanted) || pkg == wanted {
				matches = append(matches, cand)
			}
		}
		switch len(matches) {
		case 0:
			return nil, importErrorf("No SKILL.md with name or path '%s' found", selector)
		case 1:
			return matches, nil
		}
		return nil, importErrorf("Multiple skills match '%s'; use a more specific path", selector)
	}
	if len(candidates) == 1 {
		return candidates, nil
	}
	return nil, &toolError{skillMultipleFound}
}

// importErrorf is a refusal whose text is Python's ValueError message.
func importErrorf(format string, a ...any) error { return &toolError{fmt.Sprintf(format, a...)} }
