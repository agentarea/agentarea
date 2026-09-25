package main

import (
	"context"
	"os"
	"os/signal"
	"syscall"

	"github.com/agentarea/mcp-manager/internal/config"
	"github.com/agentarea/mcp-manager/internal/managerapp"
)

func main() {
	cfg := config.Load()
	logger := managerapp.NewLogger(cfg)
	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	err := managerapp.Run(ctx, cfg, logger, managerapp.Options{})
	stop()
	if err != nil {
		os.Exit(1)
	}
}
