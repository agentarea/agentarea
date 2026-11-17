package service

import (
	"context"
	"fmt"
	"path"
	"regexp"
	"sort"
	"strings"
)

const (
	skillFile                = "SKILL.md"
	frontmatterMaxNodes      = 2000
	frontmatterMaxBytes      = 64 * 1024
	maxWorkspaceGitHubSkills = 200
)

var (
	frontmatter = regexp.MustCompile(`(?s)\A---\s*\n(.*?)\n---\s*(?:\n|\z)`)
)

// skillFrontmatter is skill_frontmatter: {} when absent or unreadable.
func skillFrontmatter(content string) map[string]any {
	m := frontmatter.FindStringSubmatch(content)
	if m == nil || len(m[1]) > frontmatterMaxBytes {
		return map[string]any{}
	}
	v, err := loadYAML([]byte(m[1]), frontmatterMaxNodes)
	if err != nil {
		return map[string]any{}
	}
	if out, ok := v.(map[string]any); ok {
		return out
	}
	return map[string]any{}
}

// IndexError is GitHubTreeTruncatedError / GitHubIndexTooLargeError.
type IndexError struct{ Msg string }

func (e *IndexError) Error() string { return e.Msg }

// BuildGitHubSkillIndex is build_github_skill_index: one item per SKILL.md
// folder of repo at commit under folderPath.
func BuildGitHubSkillIndex(ctx context.Context, src GitHubSource, repo, commit string, folderPath *string, maxSkills int) ([]Entry, error) {
	entries, root, truncated, err := src.Tree(ctx, repo, commit)
	if err != nil {
		return nil, err
	}
	if truncated {
		return nil, &IndexError{Msg: fmt.Sprintf("GitHub truncated the tree of %s at %s; set a path to a smaller folder", repo, commit)}
	}
	prefix := ""
	if folderPath != nil {
		prefix = strings.Trim(*folderPath, "/")
	}
	trees := map[string]string{}
	var files []TreeEntry
	for _, e := range entries {
		if e.Type == "tree" {
			trees[e.Path] = e.SHA
		}
	}
	for _, e := range entries {
		dir := path.Dir(e.Path)
		if dir == "." {
			dir = ""
		}
		if e.Type == "blob" && path.Base(e.Path) == skillFile &&
			(prefix == "" || dir == prefix || strings.HasPrefix(dir, prefix+"/")) {
			files = append(files, e)
		}
	}
	sort.Slice(files, func(i, j int) bool { return files[i].Path < files[j].Path })
	if maxSkills > 0 && len(files) > maxSkills {
		return nil, &IndexError{Msg: fmt.Sprintf("%s holds more than %d skills; set a path to a smaller folder", repo, maxSkills)}
	}
	out := make([]Entry, 0, len(files))
	for i, f := range files {
		body, err := src.Raw(ctx, repo, commit, f.Path)
		if err != nil {
			return nil, err
		}
		meta := skillFrontmatter(strings.ToValidUTF8(string(body), "�"))
		folder := path.Dir(f.Path)
		if folder == "." {
			folder = ""
		}
		tree := root
		if folder != "" {
			tree = trees[folder]
		}
		name, _ := meta["name"].(string)
		if name == "" {
			name = path.Base(folder)
			if folder == "" {
				name = repo[strings.LastIndex(repo, "/")+1:]
			}
		}
		var desc *string
		if d, ok := meta["description"].(string); ok {
			desc = &d
		}
		ext := folder
		if ext == "" {
			ext = name
		}
		rank := i
		out = append(out, Entry{ExternalID: ext, Name: name, Description: desc, Version: strp(tree), Tags: []any{}, Rank: &rank,
			Spec: map[string]any{
				"source_type": "github",
				"source_url":  strings.TrimRight("https://github.com/"+repo+"/tree/"+commit+"/"+folder, "/"),
				"source":      map[string]any{"type": "github", "repo": repo, "path": folder, "ref": commit, "tree_sha": tree},
			}})
	}
	return out, nil
}
