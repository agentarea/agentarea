package mcpserver

import (
	"context"
	"encoding/json"
	"strings"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	identityapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/identity/api"
	streamsapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/api"
)

// messageTools is the messages toolset: a run writes first to a workspace member, through the
// account the member linked. The recipient is a member, never a chat id the caller names.
func messageTools(m streamsapi.PlatformMessages, members identityapi.Members) map[string]toolDef {
	return map[string]toolDef{
		"send_message": {title: "Send a message to a member", effect: effectWrite, openWorld: true, call: func(ctx context.Context, c authn.Caller, args json.RawMessage) (any, error) {
			in, err := decodeArgs[struct {
				Text   string   `json:"text"`
				To     string   `json:"to"`
				Stream string   `json:"stream"`
				Files  []string `json:"files"`
			}](args)
			if err != nil {
				return nil, err
			}
			if strings.TrimSpace(in.Text) == "" && len(in.Files) == 0 {
				return nil, &toolError{"text must not be empty"}
			}
			if len(in.Files) > 0 && c.BoundTaskID == "" {
				return nil, &toolError{"files can be sent only from a run: they are paths of the run's own files"}
			}
			to := strings.TrimSpace(in.To)
			if to == "" {
				to = c.UserID
			}
			all, err := members.ListMembers(ctx, c)
			if err != nil {
				return nil, err
			}
			for _, mb := range all {
				if mb.UserID == to || (mb.Email != nil && strings.EqualFold(*mb.Email, to)) {
					name := mb.UserID
					if mb.Email != nil {
						name = *mb.Email
					}
					return m.Send(ctx, c, streamsapi.MessageSend{UserID: mb.UserID, Recipient: name,
						Stream: strings.TrimSpace(in.Stream), Text: in.Text, Files: in.Files, TaskID: c.BoundTaskID})
				}
			}
			return nil, &toolError{to + " is not a member of this workspace; name a member by the user id or email members_list shows"}
		}},
	}
}
