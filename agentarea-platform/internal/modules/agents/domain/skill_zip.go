package domain

import (
	"archive/zip"
	"bytes"
	"fmt"
	"io"
	"net/url"
	"path"
	"regexp"
	"strings"
	"unicode/utf8"
)

// SkillNotAZip and SkillMissingManifest are the parser's two package refusals.
const (
	SkillNotAZip         = "Skill package is not a valid ZIP archive"
	SkillMissingManifest = "No SKILL.md found at package root. Skills must include a SKILL.md file."
	// SkillMaxRepoZipBytes is MAX_GITHUB_REPO_ZIP_BYTES.
	SkillMaxRepoZipBytes = 25 * 1024 * 1024
)

func skillOpenZip(data []byte) (*zip.Reader, error) {
	zr, err := zip.NewReader(bytes.NewReader(data), int64(len(data)))
	if err != nil {
		return nil, &SkillValueError{Msg: SkillNotAZip}
	}
	return zr, nil
}

func skillIsDir(f *zip.File) bool { return strings.HasSuffix(f.Name, "/") }

// skillZipBudget is check_zip_budget: the declared sizes against the package limits.
func skillZipBudget(zr *zip.Reader) error {
	var files []*zip.File
	for _, f := range zr.File {
		if !skillIsDir(f) {
			files = append(files, f)
		}
	}
	if len(files) > SkillMaxPackageFiles {
		return skillTooManyFiles()
	}
	var total uint64
	for _, f := range files {
		if f.UncompressedSize64 > SkillMaxPackageFileBytes {
			return skillTooLarge(f.Name)
		}
		total += f.UncompressedSize64
	}
	if total > SkillMaxPackageTotalBytes {
		return skillTotalTooLarge()
	}
	return nil
}

// skillReadEntry is read_entry: one entry, refused when it inflates past the per-file cap.
func skillReadEntry(f *zip.File) ([]byte, error) {
	rc, err := f.Open()
	if err != nil {
		return nil, &SkillValueError{Msg: SkillNotAZip}
	}
	defer func() { _ = rc.Close() }()
	data, err := io.ReadAll(io.LimitReader(rc, SkillMaxPackageFileBytes+1))
	if err != nil {
		return nil, &SkillValueError{Msg: SkillNotAZip}
	}
	if len(data) > SkillMaxPackageFileBytes {
		return nil, skillTooLarge(f.Name)
	}
	return data, nil
}

// skillStorageRoot is SkillStorageService._detect_root_folder.
func skillStorageRoot(names []string) string {
	first := map[string]bool{}
	seen := false
	for _, n := range names {
		if strings.HasSuffix(n, "/") || strings.HasPrefix(n, "__MACOSX") {
			continue
		}
		seen = true
		parts := strings.Split(n, "/")
		if len(parts) == 1 {
			return ""
		}
		first[parts[0]] = true
	}
	if !seen || len(first) != 1 {
		return ""
	}
	for k := range first {
		return k + "/"
	}
	return ""
}

// skillParserRoot is SkillParser._normalize_zip_path's root: top-level files do not count.
func skillParserRoot(names []string) string {
	first := map[string]bool{}
	for _, n := range names {
		if strings.HasSuffix(n, "/") || strings.HasPrefix(n, "__MACOSX") {
			continue
		}
		if parts := strings.Split(n, "/"); len(parts) > 1 {
			first[parts[0]] = true
		}
	}
	if len(first) != 1 {
		return ""
	}
	for k := range first {
		return k + "/"
	}
	return ""
}

func skillNames(zr *zip.Reader) []string {
	out := make([]string, len(zr.File))
	for i, f := range zr.File {
		out[i] = f.Name
	}
	return out
}

// SkillFilesFromZip is files_from_zip: the package a ZIP upload holds; budget and paths checked first.
func SkillFilesFromZip(data []byte) (SkillFiles, error) {
	zr, err := skillOpenZip(data)
	if err != nil {
		return nil, err
	}
	if err := skillZipBudget(zr); err != nil {
		return nil, err
	}
	root := skillStorageRoot(skillNames(zr))
	type entry struct {
		f    *zip.File
		path string
	}
	var entries []entry
	for _, f := range zr.File {
		if skillIsDir(f) || strings.HasPrefix(f.Name, "__MACOSX") || strings.Contains(f.Name, "/.") || strings.HasPrefix(f.Name, ".") {
			continue
		}
		rel := f.Name
		if root != "" && strings.HasPrefix(rel, root) {
			rel = rel[len(root):]
		}
		if rel == "" {
			continue
		}
		p, err := SkillSafePath(rel)
		if err != nil {
			return nil, err
		}
		entries = append(entries, entry{f, p})
	}
	var files SkillFiles
	for _, e := range entries {
		b, err := skillReadEntry(e.f)
		if err != nil {
			return nil, err
		}
		files.Set(e.path, b)
	}
	return files, nil
}

// SkillMainFromZip is extract_main_skill_from_zip: the root SKILL.md's text.
func SkillMainFromZip(data []byte) (string, error) {
	zr, err := skillOpenZip(data)
	if err != nil {
		return "", err
	}
	if err := skillZipBudget(zr); err != nil {
		return "", err
	}
	names := skillNames(zr)
	root := skillParserRoot(names)
	var paths []string
	for _, f := range zr.File {
		if skillIsDir(f) || strings.HasPrefix(f.Name, "__MACOSX") || strings.Contains(f.Name, "/.") {
			continue
		}
		p := f.Name
		if root != "" && strings.HasPrefix(p, root) {
			p = p[len(root):]
		}
		if p != "" {
			paths = append(paths, p)
		}
	}
	main, ok := SkillMainFile(paths)
	if !ok {
		return "", &SkillValueError{Msg: SkillMissingManifest}
	}
	actual := ""
	for _, n := range names {
		if n == main {
			actual = n
			break
		}
	}
	if actual == "" && root != "" {
		for _, n := range names {
			if n == root+main {
				actual = n
				break
			}
		}
	}
	if actual == "" {
		return "", skillValueErrorf("Could not find %s in ZIP", main)
	}
	for _, f := range zr.File {
		if f.Name != actual {
			continue
		}
		rc, err := f.Open()
		if err != nil {
			return "", &SkillValueError{Msg: SkillNotAZip}
		}
		raw, err := io.ReadAll(rc)
		_ = rc.Close()
		if err != nil {
			return "", &SkillValueError{Msg: SkillNotAZip}
		}
		return SkillDecodeUTF8(raw)
	}
	return "", skillValueErrorf("Could not find %s in ZIP", main)
}

// SkillDecodeUTF8 is bytes.decode("utf-8"), its UnicodeDecodeError a ValueError.
func SkillDecodeUTF8(raw []byte) (string, error) {
	for i := 0; i < len(raw); {
		r, size := utf8.DecodeRune(raw[i:])
		if r == utf8.RuneError && size <= 1 {
			reason := "invalid start byte"
			if raw[i] >= 0xc2 && raw[i] <= 0xf4 {
				if i+1 >= len(raw) {
					reason = "unexpected end of data"
				} else {
					reason = "invalid continuation byte"
				}
			}
			return "", skillValueErrorf("'utf-8' codec can't decode byte 0x%02x in position %d: %s", raw[i], i, reason)
		}
		i += size
	}
	return string(raw), nil
}

// SkillZip writes files as a ZIP archive.
func SkillZip(files SkillFiles) ([]byte, error) {
	var buf bytes.Buffer
	zw := zip.NewWriter(&buf)
	for _, f := range files {
		w, err := zw.Create(f.Path)
		if err != nil {
			return nil, err
		}
		if _, err := w.Write(f.Data); err != nil {
			return nil, err
		}
	}
	if err := zw.Close(); err != nil {
		return nil, err
	}
	return buf.Bytes(), nil
}

// SkillGitHubError is a GitHubSkillImporterError; Kind tells its subclass.
type SkillGitHubError struct {
	Kind SkillGitHubErrorKind
	Msg  string
}

// SkillGitHubErrorKind is the importer error's class.
type SkillGitHubErrorKind int

// The importer's error classes.
const (
	SkillGitHubOther SkillGitHubErrorKind = iota
	SkillGitHubRateLimited
	SkillGitHubNotFound
	SkillGitHubInvalidURL
)

func (e *SkillGitHubError) Error() string { return e.Msg }

// SkillGitHubRepo is GitHubRepoInfo.
type SkillGitHubRepo struct {
	Owner, Repo string
	Branch      *string
	Path        *string
}

// SkillParseGitHubURL is parse_github_url.
func SkillParseGitHubURL(raw string) (SkillGitHubRepo, error) {
	u := SkillPyStrip(raw)
	if m := skillSSH.FindStringSubmatch(u); m != nil {
		return SkillGitHubRepo{Owner: m[1], Repo: m[2]}, nil
	}
	parsed, err := url.Parse(u)
	if err != nil {
		return SkillGitHubRepo{}, &SkillGitHubError{Kind: SkillGitHubInvalidURL, Msg: "Invalid URL: " + u}
	}
	host, p := parsed.Host, parsed.EscapedPath()
	if parsed.Opaque != "" {
		p = parsed.Opaque
	}
	if host != "github.com" && host != "www.github.com" {
		return SkillGitHubRepo{}, &SkillGitHubError{Kind: SkillGitHubInvalidURL, Msg: "Not a GitHub URL: " + u}
	}
	parts := strings.Split(strings.Trim(p, "/"), "/")
	if len(parts) < 2 {
		return SkillGitHubRepo{}, &SkillGitHubError{Kind: SkillGitHubInvalidURL, Msg: "Invalid GitHub repository URL: " + u}
	}
	info := SkillGitHubRepo{Owner: parts[0], Repo: strings.TrimSuffix(parts[1], ".git")}
	if len(parts) >= 4 && (parts[2] == "tree" || parts[2] == "blob") {
		b := parts[3]
		info.Branch = &b
		if len(parts) > 4 {
			sub := strings.Join(parts[4:], "/")
			info.Path = &sub
		}
	}
	return info, nil
}

// SkillCheckRepoPart is _REPO_PART.fullmatch and not . or ..
func SkillCheckRepoPart(p string) bool {
	return p != "." && p != ".." && skillRepoPart.MatchString(p)
}

// SkillExtractPackage is extract_skill_package: one package re-rooted out of a repository zipball.
func SkillExtractPackage(repoZip []byte, packagePath string) ([]byte, error) {
	if len(repoZip) > SkillMaxRepoZipBytes {
		return nil, skillValueErrorf("GitHub repository ZIP exceeds %d MB limit", SkillMaxRepoZipBytes/(1024*1024))
	}
	packagePath = strings.Trim(packagePath, "/")
	if strings.ToLower(path.Base(packagePath)) == "skill.md" {
		packagePath = path.Dir(packagePath)
		if packagePath == "." {
			packagePath = ""
		}
	}
	prefix := ""
	if packagePath != "" {
		prefix = packagePath + "/"
	}
	zr, err := zip.NewReader(bytes.NewReader(repoZip), int64(len(repoZip)))
	if err != nil {
		return nil, fmt.Errorf("repository archive is not a zip file: %w", err)
	}
	type sel struct {
		f   *zip.File
		rel string
	}
	var selected []sel
	var total uint64
	for _, f := range zr.File {
		if skillIsDir(f) {
			continue
		}
		parts := strings.SplitN(f.Name, "/", 2)
		if len(parts) != 2 {
			continue
		}
		rel := parts[1]
		if prefix != "" {
			if !strings.HasPrefix(rel, prefix) {
				continue
			}
			rel = rel[len(prefix):]
		}
		if rel == "" || strings.HasPrefix(rel, "__MACOSX/") {
			continue
		}
		selected = append(selected, sel{f, rel})
		total += f.UncompressedSize64
		if len(selected) > SkillMaxPackageFiles {
			return nil, skillValueErrorf("GitHub skill package contains more than %d files", SkillMaxPackageFiles)
		}
		if total > SkillMaxPackageTotalBytes {
			return nil, skillValueErrorf("GitHub skill package exceeds %d MB uncompressed limit", SkillMaxPackageTotalBytes/(1024*1024))
		}
	}
	if len(selected) == 0 {
		where := packagePath
		if where == "" {
			where = "/"
		}
		return nil, skillValueErrorf("No files found at '%s' in the GitHub repository", where)
	}
	var buf bytes.Buffer
	zw := zip.NewWriter(&buf)
	for _, s := range selected {
		rc, err := s.f.Open()
		if err != nil {
			return nil, err
		}
		data, err := io.ReadAll(rc)
		_ = rc.Close()
		if err != nil {
			return nil, err
		}
		w, err := zw.CreateHeader(&zip.FileHeader{Name: s.rel, Method: zip.Deflate})
		if err != nil {
			return nil, err
		}
		if _, err := w.Write(data); err != nil {
			return nil, err
		}
	}
	if err := zw.Close(); err != nil {
		return nil, err
	}
	return buf.Bytes(), nil
}

// SkillCycleMessage is _topological_sort's circular dependency.
const SkillCycleMessage = "Circular dependency detected in skill members"

var (
	skillSSH      = regexp.MustCompile(`^git@github\.com:([^/]+)/([^/]+?)(?:\.git)?$`)
	skillRepoPart = regexp.MustCompile(`^[A-Za-z0-9_.-]+$`)
)

// SkillMemberDeps is a member's child id and the sibling ids it runs after.
type SkillMemberDeps struct {
	Child        string
	Dependencies []string
}

// SkillTopoSort is _topological_sort (Kahn); ties keep member order.
func SkillTopoSort(members []SkillMemberDeps) ([]string, error) {
	var ids []string
	in := map[string]int{}
	for _, m := range members {
		if _, ok := in[m.Child]; !ok {
			in[m.Child] = 0
			ids = append(ids, m.Child)
		}
	}
	graph := map[string][]string{}
	for _, m := range members {
		for _, d := range m.Dependencies {
			if _, ok := in[d]; ok {
				graph[d] = append(graph[d], m.Child)
				in[m.Child]++
			}
		}
	}
	var queue, out []string
	for _, id := range ids {
		if in[id] == 0 {
			queue = append(queue, id)
		}
	}
	for len(queue) > 0 {
		n := queue[0]
		queue = queue[1:]
		out = append(out, n)
		for _, next := range graph[n] {
			in[next]--
			if in[next] == 0 {
				queue = append(queue, next)
			}
		}
	}
	if len(out) != len(ids) {
		return nil, &SkillValueError{Msg: SkillCycleMessage}
	}
	return out, nil
}
