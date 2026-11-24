package domain

import "time"

// Skill is a skills row. Content is the pre-package body still held in the
// row (nil once moved, and nil on rows read without it); HasContent tells
// whether the row still holds one.
type Skill struct {
	ID             string
	Name           string
	Slug           string
	Description    *string
	SourceType     string
	SourceURL      *string
	NetworkScope   string
	WorkspaceID    string
	CreatedBy      string
	CreatedAt      time.Time
	UpdatedAt      time.Time
	RegistryItemID *string
	S3Path         *string
	Content        *string
}

// SkillVersion is one package a skill pointed at.
type SkillVersion struct {
	ID             string
	SkillID        string
	S3Path         string
	Digest         *string
	Reason         string
	CatalogVersion *string
	CreatedBy      string
	CreatedAt      time.Time
}

// SkillMember is a bundle edge: a child skill of a parent.
type SkillMember struct {
	ParentSkillID string
	ChildSkillID  string
	Order         int32
	IsRequired    bool
	Dependencies  []string
}

// SkillSourceContent and the others are SkillSourceType.
const (
	SkillSourceContent = "content"
	SkillSourceZip     = "zip"
	SkillSourceGitHub  = "github"
)

// SkillIsOwnCopy is is_own_copy: the skill still points at its mutable pre-package copy.
func SkillIsOwnCopy(s Skill) bool {
	return s.S3Path != nil && *s.S3Path != "" && *s.S3Path == SkillOwnCopyPrefix(s.WorkspaceID, s.ID)
}

// SkillIsCustomized is is_customized: an installed catalog skill the workspace edited.
func SkillIsCustomized(s Skill) bool {
	if s.RegistryItemID == nil || *s.RegistryItemID == "" {
		return false
	}
	return (s.S3Path != nil && SkillIsWorkspacePackage(*s.S3Path)) || SkillIsOwnCopy(s)
}
