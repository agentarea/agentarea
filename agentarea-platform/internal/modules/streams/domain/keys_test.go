package domain_test

import (
	"testing"

	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/streams/domain"
)

func TestUUID5MatchesPython(t *testing.T) {
	got, err := domain.UUID5("6ba7b810-9dad-11d1-80b4-00c04fd430c8", "python.org")
	if err != nil || got != "886313e1-3b8a-5372-9b90-0c9aee199e5d" {
		t.Fatalf("uuid5 = %s, %v", got, err)
	}
	if id := domain.EventIDFor("6f1c7b8e-3d2a-4f5e-9b0c-1a2b3c4d5e6f", "k"); len(id) != 36 {
		t.Fatalf("event id = %s", id)
	}
}
