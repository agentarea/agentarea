package service

import (
	"strings"
	"testing"
)

const stubBody = `---
name: pdf--anthropics
description: Reads and writes
  PDF files
---
Reads and writes PDF files

Imported system skill metadata. The original SKILL.md should be reviewed before execution.

Source: https://github.com/anthropics/skills/tree/main/pdf
Repository: anthropics/skills
Path: document-skills/pdf/SKILL.md
License: MIT
`

func TestParseStubFindsWhereTheOriginalLives(t *testing.T) {
	stub, ok := parseStub(stubBody)
	if !ok || stub.repo != "anthropics/skills" || stub.path != "document-skills/pdf/SKILL.md" ||
		stub.sourceURL != "https://github.com/anthropics/skills/tree/main/pdf" || stub.folder() != "document-skills/pdf" {
		t.Fatalf("%+v %v", stub, ok)
	}
	if (skillStub{path: "/a/b/"}).folder() != "a/b" {
		t.Error("a folder path keeps its slashes")
	}
	if _, ok := parseStub("# PDF\nReads PDFs"); ok {
		t.Error("a skill without the marker parsed as a stub")
	}
	if _, ok := parseStub(strings.Replace(stubBody, "Path: document-skills/pdf/SKILL.md\n", "", 1)); ok {
		t.Error("a stub without its path parsed")
	}
}

func TestBareStubIsExactlyWhatAnIndexWrote(t *testing.T) {
	desc := "Reads and writes PDF files"
	if stub, ok := bareStub(stubBody, "pdf--anthropics", &desc); !ok || stub.repo != "anthropics/skills" {
		t.Fatalf("the index's stub: %+v %v", stub, ok)
	}
	for name, text := range map[string]string{
		"an added line":       strings.Replace(stubBody, "License: MIT", "License: MIT\nNote: edited", 1),
		"a two-word license":  strings.Replace(stubBody, "License: MIT", "License: MIT or Apache", 1),
		"another paragraph":   strings.Replace(stubBody, "Reads and writes PDF files\n\n", "Reads and writes PDF files\n\nMy notes\n\n", 1),
		"another frontmatter": strings.Replace(stubBody, "name: pdf--anthropics\n", "name: pdf--anthropics\nversion: 2\n", 1),
		"a path outside":      strings.Replace(stubBody, "Path: document-skills", "Path: ../document-skills", 1),
		"a foreign source":    strings.Replace(stubBody, "https://github.com/anthropics/skills/tree", "https://example.com/anthropics/skills/tree", 1),
	} {
		if _, ok := bareStub(text, "pdf--anthropics", &desc); ok {
			t.Errorf("%s passed as the bare stub", name)
		}
	}
	if _, ok := bareStub(stubBody, "pdf", &desc); ok {
		t.Error("another name passed")
	}
	if _, ok := bareStub(stubBody, "pdf--anthropics", nil); ok {
		t.Error("no description passed")
	}
}
