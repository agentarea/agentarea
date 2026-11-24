package mcpserver

import (
	"context"
	"testing"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
	identityapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/identity/api"
	streamsapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/api"
)

type fakeMessages struct{ *recorder }

func (f fakeMessages) Send(_ context.Context, c authn.Caller, in streamsapi.MessageSend) (streamsapi.MessageSent, error) {
	f.saw("send %s %s %q %q by %s", in.UserID, in.Recipient, in.Stream, in.Text, c.UserID)
	return streamsapi.MessageSent{Sent: true, To: in.Recipient, Stream: streamsapi.StreamRef{ID: "s1", Name: "bot"}, Messenger: "telegram"}, nil
}

type twoMembers struct{ fakeMembers }

func (twoMembers) ListMembers(context.Context, authn.Caller) ([]identityapi.Member, error) {
	return []identityapi.Member{
		{UserID: "u1", Email: ptr("owner@example.com"), IsOwner: true, IsYou: true},
		{UserID: "u2", Email: ptr("Bob@Example.com")},
	}, nil
}

func TestMessagesToolsetWritesOnlyToMembers(t *testing.T) {
	rec := &recorder{}
	ts := toolsetNamed(t, Providers{Messages: fakeMessages{rec}, Members: twoMembers{fakeMembers{rec}}}, "messages")
	runToolCases(t, ts, rec, []toolCase{
		{"messages_send_message", `{"text":"The report is ready"}`, `send u1 owner@example.com "" "The report is ready" by u1`, `"sent":true`, false},
		{"messages_send_message", `{"text":"hi","to":"bob@example.com","stream":"bot"}`, `send u2 Bob@Example.com "bot" "hi" by u1`, `"to":"Bob@Example.com"`, false},
		{"messages_send_message", `{"text":"hi","to":"u2"}`, `send u2 Bob@Example.com "" "hi" by u1`, `"messenger":"telegram"`, false},
		{"messages_send_message", `{"text":"hi","to":"123456789"}`, "", "123456789 is not a member of this workspace", true},
		{"messages_send_message", `{"text":"hi","to":"stranger@example.com"}`, "", "stranger@example.com is not a member of this workspace", true},
		{"messages_send_message", `{"text":"  "}`, "", "text must not be empty", true},
		{"messages_send_message", `{"files":["outputs/a.mp4"]}`, "", "files can be sent only from a run", true},
	})
}

func TestMessagesToolsetIsAnExternalWrite(t *testing.T) {
	ts := toolsetNamed(t, Providers{Messages: fakeMessages{&recorder{}}, Members: twoMembers{}}, "messages")
	tools, err := ts.Tools(context.Background(), authn.Principal{})
	if err != nil || len(tools) != 1 {
		t.Fatalf("tools %v %v", tools, err)
	}
	a := tools[0].Annotations
	if a["readOnlyHint"] != false || a["destructiveHint"] != false || a["openWorldHint"] != true {
		t.Fatalf("annotations %v", a)
	}
}
