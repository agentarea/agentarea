package service

import (
	"strings"
	"testing"
	"time"

	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/domain"
)

func chatEvent(text string) (domain.Event, map[string]any) {
	session := "src-1:42"
	body := map[string]any{"message": map[string]any{"chat": map[string]any{"id": 42}, "text": text}}
	e := domain.Event{
		Kind: "message", EventKey: "update:9", ReceivedAt: time.Date(2026, 11, 24, 9, 12, 3, 0, time.UTC),
		SessionKey: &session,
		Data:       map[string]any{"body": body, "body_ref": nil, "headers": map[string]any{"x-forwarded-for": "10.0.0.1"}},
	}
	ev := StreamTriggerEvent(e, "Assistant", nil)
	data := make(map[string]any, len(ev.Data)+1)
	for k, v := range ev.Data {
		data[k] = v
	}
	data["text"] = text
	return e, data
}

func fireOn(t *testing.T, tr domain.Trigger, e domain.Event, data map[string]any) taskInput {
	t.Helper()
	ev := StreamTriggerEvent(e, "Assistant", nil)
	ev.Data = data
	in, asks, err := composeTaskInput(tr, data, &ev, nil)
	if err != nil || !asks {
		t.Fatalf("compose: asks=%v err=%v", asks, err)
	}
	return in
}

func assertEventKept(t *testing.T, in taskInput, data map[string]any) {
	t.Helper()
	if in.eventFile != triggerEventFileName || !domain.JSONEqual(in.eventData, data) {
		t.Errorf("the whole event stays with the task: %q %v", in.eventFile, in.eventData)
	}
	if in.followUp != "what can you do?" {
		t.Errorf("follow-up = %q", in.followUp)
	}
}

func TestAChatMessageWithoutTriggerTextIsExactlyTheMessage(t *testing.T) {
	e, data := chatEvent("what can you do?")
	in := fireOn(t, domain.Trigger{Name: "Telegram → Assistant", Type: "stream"}, e, data)
	if in.ask != "what can you do?" || in.message != "what can you do?" {
		t.Errorf("the task text is the message alone: ask %q message:\n%s", in.ask, in.message)
	}
	assertEventKept(t, in, data)
}

func TestAChatMessageFollowsTheTriggerTextLabelled(t *testing.T) {
	e, data := chatEvent("what can you do?")
	tr := domain.Trigger{Name: "Assistant", Type: "stream", TaskParameters: map[string]any{"text": "Answer politely."}}
	in := fireOn(t, tr, e, data)
	if in.ask != "Answer politely." || in.message != "Answer politely.\n\n## Message\n\nwhat can you do?" {
		t.Errorf("the trigger text leads, the message follows labelled:\n%s", in.message)
	}
	assertEventKept(t, in, data)
}

func TestAnEventWithoutTextKeepsItsEventBlock(t *testing.T) {
	e, data := chatEvent("")
	delete(data, "text")
	e.SessionKey = nil
	tr := domain.Trigger{Name: "Deploys", Type: "stream", TaskParameters: map[string]any{"text": "Check the deploy."}}
	in := fireOn(t, tr, e, data)
	for _, want := range []string{"Check the deploy.\n\n## What started this run", "- Event key: \"update:9\"", "```json", "x-forwarded-for"} {
		if !strings.Contains(in.message, want) {
			t.Errorf("message lacks %q:\n%s", want, in.message)
		}
	}
	if in.eventFile != "" {
		t.Errorf("a small event stays inline, got file %q", in.eventFile)
	}
}

func TestATextOutsideAConversationKeepsItsEventBlock(t *testing.T) {
	e, data := chatEvent("Fix the login bug")
	e.SessionKey = nil
	in := fireOn(t, domain.Trigger{Name: "PRs", Type: "stream", TaskParameters: map[string]any{"text": "Review it."}}, e, data)
	if !strings.Contains(in.message, "## What started this run") || !strings.Contains(in.message, "```json") {
		t.Errorf("an event with no session keeps its block:\n%s", in.message)
	}
}
