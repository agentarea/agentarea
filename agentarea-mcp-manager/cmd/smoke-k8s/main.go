package main

import (
	"context"
	"encoding/json"
	"fmt"
	"log/slog"
	"os"

	"github.com/agentarea/mcp-manager/internal/backends"
	"github.com/agentarea/mcp-manager/internal/config"
)

func main() {
	logger := slog.New(slog.NewTextHandler(os.Stderr, &slog.HandlerOptions{Level: slog.LevelInfo}))

	cfg := config.Load()
	logger.Info("loaded", "namespace", cfg.Kubernetes.Namespace, "domain", cfg.Kubernetes.Domain)

	b, err := backends.NewKubernetesBackend(cfg, logger)
	if err != nil {
		logger.Error("backend init", "err", err)
		os.Exit(1)
	}

	spec := &backends.InstanceSpec{
		InstanceID:  "11111111-1111-1111-1111-111111111111",
		Name:        "smoke-test",
		ServiceName: "11111111-1111-1111-1111-111111111111",
		Image:       "nginx:alpine",
		Port:        80,
		WorkspaceID: "default",
	}

	ctx := context.Background()
	result, err := b.CreateInstance(ctx, spec)
	if err != nil {
		logger.Error("create", "err", err)
		os.Exit(1)
	}
	buf, _ := json.MarshalIndent(result, "", "  ")
	fmt.Println(string(buf))
}
