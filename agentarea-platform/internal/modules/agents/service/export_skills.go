package service

import (
	"context"
	"errors"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	agentsapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/agents/api"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/agents/domain"
)

// SkillsExport is the skill store the workspace config export reads.
type SkillsExport struct{ K *Skills }

var _ ExportSkills = SkillsExport{}

// ExportSkills is SkillService.list() with each SKILL.md the export inlines.
func (e SkillsExport) ExportSkills(ctx context.Context, c authn.Caller) ([]domain.ExportSkill, error) {
	views, _, err := e.K.List(ctx, c, SkillListQuery{Limit: 1 << 20})
	if err != nil {
		return nil, err
	}
	out := make([]domain.ExportSkill, 0, len(views))
	for _, v := range views {
		sk := domain.ExportSkill{ID: v.ID, Name: v.Name, Slug: v.Slug, SourceType: v.SourceType, IsCatalog: v.IsCatalog}
		if v.SourceURL != nil {
			sk.SourceURL = *v.SourceURL
		}
		if !v.IsCatalog && (sk.SourceType != domain.SkillSourceGitHub || sk.SourceURL == "") {
			id, err := uuid.Parse(v.ID)
			if err != nil {
				return nil, err
			}
			_, text, err := e.K.Content(ctx, c, id)
			var invalid *domain.SkillValueError
			if errors.As(err, &invalid) {
				return nil, &agentsapi.ExportInvalidError{Msg: invalid.Msg}
			}
			if err != nil {
				return nil, err
			}
			sk.Content = text
		}
		out = append(out, sk)
	}
	return out, nil
}
