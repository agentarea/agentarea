package domain

import (
	"crypto/sha256"
	"encoding/binary"
	"encoding/hex"
	"fmt"
	"mime"
	"slices"
	"sort"
	"strings"
	"unicode"
)

// Package limits every skill package write and read goes through (skill_package_limits.py).
const (
	SkillMaxPackageFiles      = 1000
	SkillMaxPackageFileBytes  = 10 * 1024 * 1024
	SkillMaxPackageTotalBytes = 50 * 1024 * 1024
	SkillMaxNameLength        = 255
	SkillManifest             = "SKILL.md"
	SkillsPrefix              = "skills"
	skillCatalogArea          = "catalog"
	skillPackagesArea         = "packages"
)

// SkillValueError is a ValueError the skill code raises; its text is the detail.
type SkillValueError struct{ Msg string }

func (e *SkillValueError) Error() string { return e.Msg }

func skillValueErrorf(format string, a ...any) error {
	return &SkillValueError{Msg: fmt.Sprintf(format, a...)}
}

// SkillFile is one file of a package; a package keeps its files in insertion order.
type SkillFile struct {
	Path string
	Data []byte
}

// SkillFiles is a package's files by path, in the order they were added.
type SkillFiles []SkillFile

// Set is files[path] = data: a known path keeps its place.
func (f *SkillFiles) Set(path string, data []byte) {
	for i := range *f {
		if (*f)[i].Path == path {
			(*f)[i].Data = data
			return
		}
	}
	*f = append(*f, SkillFile{Path: path, Data: data})
}

// Get is files.get(path).
func (f SkillFiles) Get(path string) ([]byte, bool) {
	for _, x := range f {
		if x.Path == path {
			return x.Data, true
		}
	}
	return nil, false
}

// Paths is list(files).
func (f SkillFiles) Paths() []string {
	out := make([]string, len(f))
	for i, x := range f {
		out[i] = x.Path
	}
	return out
}

// SkillRepr is Python's repr of a str.
func SkillRepr(s string) string {
	quote := '\''
	if strings.ContainsRune(s, '\'') && !strings.ContainsRune(s, '"') {
		quote = '"'
	}
	var b strings.Builder
	b.WriteRune(quote)
	for _, r := range s {
		switch {
		case r == '\\':
			b.WriteString(`\\`)
		case r == quote:
			b.WriteByte('\\')
			b.WriteRune(r)
		case r == '\n':
			b.WriteString(`\n`)
		case r == '\r':
			b.WriteString(`\r`)
		case r == '\t':
			b.WriteString(`\t`)
		case r < 0x20 || r == 0x7f:
			fmt.Fprintf(&b, `\x%02x`, r)
		case r >= 0x80 && r <= 0xa0:
			fmt.Fprintf(&b, `\x%02x`, r)
		case !unicode.IsPrint(r) && r > 0xa0:
			if r > 0xffff {
				fmt.Fprintf(&b, `\U%08x`, r)
			} else {
				fmt.Fprintf(&b, `\u%04x`, r)
			}
		default:
			b.WriteRune(r)
		}
	}
	b.WriteRune(quote)
	return b.String()
}

// SkillPyStrip is str.strip().
func SkillPyStrip(s string) string {
	return strings.TrimFunc(s, skillPySpace)
}

func skillPySpace(r rune) bool {
	return unicode.IsSpace(r) || (r >= 0x1c && r <= 0x1f)
}

// SkillSafePath is safe_package_path: a plain relative package path, else a ValueError.
func SkillSafePath(path string) (string, error) {
	path = strings.TrimLeft(path, "/")
	if path == "" || strings.ContainsAny(path, "\\\x00") {
		return "", skillValueErrorf("Invalid skill file path: %s", SkillRepr(path))
	}
	for _, part := range strings.Split(path, "/") {
		if part == "" || part == "." || part == ".." {
			return "", skillValueErrorf("Invalid skill file path: %s", SkillRepr(path))
		}
	}
	return path, nil
}

func skillTooLarge(path string) error {
	return skillValueErrorf("Skill package file %s is larger than %d MB", SkillRepr(path), SkillMaxPackageFileBytes/(1024*1024))
}

func skillTooManyFiles() error {
	return skillValueErrorf("Skill package contains more than %d files", SkillMaxPackageFiles)
}

func skillTotalTooLarge() error {
	return skillValueErrorf("Skill package is larger than %d MB uncompressed", SkillMaxPackageTotalBytes/(1024*1024))
}

// SkillCheckedFiles is checked_package_files: every path normalised, or a ValueError for the whole set.
func SkillCheckedFiles(files SkillFiles) (SkillFiles, error) {
	if len(files) > SkillMaxPackageFiles {
		return nil, skillTooManyFiles()
	}
	var checked SkillFiles
	total := 0
	for _, f := range files {
		if len(f.Data) > SkillMaxPackageFileBytes {
			return nil, skillTooLarge(f.Path)
		}
		total += len(f.Data)
		p, err := SkillSafePath(f.Path)
		if err != nil {
			return nil, err
		}
		checked.Set(p, f.Data)
	}
	if total > SkillMaxPackageTotalBytes {
		return nil, skillTotalTooLarge()
	}
	return checked, nil
}

// SkillDigest is package_digest: sha256 over the sorted (path, bytes) pairs, each length-prefixed.
func SkillDigest(files SkillFiles) string {
	sorted := append(SkillFiles(nil), files...)
	sort.SliceStable(sorted, func(i, j int) bool { return sorted[i].Path < sorted[j].Path })
	h := sha256.New()
	var n [8]byte
	for _, f := range sorted {
		for _, part := range [][]byte{[]byte(f.Path), f.Data} {
			binary.BigEndian.PutUint64(n[:], uint64(len(part)))
			h.Write(n[:])
			h.Write(part)
		}
	}
	return hex.EncodeToString(h.Sum(nil))
}

// SkillWorkspacePackageArea is where a workspace's own immutable packages live.
func SkillWorkspacePackageArea(workspaceID string) string {
	return SkillsPrefix + "/" + workspaceID + "/" + skillPackagesArea
}

// SkillOwnCopyPrefix is tenant_package_prefix: the mutable pre-package copy of a skill.
func SkillOwnCopyPrefix(workspaceID, skillID string) string {
	return SkillsPrefix + "/" + workspaceID + "/" + skillID + "/"
}

// SkillIsCatalogPackage is is_catalog_package.
func SkillIsCatalogPackage(s3Path string) bool {
	parts := strings.Split(s3Path, "/")
	return len(parts) > 2 && parts[0] == SkillsPrefix && (parts[1] == skillCatalogArea || parts[2] == skillCatalogArea)
}

// SkillIsWorkspacePackage is is_workspace_package.
func SkillIsWorkspacePackage(s3Path string) bool {
	parts := strings.Split(s3Path, "/")
	return len(parts) > 3 && parts[0] == SkillsPrefix && parts[2] == skillPackagesArea
}

// SkillIsImmutablePackage is is_immutable_package.
func SkillIsImmutablePackage(s3Path string) bool {
	return SkillIsCatalogPackage(s3Path) || SkillIsWorkspacePackage(s3Path)
}

// SkillPackageDigestOf is package_digest_of; nil for a mutable path.
func SkillPackageDigestOf(s3Path *string) *string {
	if s3Path == nil || !SkillIsImmutablePackage(*s3Path) {
		return nil
	}
	p := strings.TrimRight(*s3Path, "/")
	d := p[strings.LastIndex(p, "/")+1:]
	return &d
}

// SkillContentType is _guess_content_type.
func SkillContentType(path string) string {
	ext := ""
	if i := strings.LastIndex(path, "."); i >= 0 {
		ext = strings.ToLower(path[i+1:])
	}
	switch ext {
	case "md":
		return "text/markdown"
	case "yaml", "yml":
		return "application/yaml"
	case "json":
		return "application/json"
	case "txt":
		return "text/plain"
	}
	if ext != "" && !strings.Contains(path[strings.LastIndex(path, "/")+1:], ".") {
		ext = ""
	}
	if ext != "" {
		if t := mime.TypeByExtension("." + ext); t != "" {
			if media, _, err := mime.ParseMediaType(t); err == nil {
				return media
			}
			return t
		}
	}
	return "application/octet-stream"
}

// SkillMainFile is find_main_skill_file: the first root-level SKILL.md, case-insensitively.
func SkillMainFile(paths []string) (string, bool) {
	for _, p := range paths {
		n := strings.ReplaceAll(p, "\\", "/")
		if strings.Contains(strings.Trim(n, "/"), "/") {
			continue
		}
		if strings.ToLower(n) == "skill.md" {
			return n, true
		}
	}
	return "", false
}

// SkillCheckedName is _checked_skill_name.
func SkillCheckedName(name string) (string, error) {
	if SkillPyStrip(name) == "" {
		return "", &SkillValueError{Msg: "Skill name cannot be empty"}
	}
	if n := len([]rune(name)); n > SkillMaxNameLength {
		return "", skillValueErrorf("Skill name is %d characters; the limit is %d. "+
			"Shorten the 'name' in the SKILL.md frontmatter (or its first heading), or pass a shorter name.", n, SkillMaxNameLength)
	}
	return name, nil
}

// SkillCatalogArea is catalog_area: the platform registries' shared area, or a
// workspace registry's own.
func SkillCatalogArea(registryWorkspaceID *string) string {
	if registryWorkspaceID == nil {
		return SkillsPrefix + "/" + skillCatalogArea
	}
	return SkillsPrefix + "/" + *registryWorkspaceID + "/" + skillCatalogArea
}

// SkillLegacyCatalogPath is legacy_catalog_s3_path: a catalog item's legacy
// s3_path when it lies where its registry stores, else "".
func SkillLegacyCatalogPath(path string, registryWorkspaceID *string, platformWorkspace string) string {
	if path == "" || slices.Contains(strings.Split(path, "/"), "..") || strings.Contains(path, "\\") {
		return ""
	}
	areas := []string{SkillCatalogArea(nil) + "/", SkillsPrefix + "/" + platformWorkspace + "/"}
	if registryWorkspaceID != nil {
		areas = []string{SkillsPrefix + "/" + *registryWorkspaceID + "/"}
	}
	for _, a := range areas {
		if strings.HasPrefix(path, a) {
			return path
		}
	}
	return ""
}
