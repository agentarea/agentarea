package service

import (
	"errors"
	"strings"
	"testing"
)

func TestSkillParseFrontmatter(t *testing.T) {
	p, err := SkillParse("---\nname: PDF tools\ndescription: Reads PDFs\n---\n\n# Heading\nbody\n")
	if err != nil || p.Name != "PDF tools" || p.Description == nil || *p.Description != "Reads PDFs" || p.Body != "# Heading\nbody" {
		t.Fatalf("%+v %v", p, err)
	}
	p, err = SkillParse("# From heading\ntext")
	if err != nil || p.Name != "From heading" || p.Description != nil {
		t.Fatalf("%+v %v", p, err)
	}
	p, err = SkillParse("no heading")
	if err != nil || p.Name != "Unnamed Skill" {
		t.Fatalf("%+v %v", p, err)
	}
}

func TestSkillParseNonStringValuesAreNotNames(t *testing.T) {
	for _, fm := range []string{"name: 123", "name: true", "name: 2024-01-01", "name: null", "name: [a]"} {
		p, err := SkillParse("---\n" + fm + "\ndescription: 1.5\n---\n# H\n")
		if err != nil || p.Name != "H" || p.Description != nil {
			t.Errorf("%s: %+v %v", fm, p, err)
		}
	}
	for _, fm := range []string{`name: "123"`, "name: !!str 123", "name: |\n  123"} {
		p, err := SkillParse("---\n" + fm + "\n---\n# H\n")
		if err != nil || strings.TrimSpace(p.Name) != "123" {
			t.Errorf("%s: %+v %v", fm, p, err)
		}
	}
}

func TestSkillParseRefusesAliases(t *testing.T) {
	_, err := SkillParse("---\na: &x [1]\nname: *x\n---\nbody")
	var fe *SkillFrontmatterError
	if !errors.As(err, &fe) || !strings.HasPrefix(fe.Msg, "SKILL.md frontmatter is refused: ") {
		t.Fatalf("%v", err)
	}
	_, err = SkillParse("---\nbase: &b {k: 1}\nother:\n  <<: *b\n---\nbody")
	if !errors.As(err, &fe) {
		t.Fatalf("merge key: %v", err)
	}
}

func TestSkillParseLenientOnBrokenYAML(t *testing.T) {
	p, err := SkillParse("---\nname: Broken: colon\ndescription: fine\n---\nbody")
	if err != nil || p.Description == nil || *p.Description != "fine" {
		t.Fatalf("%+v %v", p, err)
	}
}
