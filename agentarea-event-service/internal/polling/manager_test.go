package polling

import (
	"testing"

	"github.com/agentarea/event-service/internal/trigger"
)

func TestRunningPollerServesOnlyItsConfig(t *testing.T) {
	p := &runningPoller{
		extractor: "telegram_polling",
		config:    map[string]any{"bot_token": "123:OLD"},
	}

	same := trigger.Trigger{
		DataExtractor:       "telegram_polling",
		DataExtractorConfig: map[string]any{"bot_token": "123:OLD"},
		DataExtractorState:  map[string]any{"offset": float64(42)},
	}
	if !p.serves(same) {
		t.Fatal("poller does not serve its own config; an offset change must not restart it")
	}

	rotated := same
	rotated.DataExtractorConfig = map[string]any{"bot_token": "123:NEW"}
	if p.serves(rotated) {
		t.Fatal("poller serves a rotated bot_token; it must restart")
	}
}
