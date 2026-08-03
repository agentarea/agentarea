package main

import (
	"context"
	"io"
	"log/slog"
	"testing"
	"time"

	"github.com/agentarea/mcp-manager/internal/config"
	"github.com/agentarea/mcp-manager/internal/workspace"
)

func TestGetDurationEnvRejectsMalformedValue(t *testing.T) {
	t.Setenv("TEST_DURATION", "not-a-duration")

	if _, err := getDurationEnv("TEST_DURATION", time.Minute); err == nil {
		t.Fatal("expected malformed duration to fail closed")
	}
}

func TestGetDurationEnvUsesExplicitValue(t *testing.T) {
	t.Setenv("TEST_DURATION", "45s")

	got, err := getDurationEnv("TEST_DURATION", time.Minute)
	if err != nil {
		t.Fatalf("parse duration: %v", err)
	}
	if got != 45*time.Second {
		t.Fatalf("duration = %s, want 45s", got)
	}
}

func TestEmbeddedRunnerRejectsMalformedEnableFlagBeforeInitialization(t *testing.T) {
	t.Setenv("SANDBOX_EMBEDDED_RUNNER", "sometimes")
	logger := slog.New(slog.NewTextHandler(io.Discard, nil))

	err := startEmbeddedSandboxRunner(
		context.Background(),
		&config.Config{},
		nil,
		"test",
		workspace.RepositoryConfig{},
		logger,
	)
	if err == nil {
		t.Fatal("expected malformed enable flag to fail closed")
	}
}
