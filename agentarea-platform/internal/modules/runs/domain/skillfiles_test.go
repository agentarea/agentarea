package domain

import (
	"strings"
	"testing"
)

func TestSkillWorkspaceDirKeysOnTheID(t *testing.T) {
	a, b := SkillWorkspaceDir("Deploy API", "1"), SkillWorkspaceDir("deploy_api", "2")
	if !strings.HasPrefix(a, "inputs/skills/deploy-api-") || !strings.HasPrefix(b, "inputs/skills/deploy-api-") || a == b {
		t.Fatalf("%s %s", a, b)
	}
	if got := SkillWorkspaceDir("Отчёт!", "1"); !strings.HasPrefix(got, "inputs/skills/отчёт-") {
		t.Fatal(got)
	}
	if got := SkillWorkspaceDir("!!", "1"); !strings.HasPrefix(got, "inputs/skills/skill-") || len(got) != len("inputs/skills/skill-")+8 {
		t.Fatal(got)
	}
}

func TestSkillWorkspaceFilesAddsAManifestAndRefusesEscapes(t *testing.T) {
	files, err := SkillWorkspaceFiles("s", "1", []SkillFile{{Path: "./scripts//run.sh", Data: []byte("x")}})
	dir := SkillWorkspaceDir("s", "1")
	if err != nil || len(files) != 2 || files[0].Path != dir+"/SKILL.md" || files[1].Path != dir+"/scripts/run.sh" {
		t.Fatalf("%+v %v", files, err)
	}
	if _, err := SkillWorkspaceFiles("s", "1", []SkillFile{{Path: "SKILL.md"}, {Path: "a/../../x"}}); err == nil || err.Error() != "skill bundle path escapes workspace: 'a/../../x'" {
		t.Fatal(err)
	}
}

func TestFileListingIsPythonsIndentedJSON(t *testing.T) {
	want := "{\n  \"pattern\": \"*\",\n  \"scope\": \"/\",\n  \"matches_found\": 0,\n  \"files\": []\n}"
	if got := FileListing("*", "matches_found", true, nil); got != want {
		t.Fatal(got)
	}
	if got := FileListing("é", "files_found", false, []string{"a"}); !strings.Contains(got, `"pattern": "\u00e9"`) {
		t.Fatal(got)
	}
}
