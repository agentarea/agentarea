package domain

import "time"

// DefaultFollowUpWindow is how long a web chat's completed turn waits for the next message.
const DefaultFollowUpWindow = 30 * time.Minute

// InteractionCapabilities are the human return routes of a run.
type InteractionCapabilities struct {
	Channel        string `json:"channel"`
	AllowQuestions bool   `json:"allow_questions"`
	AllowApprovals bool   `json:"allow_approvals"`
	AllowA2UI      bool   `json:"allow_a2ui"`
}

// DefaultInteraction is a web route with questions and approvals.
func DefaultInteraction() InteractionCapabilities {
	return InteractionCapabilities{Channel: "web", AllowQuestions: true, AllowApprovals: true}
}

// ResolveInteraction derives the return route; restrictions only subtract.
func ResolveInteraction(params, metadata map[string]any, a2uiEnabled bool) InteractionCapabilities {
	interaction, ok := params["interaction"].(map[string]any)
	if raw, present := params["interaction"]; present && raw != nil && !ok {
		interaction = map[string]any{"channel": "none"}
	}
	var web bool
	if ch, has := interaction["channel"]; has {
		web = ch == "web"
	} else if truthy(params["delivery_address"]) {
		web = false
	} else {
		scheduled := truthy(params["trigger_id"]) || truthy(params["trigger_type"]) || truthy(metadata["scheduled_at"])
		web = !scheduled
		for _, src := range []any{params["source"], metadata["source"], metadata["created_via"]} {
			switch src {
			case nil, "", "web", "api", "rest", "manual":
			default:
				web = false
			}
		}
	}
	allow := func(key string) bool {
		v, has := interaction[key]
		if !has {
			return true
		}
		b, isBool := v.(bool)
		return isBool && b
	}
	channel := "none"
	if web {
		channel = "web"
	}
	return InteractionCapabilities{
		Channel:        channel,
		AllowQuestions: web && allow("allow_questions"),
		AllowApprovals: web && allow("allow_approvals"),
		AllowA2UI:      web && a2uiEnabled && allow("allow_a2ui"),
	}
}

// FollowUpWindow is how long a completed turn waits for the next message;
// ok is false when the run ends instead.
func FollowUpWindow(params map[string]any, caps InteractionCapabilities) (time.Duration, bool) {
	if session, isMap := params["session"].(map[string]any); isMap {
		if cont, _ := session["continue"].(bool); !cont {
			return 0, false
		}
		if secs, isInt := intValue(session["idle_timeout_seconds"]); isInt && secs > 0 {
			return time.Duration(secs) * time.Second, true
		}
		return DefaultFollowUpWindow, true
	}
	if caps.Channel == "web" {
		return DefaultFollowUpWindow, true
	}
	return 0, false
}

func intValue(v any) (int, bool) {
	switch x := v.(type) {
	case int:
		return x, true
	case int64:
		return int(x), true
	case float64:
		if x == float64(int(x)) {
			return int(x), true
		}
	}
	return 0, false
}
