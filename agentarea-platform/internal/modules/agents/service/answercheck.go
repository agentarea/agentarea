package service

import (
	"encoding/json"

	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/agents/api"
)

// answerCheck reads an AnswerCheckPolicy dump; empty or unreadable is none.
func answerCheck(raw []byte) *api.AnswerCheck {
	if len(raw) == 0 {
		return nil
	}
	var v struct {
		Enabled            *bool   `json:"enabled"`
		Language           *string `json:"language"`
		RewriteInstruction *string `json:"rewrite_instruction"`
	}
	if json.Unmarshal(raw, &v) != nil || (v.Enabled == nil && v.Language == nil && v.RewriteInstruction == nil && string(raw) == "null") {
		return nil
	}
	out := &api.AnswerCheck{Enabled: v.Enabled == nil || *v.Enabled}
	if v.Language != nil {
		out.Language = *v.Language
	}
	if v.RewriteInstruction != nil {
		out.RewriteInstruction = *v.RewriteInstruction
	}
	return out
}
