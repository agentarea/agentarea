package domain

import (
	"archive/zip"
	"bytes"
	"errors"
	"strings"
	"testing"
)

func skillTestZip(t *testing.T, files map[string]string, order ...string) []byte {
	t.Helper()
	var buf bytes.Buffer
	zw := zip.NewWriter(&buf)
	for _, name := range order {
		w, err := zw.Create(name)
		if err != nil {
			t.Fatal(err)
		}
		_, _ = w.Write([]byte(files[name]))
	}
	if err := zw.Close(); err != nil {
		t.Fatal(err)
	}
	return buf.Bytes()
}

func TestSkillDigestMatchesPackageDigest(t *testing.T) {
	var fs SkillFiles
	fs.Set("a/b.txt", []byte("x"))
	fs.Set("SKILL.md", []byte("hi"))
	if got := SkillDigest(fs); got != "af36980ac6d0789b01d00f2d72284777bf36e65ef82851baeae1e6c284a8c5fe" {
		t.Errorf("digest %s", got)
	}
}

func TestSkillSafePath(t *testing.T) {
	if p, err := SkillSafePath("/a/b.md"); err != nil || p != "a/b.md" {
		t.Errorf("%q %v", p, err)
	}
	for _, bad := range []string{"", "a/../b", "a//b", `a\b`, "./a", "a/."} {
		var ve *SkillValueError
		if _, err := SkillSafePath(bad); !errors.As(err, &ve) || !strings.HasPrefix(ve.Msg, "Invalid skill file path: ") {
			t.Errorf("%q: %v", bad, err)
		}
	}
	if _, err := SkillSafePath("a/../b"); err.Error() != "Invalid skill file path: 'a/../b'" {
		t.Errorf("repr: %v", err)
	}
}

func TestSkillFilesSetKeepsFirstPlace(t *testing.T) {
	var fs SkillFiles
	fs.Set("b", []byte("1"))
	fs.Set("a", []byte("2"))
	fs.Set("b", []byte("3"))
	if got := strings.Join(fs.Paths(), ","); got != "b,a" {
		t.Errorf("%s", got)
	}
	if d, _ := fs.Get("b"); string(d) != "3" {
		t.Errorf("%s", d)
	}
}

func TestSkillCheckedFilesLimits(t *testing.T) {
	var fs SkillFiles
	fs.Set("big", make([]byte, SkillMaxPackageFileBytes+1))
	if _, err := SkillCheckedFiles(fs); err == nil || err.Error() != "Skill package file 'big' is larger than 10 MB" {
		t.Errorf("%v", err)
	}
	fs = nil
	for i := 0; i <= SkillMaxPackageFiles; i++ {
		fs = append(fs, SkillFile{Path: "f" + strings.Repeat("x", i%7) + string(rune('a'+i%26)), Data: nil})
	}
	if _, err := SkillCheckedFiles(fs); err == nil || err.Error() != "Skill package contains more than 1000 files" {
		t.Errorf("%v", err)
	}
}

func TestSkillPackagePaths(t *testing.T) {
	area := SkillWorkspacePackageArea("w1")
	p := area + "/abc/"
	if !SkillIsWorkspacePackage(p) || !SkillIsImmutablePackage(p) || SkillIsCatalogPackage(p) {
		t.Errorf("%s", p)
	}
	if d := SkillPackageDigestOf(&p); d == nil || *d != "abc" {
		t.Errorf("%v", d)
	}
	own := SkillOwnCopyPrefix("w1", "s1")
	if SkillIsImmutablePackage(own) || SkillPackageDigestOf(&own) != nil {
		t.Errorf("own copy %s", own)
	}
	if !SkillIsOwnCopy(Skill{ID: "s1", WorkspaceID: "w1", S3Path: &own}) {
		t.Error("own copy not recognised")
	}
}

func TestSkillContentType(t *testing.T) {
	for p, want := range map[string]string{"SKILL.md": "text/markdown", "x.yaml": "application/yaml", "x.json": "application/json", "x.unknownext": "application/octet-stream"} {
		if got := SkillContentType(p); got != want {
			t.Errorf("%s: %s, want %s", p, got, want)
		}
	}
}

func TestSkillFilesFromZipStripsTheRootFolder(t *testing.T) {
	data := skillTestZip(t, map[string]string{"pkg/SKILL.md": "# S", "pkg/ref/a.txt": "a", "pkg/.hidden/x": "h", "__MACOSX/pkg/SKILL.md": "m"},
		"pkg/SKILL.md", "pkg/ref/a.txt", "pkg/.hidden/x", "__MACOSX/pkg/SKILL.md")
	fs, err := SkillFilesFromZip(data)
	if err != nil {
		t.Fatal(err)
	}
	if got := strings.Join(fs.Paths(), ","); got != "SKILL.md,ref/a.txt" {
		t.Errorf("%s", got)
	}
	main, err := SkillMainFromZip(data)
	if err != nil || main != "# S" {
		t.Errorf("%q %v", main, err)
	}
	if _, err := SkillFilesFromZip([]byte("nope")); err == nil {
		t.Error("not a zip")
	}
	noMain := skillTestZip(t, map[string]string{"a.txt": "a"}, "a.txt")
	if _, err := SkillMainFromZip(noMain); err == nil || err.Error() != SkillMissingManifest {
		t.Errorf("%v", err)
	}
}

func TestSkillZipRoundTrip(t *testing.T) {
	var fs SkillFiles
	fs.Set("SKILL.md", []byte("x"))
	fs.Set("d/e.txt", []byte("y"))
	data, err := SkillZip(fs)
	if err != nil {
		t.Fatal(err)
	}
	back, err := SkillFilesFromZip(data)
	if err != nil || SkillDigest(back) != SkillDigest(fs) {
		t.Errorf("%v %v", back, err)
	}
}

func TestSkillParseGitHubURL(t *testing.T) {
	r, err := SkillParseGitHubURL(" https://github.com/acme/tools.git ")
	if err != nil || r.Owner != "acme" || r.Repo != "tools" || r.Branch != nil {
		t.Errorf("%+v %v", r, err)
	}
	r, err = SkillParseGitHubURL("https://github.com/acme/tools/tree/main/skills/pdf")
	if err != nil || *r.Branch != "main" || *r.Path != "skills/pdf" {
		t.Errorf("%+v %v", r, err)
	}
	r, err = SkillParseGitHubURL("git@github.com:acme/tools.git")
	if err != nil || r.Owner != "acme" || r.Repo != "tools" {
		t.Errorf("%+v %v", r, err)
	}
	var ge *SkillGitHubError
	if _, err := SkillParseGitHubURL("https://gitlab.com/a/b"); !errors.As(err, &ge) || ge.Msg != "Not a GitHub URL: https://gitlab.com/a/b" {
		t.Errorf("%v", err)
	}
	if _, err := SkillParseGitHubURL("https://github.com/acme"); !errors.As(err, &ge) || ge.Msg != "Invalid GitHub repository URL: https://github.com/acme" {
		t.Errorf("%v", err)
	}
	if SkillCheckRepoPart("..") || SkillCheckRepoPart("a b") || !SkillCheckRepoPart("a.b-c_d") {
		t.Error("repo part")
	}
}

func TestSkillExtractPackage(t *testing.T) {
	repo := skillTestZip(t, map[string]string{"tools-main/README.md": "r", "tools-main/skills/pdf/SKILL.md": "# P", "tools-main/skills/pdf/a.py": "a"},
		"tools-main/README.md", "tools-main/skills/pdf/SKILL.md", "tools-main/skills/pdf/a.py")
	for _, p := range []string{"skills/pdf", "/skills/pdf/", "skills/pdf/SKILL.md"} {
		out, err := SkillExtractPackage(repo, p)
		if err != nil {
			t.Fatal(err)
		}
		fs, err := SkillFilesFromZip(out)
		if err != nil || strings.Join(fs.Paths(), ",") != "SKILL.md,a.py" {
			t.Errorf("%s: %v %v", p, fs.Paths(), err)
		}
	}
	if _, err := SkillExtractPackage(repo, "nope"); err == nil || err.Error() != "No files found at 'nope' in the GitHub repository" {
		t.Errorf("%v", err)
	}
	whole, err := SkillExtractPackage(repo, "")
	if err != nil {
		t.Fatal(err)
	}
	if fs, _ := SkillFilesFromZip(whole); len(fs) != 3 {
		t.Errorf("whole repo %v", fs.Paths())
	}
}

func TestSkillTopoSortIsDeterministic(t *testing.T) {
	members := []SkillMemberDeps{{Child: "c"}, {Child: "a", Dependencies: []string{"b", "outside"}}, {Child: "b"}, {Child: "d"}}
	for range 20 {
		got, err := SkillTopoSort(members)
		if err != nil || strings.Join(got, ",") != "c,b,d,a" {
			t.Fatalf("%v %v", got, err)
		}
	}
	_, err := SkillTopoSort([]SkillMemberDeps{{Child: "a", Dependencies: []string{"b"}}, {Child: "b", Dependencies: []string{"a"}}})
	var ve *SkillValueError
	if !errors.As(err, &ve) || ve.Msg != SkillCycleMessage {
		t.Errorf("%v", err)
	}
}
