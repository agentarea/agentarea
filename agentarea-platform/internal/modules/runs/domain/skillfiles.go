package domain

import (
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"path"
	"strings"
	"unicode"
)

// SkillsRoot is where a skill's package lands in the task workspace.
const SkillsRoot = "inputs/skills"

// SkillFile is one file of a skill's package, by its path in the package.
type SkillFile struct {
	Path string
	Data []byte
}

// SkillWorkspaceDir is the skill's directory under SkillsRoot, keyed on its
// id; the name's slug only keeps the path readable (skill_workspace_dir).
func SkillWorkspaceDir(name, id string) string {
	var b strings.Builder
	sep := false
	for _, r := range strings.ToLower(name) {
		if unicode.IsLetter(r) || unicode.IsNumber(r) {
			b.WriteRune(r)
			sep = false
		} else if !sep {
			b.WriteByte('-')
			sep = true
		}
	}
	slug := strings.Trim(b.String(), "-")
	sum := sha256.Sum256([]byte(id))
	suffix := hex.EncodeToString(sum[:])[:8]
	if slug == "" {
		return SkillsRoot + "/skill-" + suffix
	}
	return SkillsRoot + "/" + slug + "-" + suffix
}

// SkillWorkspaceFiles lays a package out under the skill's directory, with an
// empty SKILL.md when it has none (assemble_skill_bundle,
// build_skill_workspace_files). One unsafe path refuses the whole package.
func SkillWorkspaceFiles(name, id string, files []SkillFile) ([]SkillFile, error) {
	hasManifest := false
	for _, f := range files {
		if strings.EqualFold(path.Base(f.Path), "SKILL.md") {
			hasManifest = true
			break
		}
	}
	if !hasManifest {
		files = append([]SkillFile{{Path: "SKILL.md", Data: []byte{}}}, files...)
	}
	dir := SkillWorkspaceDir(name, id)
	var out []SkillFile
	at := map[string]int{}
	for _, f := range files {
		clean := strings.ReplaceAll(f.Path, "\\", "/")
		var parts []string
		for _, p := range strings.Split(clean, "/") {
			if p != "" && p != "." {
				parts = append(parts, p)
			}
		}
		if len(parts) == 0 || strings.HasPrefix(clean, "/") || containsDotDot(parts) {
			return nil, fmt.Errorf("skill bundle path escapes workspace: %s", PyStrRepr(f.Path))
		}
		key := dir + "/" + strings.Join(parts, "/")
		if i, ok := at[key]; ok {
			out[i].Data = f.Data
			continue
		}
		at[key] = len(out)
		out = append(out, SkillFile{Path: key, Data: f.Data})
	}
	return out, nil
}

func containsDotDot(parts []string) bool {
	for _, p := range parts {
		if p == ".." {
			return true
		}
	}
	return false
}

// PyStrRepr is Python's repr of a string (without escapes for control characters).
func PyStrRepr(s string) string {
	r := PyListRepr([]string{s})
	return r[1 : len(r)-1]
}
