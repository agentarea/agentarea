package catalog

import (
	"testing"
	"time"
)

func TestParseReadsPollAndRegistration(t *testing.T) {
	entry, err := Parse([]byte(`{
		"slug": "telegram",
		"poll": {"transport": "http_json", "request": {"method": "GET", "url": "https://x/{cursor}"},
		         "items": "result", "cursor": "{item:update_id}+1", "interval": "0s"},
		"registration": {"register": {"method": "POST", "url": "https://x/set", "json": {"url": "{webhook_url}"}}},
		"event": {"kind": "ignored here"}
	}`))
	if err != nil {
		t.Fatalf("Parse: %v", err)
	}
	if entry.Slug != "telegram" || entry.Poll.Transport != "http_json" || entry.Poll.Items != "result" {
		t.Fatalf("entry = %+v", entry)
	}
	if entry.Registration.Register.Method != "POST" {
		t.Fatalf("register = %+v", entry.Registration.Register)
	}
	if d, err := entry.Poll.PollInterval(); err != nil || d != 0 {
		t.Fatalf("interval = %v, %v", d, err)
	}
}

func TestParseRefusesAnEntryWithoutSlug(t *testing.T) {
	if _, err := Parse([]byte(`{"poll": {}}`)); err == nil {
		t.Fatal("Parse accepted an entry without a slug")
	}
}

func TestPollIntervalParsesDurations(t *testing.T) {
	if d, err := (Poll{Interval: "5m"}).PollInterval(); err != nil || d != 5*time.Minute {
		t.Fatalf("interval = %v, %v", d, err)
	}
	if d, err := (Poll{}).PollInterval(); err != nil || d != DefaultPollInterval {
		t.Fatalf("default interval = %v, %v", d, err)
	}
	if _, err := (Poll{Interval: "soon"}).PollInterval(); err == nil {
		t.Fatal("accepted an unparsable interval")
	}
}
