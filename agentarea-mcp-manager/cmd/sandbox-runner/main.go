package main

import (
	"context"
	"os"
	"os/signal"
	"syscall"

	"github.com/agentarea/mcp-manager/internal/config"
	"github.com/agentarea/mcp-manager/internal/runnerapp"
)

func main() {
	cfg := config.Load()
	logger := runnerapp.NewLogger(cfg)
	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	err := runnerapp.Run(ctx, cfg, logger, nil)
	stop()
	if err != nil {
		os.Exit(1)
	}
}
