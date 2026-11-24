package api

import (
	"context"
	"errors"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
)

// ErrSkillNotFound: no such skill in the workspace.
var ErrSkillNotFound = errors.New("skill not found")

// SkillSummary is one entry of skills_list (_skill_summary) plus what the
// edit tools decide by: Package is the skill's s3_path, "" when it has none.
type SkillSummary struct {
	ID          string
	Name        string
	Slug        string
	Description *string
	SourceType  string
	SourceURL   *string
	Package     string
}

// SkillDetail is skills_get's output: the summary and the SKILL.md text.
type SkillDetail struct {
	SkillSummary
	Content string
}

// SkillFileText is one file of an inline {path: text} package, in the order given.
type SkillFileText struct {
	Path string
	Text string
}

// SkillFileEntry is one file of skills_list_files; URL is set when asked for.
type SkillFileEntry struct {
	Path string
	Size int64
	URL  *string
}

// SkillCreate is the overrides a create takes; SourceURL is recorded on the
// created skill (an import from GitHub records the URL it read).
type SkillCreate struct {
	Name        *string
	Description *string
	SourceURL   *string
}

// Skills is what the platform MCP skills toolset (tools/skills_toolset.py)
// calls. The tool layer checks the relations @requires names; these methods
// check them again where the REST routes do. A refusal of the input is an
// error whose text is what the toolset reports.
type Skills interface {
	// List is every skill of the workspace the caller may read.
	List(ctx context.Context, c authn.Caller) ([]SkillSummary, error)
	// Get is the skill and its SKILL.md; ErrSkillNotFound for an unknown id.
	Get(ctx context.Context, c authn.Caller, skillID string) (SkillDetail, error)
	// CreateFromFiles zips files and creates the skill as create_from_zip does.
	CreateFromFiles(ctx context.Context, c authn.Caller, files []SkillFileText, in SkillCreate) (SkillSummary, error)
	// CreateFromArchive is create_from_zip over a ZIP archive's bytes.
	CreateFromArchive(ctx context.Context, c authn.Caller, zip []byte, in SkillCreate) (SkillSummary, error)
	// DownloadGitHubRepo is the repository zipball a GitHub URL names, after the
	// install policy allowed an import from GitHub.
	DownloadGitHubRepo(ctx context.Context, c authn.Caller, githubURL string) ([]byte, error)
	// ExtractGitHubPackage is extract_skill_package: one package of a zipball, re-rooted.
	ExtractGitHubPackage(repoZip []byte, packagePath string) ([]byte, error)
	// EditMetadata patches name and description (nil leaves a field).
	EditMetadata(ctx context.Context, c authn.Caller, skillID string, name, description *string) (SkillSummary, error)
	// SetContent replaces the package's SKILL.md.
	SetContent(ctx context.Context, c authn.Caller, skillID, content string) (SkillSummary, error)
	// ReplaceFiles replaces the package's file tree (replace_package_from_files).
	ReplaceFiles(ctx context.Context, c authn.Caller, skillID string, files []SkillFileText) (SkillSummary, error)
	// Delete removes the skill; false when the workspace had none.
	Delete(ctx context.Context, c authn.Caller, skillID string) (bool, error)
	// ListFiles is get_skill_files(to_run=True).
	ListFiles(ctx context.Context, c authn.Caller, skillID string, includeURLs bool) ([]SkillFileEntry, error)
	// FileURL is get_skill_file_url(to_run=True); expiresIn is in seconds.
	FileURL(ctx context.Context, c authn.Caller, skillID, path string, expiresIn int) (string, error)
	// FileContent is get_skill_file_content(to_run=True).
	FileContent(ctx context.Context, c authn.Caller, skillID, path string) ([]byte, error)
}
