package mcpserver

import (
	"context"
	"encoding/json"
	"fmt"
	"slices"
	"strings"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/authn"
	runsapi "github.com/agentarea/agentarea/agentarea-go/internal/modules/runs/api"
)

// inboxStatuses is INBOX_STATUSES in order.
func inboxStatuses() []string {
	return []string{"waiting_for_approval", "waiting_for_input", "completed", "failed"}
}

// inboxTools is tools/inbox_toolset.py.
func inboxTools(i runsapi.PlatformInbox) map[string]toolDef {
	return map[string]toolDef{
		"list": {title: "List inbox items", effect: effectRead, call: func(ctx context.Context, c authn.Caller, args json.RawMessage) (any, error) {
			in, err := decodeArgs[struct {
				Status   *string `json:"status"`
				AgentID  string  `json:"agent_id"`
				Page     *int    `json:"page"`
				PageSize *int    `json:"page_size"`
			}](args)
			if err != nil {
				return nil, err
			}
			if in.Status != nil && *in.Status == "" {
				in.Status = nil
			}
			if in.Status != nil && !slices.Contains(inboxStatuses(), *in.Status) {
				quoted := make([]string, 0, 4)
				for _, s := range inboxStatuses() {
					quoted = append(quoted, "'"+s+"'")
				}
				return nil, &toolError{fmt.Sprintf("Unknown inbox status '%s'; expected one of [%s]", *in.Status, strings.Join(quoted, ", "))}
			}
			page, size := 1, 50
			if in.Page != nil {
				page = *in.Page
			}
			if in.PageSize != nil {
				size = *in.PageSize
			}
			return i.List(ctx, c, in.Status, in.AgentID, page, size)
		}},
	}
}
