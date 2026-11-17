package main

import (
	"context"
	"os/exec"
	"testing"
	"time"
)

func TestRunStoppableEndsTheSupervisorGracefullyWhenTheCallerStops(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	// Stands in for the supervisor: it exits cleanly only if it gets SIGTERM.
	command := exec.CommandContext(ctx, "/bin/sh", "-c", `trap 'exit 0' TERM; while :; do sleep 0.05; done`)
	done := make(chan error, 1)
	go func() { done <- runStoppable(ctx, command) }()
	time.Sleep(200 * time.Millisecond)
	cancel()

	select {
	case err := <-done:
		if err != nil {
			t.Fatalf("runStoppable() error = %v, want a clean stop", err)
		}
	case <-time.After(10 * time.Second):
		t.Fatal("the supervisor was not stopped")
	}
}

func TestRunStoppableReportsASupervisorThatFailsWithoutACancel(t *testing.T) {
	command := exec.Command("/bin/sh", "-c", "exit 3")
	if err := runStoppable(context.Background(), command); err == nil {
		t.Fatal("runStoppable() error = nil, want the supervisor's failure")
	}
}
