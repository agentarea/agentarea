package app

import (
	"context"
	"errors"
	"testing"

	agentsservice "github.com/agentarea/agentarea/agentarea-platform/internal/modules/agents/service"
)

func TestReportSkillJobCountsStatusesInFirstSeenOrder(t *testing.T) {
	gone := "item left the catalog"
	got := reportSkillJob([]agentsservice.SkillJobResult{
		{WorkspaceID: "w1", SkillID: "s1", Name: "a", Status: "repinned"},
		{WorkspaceID: "w1", SkillID: "s2", Name: "b", Status: "skipped", Error: &gone},
		{WorkspaceID: "w2", SkillID: "s3", Name: "c", Status: "repinned"},
	}, "No catalog installs")
	want := "repinned  w1/s1  a\nskipped  w1/s2  b: item left the catalog\nrepinned  w2/s3  c\n2 repinned, 1 skipped\n"
	if got != want {
		t.Fatalf("%q", got)
	}
	if got := reportSkillJob(nil, "No stub installs"); got != "No stub installs\n" {
		t.Fatalf("%q", got)
	}
	url, kept := "https://github.com/o/r/tree/c1/s", "description taken from its SKILL.md"
	got = reportSkillJob([]agentsservice.SkillJobResult{
		{WorkspaceID: "w1", SkillID: "s1", Name: "a", Status: "refreshed", SourceURL: &url, Error: &kept},
	}, "No stub installs")
	if want := "refreshed  w1/s1  a  https://github.com/o/r/tree/c1/s: description taken from its SKILL.md\n1 refreshed\n"; got != want {
		t.Fatalf("%q", got)
	}
}

func TestSkillsRefusesUnknownJobsAndFlags(t *testing.T) {
	b, _ := quiet()
	for _, args := range [][]string{
		{"skills"}, {"skills", "nope"}, {"skills", "move-bodies-to-packages", "--dry-run"},
		{"skills", "delete-moved-own-copies", "--min-age-hours", "-1"}, {"skills", "repin-catalog-installs", "extra"},
	} {
		if err := b.Run(context.Background(), args); !errors.Is(err, ErrUsage) {
			t.Errorf("%v: %v", args, err)
		}
	}
}

func TestStatusNamesTheMissingDatabase(t *testing.T) {
	b, _ := quiet()
	b.lookup = mapLookup(nil)
	if err := b.Run(context.Background(), []string{"status"}); err == nil {
		t.Fatal("status without AGENTAREA_DB_HOST passed")
	}
}
