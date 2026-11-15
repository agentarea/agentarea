package handlers

import (
	"encoding/json"
	"regexp"
	"unicode/utf8"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx/wirejson"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/agents/domain"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/agents/service"
)

// Bounds of AgentCreate and AgentUpdate.
const (
	maxName        = 255
	maxDescription = 1000
	maxInstruction = 20000
	maxReasoning   = 1<<31 - 1
)

var effortShape = regexp.MustCompile(`^[a-z][a-z_-]{0,15}$`)

func agentFields(create bool) []string {
	f := []string{"name", "description", "instruction", "model_id", "client_id", "tools", "planning", "a2ui_enabled",
		"reasoning_effort", "reasoning_max_tokens", "answer_check", "skill_ids", "agent_type"}
	if create {
		return append(f, "triggers")
	}
	return append(f[:1], append([]string{"capabilities"}, f[1:]...)...)
}

// reasoningEffort is checked_reasoning_effort as a before-validator.
func reasoningEffort(o wirejson.Object, errs *[]httpx.FieldError) (*string, bool) {
	v, ok := o.Get("reasoning_effort")
	if !ok {
		return nil, false
	}
	if v == nil || v == "" {
		return nil, true
	}
	if s, isStr := v.(string); isStr && effortShape.MatchString(s) {
		return &s, true
	}
	*errs = append(*errs, httpx.ValueError("reasoning_effort must be a level name such as low or high", "body", "reasoning_effort"))
	return nil, true
}

// reasoningTokens is checked_reasoning_max_tokens as a before-validator.
func reasoningTokens(o wirejson.Object, errs *[]httpx.FieldError) (*int32, bool) {
	v, ok := o.Get("reasoning_max_tokens")
	if !ok {
		return nil, false
	}
	if v == nil {
		return nil, true
	}
	if n, isNum := v.(interface{ Int64() (int64, error) }); isNum {
		if i, err := n.Int64(); err == nil {
			switch {
			case i <= 0:
			case i > maxReasoning:
				*errs = append(*errs, httpx.ValueError("reasoning_max_tokens must be at most 2147483647", "body", "reasoning_max_tokens"))
				return nil, true
			default:
				x := int32(i)
				return &x, true
			}
		}
	}
	*errs = append(*errs, httpx.ValueError("reasoning_max_tokens must be a positive integer", "body", "reasoning_max_tokens"))
	return nil, true
}

// answerCheck is AnswerCheckPolicy (extra="forbid"); stored is its exclude_none dump.
func answerCheck(o wirejson.Object, errs *[]httpx.FieldError) (stored []byte, set bool) {
	v, ok := o.Get("answer_check")
	if !ok {
		return nil, false
	}
	if v == nil {
		return nil, true
	}
	obj, isObj := v.(wirejson.Object)
	if !isObj {
		*errs = append(*errs, httpx.ModelAttributesType("body", "answer_check"))
		return nil, true
	}
	before := len(*errs)
	enabled := true
	if raw, present := obj.Get("enabled"); present {
		b, isBool := raw.(bool)
		if !isBool {
			*errs = append(*errs, httpx.BoolType("body", "answer_check", "enabled"))
		}
		enabled = b
	}
	out := wirejson.Object{{Key: "enabled", Value: enabled}}
	sub := func(key string, minLen, maxLen int) {
		raw, present := obj.Get(key)
		if !present || raw == nil {
			return
		}
		s, isStr := raw.(string)
		switch n := utf8.RuneCountInString(s); {
		case !isStr:
			*errs = append(*errs, httpx.StringType("body", "answer_check", key))
		case n < minLen:
			*errs = append(*errs, httpx.StringTooShort(minLen, "body", "answer_check", key))
		case n > maxLen:
			*errs = append(*errs, httpx.StringTooLong(maxLen, "body", "answer_check", key))
		default:
			out = append(out, wirejson.Member{Key: key, Value: s})
		}
	}
	sub("language", 2, 8)
	sub("rewrite_instruction", 1, 4000)
	for _, m := range obj {
		if m.Key != "enabled" && m.Key != "language" && m.Key != "rewrite_instruction" {
			*errs = append(*errs, httpx.ExtraForbidden("body", "answer_check", m.Key))
		}
	}
	if len(*errs) > before {
		return nil, true
	}
	raw, _ := wirejson.Marshal(out, wirejson.Compact)
	return raw, true
}

func tools(o wirejson.Object, errs *[]httpx.FieldError) (out []domain.Tool, set bool) {
	v, ok := o.Get("tools")
	if !ok {
		return nil, false
	}
	if v == nil {
		return nil, true
	}
	arr, isArr := v.([]any)
	if !isArr {
		*errs = append(*errs, httpx.ListType("body", "tools"))
		return nil, true
	}
	out = []domain.Tool{}
	for i, it := range arr {
		if t, ok := service.ParseTool(it, []any{"body", "tools", i}, errs); ok {
			out = append(out, t)
		}
	}
	return out, true
}

func uuidList(o wirejson.Object, key string, errs *[]httpx.FieldError) (out []string, set bool) {
	v, ok := o.Get(key)
	if !ok {
		return nil, false
	}
	if v == nil {
		return nil, true
	}
	arr, isArr := v.([]any)
	if !isArr {
		*errs = append(*errs, httpx.ListType("body", key))
		return nil, true
	}
	out = []string{}
	for i, it := range arr {
		s, isStr := it.(string)
		if !isStr {
			*errs = append(*errs, httpx.FieldError{Type: "uuid_type", Loc: []any{"body", key, i}, Msg: "UUID input should be a string, bytes or UUID object"})
			continue
		}
		id, fe := httpx.ValidateUUID(s, "body", key, i)
		if fe != nil {
			*errs = append(*errs, *fe)
			continue
		}
		out = append(out, id)
	}
	return out, true
}

func agentType(o wirejson.Object, nullAllowed bool, errs *[]httpx.FieldError) (*string, bool) {
	v, ok := o.Get("agent_type")
	if !ok {
		return nil, false
	}
	if v == nil && !nullAllowed {
		*errs = append(*errs, httpx.ValueError("may be omitted, but not set to null", "body", "agent_type"))
		return nil, true
	}
	s, isStr := v.(string)
	switch {
	case !isStr:
		*errs = append(*errs, httpx.FieldError{Type: "literal_error", Loc: []any{"body", "agent_type"}, Msg: "Input should be 'stateless' or 'stateful'"})
		return nil, true
	case s != "stateless" && s != "stateful":
		*errs = append(*errs, httpx.FieldError{Type: "literal_error", Loc: []any{"body", "agent_type"}, Msg: "Input should be 'stateless' or 'stateful'"})
		return nil, true
	}
	return &s, true
}

// createBody is AgentCreateRequest.
func createBody(v any, in *input, errs *[]httpx.FieldError) {
	o, ok := model(v, errs)
	if !ok {
		return
	}
	c := &in.create
	c.AgentType = "stateless"
	switch name, set := str(o, "name", 1, maxName, false, errs); {
	case !set:
		*errs = append(*errs, httpx.Missing("body", "name"))
	case name != nil:
		c.Name = pyStrip(*name)
		if c.Name == "" {
			*errs = append(*errs, httpx.ValueError("name cannot be empty or whitespace", "body", "name"))
		}
	}
	if d, set := str(o, "description", 0, maxDescription, false, errs); set && d != nil {
		c.Description = *d
	}
	if d, set := str(o, "instruction", 0, maxInstruction, false, errs); set && d != nil {
		c.Instruction = *d
	}
	c.ModelID, _ = str(o, "model_id", 0, 0, true, errs)
	c.ClientID, _ = uuidField(o, "client_id", errs)
	switch t, set := tools(o, errs); {
	case !set:
		*errs = append(*errs, httpx.Missing("body", "tools"))
	case t == nil:
		*errs = append(*errs, httpx.ListType("body", "tools"))
	default:
		c.Tools = t
	}
	c.Planning, _ = boolField(o, "planning", errs)
	c.A2UIEnabled, _ = boolField(o, "a2ui_enabled", errs)
	c.ReasoningEffort, _ = reasoningEffort(o, errs)
	c.ReasoningMaxTokens, _ = reasoningTokens(o, errs)
	c.AnswerCheck, _ = answerCheck(o, errs)
	c.SkillIDs, _ = uuidList(o, "skill_ids", errs)
	if at, set := agentType(o, true, errs); set && at != nil {
		c.AgentType = *at
	}
	if tv, ok := o.Get("triggers"); ok {
		arr, isArr := tv.([]any)
		if !isArr {
			*errs = append(*errs, httpx.ListType("body", "triggers"))
		}
		for _, spec := range arr {
			raw, err := json.Marshal(spec)
			if err != nil {
				*errs = append(*errs, httpx.ListType("body", "triggers"))
				break
			}
			c.Triggers = append(c.Triggers, raw)
		}
	}
	extraForbidden(o, agentFields(true), errs)
	if len(*errs) == 0 && c.ReasoningEffort != nil && c.ReasoningMaxTokens != nil {
		*errs = append(*errs, httpx.ValueError("set reasoning_effort or reasoning_max_tokens, not both", "body"))
	}
}

// updateBody is AgentUpdate: only sent keys change.
func updateBody(v any, in *input, errs *[]httpx.FieldError) {
	o, ok := model(v, errs)
	if !ok {
		return
	}
	p := &in.patch
	if raw, present := o.Get("name"); present && raw == nil {
		*errs = append(*errs, httpx.ValueError("may be omitted, but not set to null", "body", "name"))
	} else {
		p.Name, _ = str(o, "name", 1, maxName, false, errs)
	}
	if raw, present := o.Get("capabilities"); present && raw != nil {
		if _, isArr := raw.([]any); !isArr {
			*errs = append(*errs, httpx.ListType("body", "capabilities"))
		}
	}
	p.Description.Value, p.Description.Set = str(o, "description", 0, maxDescription, true, errs)
	p.Instruction.Value, p.Instruction.Set = str(o, "instruction", 0, maxInstruction, true, errs)
	p.ModelID.Value, p.ModelID.Set = str(o, "model_id", 0, 0, true, errs)
	p.ClientID.Value, p.ClientID.Set = uuidField(o, "client_id", errs)
	if t, set := tools(o, errs); set && t != nil {
		p.Tools = &t
	}
	p.Planning.Value, p.Planning.Set = boolField(o, "planning", errs)
	p.A2UIEnabled.Value, p.A2UIEnabled.Set = boolField(o, "a2ui_enabled", errs)
	p.ReasoningEffort.Value, p.ReasoningEffort.Set = reasoningEffort(o, errs)
	p.ReasoningMaxTokens.Value, p.ReasoningMaxTokens.Set = reasoningTokens(o, errs)
	if raw, set := answerCheck(o, errs); set {
		p.AnswerCheck = service.Set[[]byte]{Set: true}
		if raw != nil {
			p.AnswerCheck.Value = &raw
		}
	}
	if ids, set := uuidList(o, "skill_ids", errs); set && ids != nil {
		p.SkillIDs = &ids
	}
	p.AgentType, _ = agentType(o, false, errs)
	extraForbidden(o, agentFields(false), errs)
}
