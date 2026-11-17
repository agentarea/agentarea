package handlers

import (
	"fmt"
	"net/http"
	"testing"

	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/agents/service"
)

func TestCatalogUpdateRefusalsAre409WithTheirCode(t *testing.T) {
	for code, err := range map[string]error{
		"skill_customized":       &service.SkillCustomizedError{Msg: "edited"},
		"skill_not_from_catalog": fmt.Errorf("update: %w", &service.SkillNotFromCatalogError{Msg: "no item"}),
	} {
		e, ok := mapSkillError(err)
		if !ok || e.Status != http.StatusConflict || e.Code != code {
			t.Errorf("%s: %+v %v", code, e, ok)
		}
	}
}
