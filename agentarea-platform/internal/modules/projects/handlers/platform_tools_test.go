package handlers

import (
	"context"
	"strings"
	"testing"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authn"
)

func TestPlatformProjectsValidateBeforeWriting(t *testing.T) {
	tools := PlatformTools{}
	_, err := tools.Create(context.Background(), authn.Caller{}, []byte(`{"name":""}`))
	if err == nil || !strings.HasPrefix(err.Error(), "1 validation error for ProjectCreate\nname\n") {
		t.Fatalf("create: %v", err)
	}
	if _, err := tools.Get(context.Background(), authn.Caller{}, "nope"); err == nil || err.Error() != "badly formed hexadecimal UUID string" {
		t.Fatalf("get: %v", err)
	}
	if err := tools.Link(context.Background(), authn.Caller{}, "folder", "p", "c"); err == nil {
		t.Fatal("link of an unknown kind")
	}
}

// int32(offset) wrapped a page past 2^31 back to the start.
func TestPlatformProjectsRefuseAPageInt32CannotHold(t *testing.T) {
	for _, page := range [][2]int{{50, 1 << 32}, {1 << 32, 0}, {50, -1}} {
		if _, err := (PlatformTools{}).List(context.Background(), authn.Caller{}, page[0], page[1]); err == nil {
			t.Fatalf("limit %d offset %d was accepted", page[0], page[1])
		}
	}
}
