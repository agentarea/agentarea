package domain

import (
	"encoding/json"
	"strings"
	"testing"
)

func summaryEntry(t *testing.T, summary string) SourceTypeEntry {
	t.Helper()
	raw := `{"slug":"x","name":"X","delivery":"webhook","event":{"kind":"k"` + summary + `}}`
	e, err := ParseSourceTypeEntry(json.RawMessage(raw))
	if err != nil {
		t.Fatal(err)
	}
	return e
}

func data(body any) map[string]any {
	return map[string]any{"headers": map[string]any{}, "body": body, "body_ref": nil}
}

func TestAStoredBodySaysNothing(t *testing.T) {
	e := summaryEntry(t, `,"summary":"{body:title}"`)
	stored := map[string]any{"headers": map[string]any{}, "body": nil, "body_ref": "files/x"}
	if f := EventSummary(e, EventOverrides{}, stored); f != nil {
		t.Fatalf("got %q", *f)
	}
}

func TestSummaryReadsHeaders(t *testing.T) {
	e := summaryEntry(t, `,"summary":"{header:X-Title}"`)
	d := map[string]any{"headers": map[string]any{"X-Title": "From header"}, "body": map[string]any{}}
	if f := EventSummary(e, EventOverrides{}, d); f == nil || *f != "From header" {
		t.Fatalf("got %v", f)
	}
}

func TestSummaryIsRenderedFromTheEntryAndASourceOverrideWins(t *testing.T) {
	e := summaryEntry(t, `,"summary":["{body:title}","{body:text}"]`)
	body := decoded(t, `{"text":"from text"}`)
	if f := EventSummary(e, EventOverrides{}, data(body)); f == nil || *f != "from text" {
		t.Fatalf("entry: %+v", f)
	}
	o, err := ParseEventOverrides(map[string]any{"summary": "{body:other}"})
	if err != nil {
		t.Fatal(err)
	}
	if f := EventSummary(e, o, data(decoded(t, `{"text":"t","other":"mine"}`))); f == nil || *f != "mine" {
		t.Fatalf("override: %+v", f)
	}
}

func TestSummaryIsAbsentWhenNothingRenders(t *testing.T) {
	if f := EventSummary(summaryEntry(t, `,"summary":"{body:title}"`), EventOverrides{}, data(decoded(t, `{}`))); f != nil {
		t.Fatalf("got %q", *f)
	}
	if f := EventSummary(summaryEntry(t, ``), EventOverrides{}, data(decoded(t, `{"title":"t"}`))); f != nil {
		t.Fatalf("entry without a summary template: %q", *f)
	}
	if f := EventSummary(summaryEntry(t, `,"summary":"{body:title}"`), EventOverrides{}, data(decoded(t, `{"title":" \n\t "}`))); f != nil {
		t.Fatalf("blank summary: %q", *f)
	}
}

func TestSummaryIsOneLineCutAtTheLimit(t *testing.T) {
	e := summaryEntry(t, `,"summary":"{body:title}"`)
	f := EventSummary(e, EventOverrides{}, data(decoded(t, `{"title":"  a \n\n b\t\tc  "}`)))
	if f == nil || *f != "a b c" {
		t.Fatalf("whitespace: %v", f)
	}
	long := strings.Repeat("я", 600)
	f = EventSummary(e, EventOverrides{}, data(decoded(t, `{"title":"`+long+`"}`)))
	if f == nil || len([]rune(*f)) != MaxSummaryRunes {
		t.Fatalf("cut: %v", f)
	}
}

func TestSummaryTemplatesParseAndRoundTripThroughOverrides(t *testing.T) {
	e := summaryEntry(t, `,"summary":["{body:a}","{body:b}"]`)
	if len(e.Event.Summary) != 2 {
		t.Fatalf("entry summary: %v", e.Event.Summary)
	}
	o, err := ParseEventOverrides(map[string]any{"summary": "{body:title}"})
	if err != nil {
		t.Fatal(err)
	}
	if got := o.Dump()["summary"]; got != "{body:title}" {
		t.Fatalf("dump: %v", got)
	}
	if _, ok := (EventOverrides{}).Dump()["summary"]; ok {
		t.Fatal("an unset summary is dumped")
	}
}

func TestTheGenericWebhookReadsASummaryFromCommonFields(t *testing.T) {
	e := shippedEntries(t)["generic_webhook"]
	f := EventSummary(e, EventOverrides{}, data(decoded(t, `{"subject":"Disk full","text":"ignored"}`)))
	if f == nil || *f != "Disk full" {
		t.Fatalf("got %v", f)
	}
}

func TestABlankFirstSummaryGivesWayToTheNext(t *testing.T) {
	e := summaryEntry(t, `,"summary":["{body:title}","{body:text}"]`)
	if f := EventSummary(e, EventOverrides{}, data(decoded(t, `{"title":"  ","text":"Disk full"}`))); f == nil || *f != "Disk full" {
		t.Fatalf("got %+v", f)
	}
}
