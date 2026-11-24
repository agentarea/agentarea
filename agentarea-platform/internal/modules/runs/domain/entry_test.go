package domain

import "testing"

func TestTheModelWindowLeadsWithTheLatestSystemPrompt(t *testing.T) {
	window := ModelWindow([]Entry{
		{Seq: 0, Kind: KindMessage, Role: "system", Content: "morning prompt"},
		{Seq: 1, Kind: KindMessage, Role: "user", Content: "hi"},
		{Seq: 2, Kind: KindMessage, Role: "assistant", Content: "hello"},
		{Seq: 3, Kind: KindMessage, Role: "system", Content: "redeployed prompt"},
		{Seq: 4, Kind: KindMessage, Role: "user", Content: "again"},
	})
	var got []string
	for _, e := range window {
		got = append(got, e.Content)
	}
	if len(got) != 4 || got[0] != "redeployed prompt" || got[1] != "hi" || got[3] != "again" {
		t.Fatalf("window = %q", got)
	}
}
