package domain

import (
	"crypto/sha256"
	"encoding/hex"
	"slices"
	"strings"
)

// ConfigHashVersion names the hashed field set (config_hash.py).
const ConfigHashVersion = "v2"

func canonicalJSON(v any) any {
	switch x := v.(type) {
	case map[string]any:
		out := make(map[string]any, len(x))
		for k, item := range x {
			out[k] = canonicalJSON(item)
		}
		return out
	case []any:
		items := make([]any, len(x))
		for i, item := range x {
			items[i] = canonicalJSON(item)
		}
		slices.SortStableFunc(items, func(a, b any) int { return strings.Compare(PyDumps(a), PyDumps(b)) })
		return items
	}
	return v
}

// AgentConfigHash is compute_agent_config_hash: "v2:<sha256>" of the fields
// the runtime acts on, order-independent. Values are plain JSON (maps, slices).
func AgentConfigHash(instruction, modelID string, tools []any, planning bool, agentType string, skillIDs []string) string {
	var typ, instr, model any
	plan := planning
	if agentType != "" {
		typ = agentType
	}
	if instruction != "" {
		instr = instruction
	}
	if modelID != "" {
		model = modelID
	}
	var toolsValue any
	if tools != nil {
		toolsValue = canonicalJSON(tools)
	}
	ids := slices.Clone(skillIDs)
	slices.Sort(ids)
	idList := make([]any, len(ids))
	for i, id := range ids {
		idList[i] = id
	}
	payload := map[string]any{
		"instruction": instr, "model_id": model, "tools": toolsValue,
		"planning": plan, "agent_type": typ, "skill_ids": idList,
	}
	var b strings.Builder
	pyEncode(&b, payload, ",", ":", true)
	sum := sha256.Sum256([]byte(b.String()))
	return ConfigHashVersion + ":" + hex.EncodeToString(sum[:])
}
