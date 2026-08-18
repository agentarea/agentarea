// data-plane-agent is an outbound-only connector; it never opens a listener.
package main

import (
	"context"
	"fmt"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/agentarea/mcp-manager/internal/connectorcomposition"
	"github.com/agentarea/mcp-manager/internal/connectorproto"
	"github.com/agentarea/mcp-manager/internal/connectortransport"
	"github.com/agentarea/mcp-manager/internal/dataplaneconnect"
)

var version = "dev"

func main() {
	if len(os.Args) < 2 {
		usage()
		os.Exit(2)
	}
	command := os.Args[1]
	if command == "version" {
		fmt.Println(version)
		return
	}
	dataplaneconnect.BuildVersion = version
	cfg, err := dataplaneconnect.LoadConfig(os.Args[2:])
	if err != nil {
		fmt.Fprintln(os.Stderr, "configuration error:", err)
		os.Exit(2)
	}
	client, err := dataplaneconnect.NewClient(cfg)
	if err != nil {
		fmt.Fprintln(os.Stderr, "configuration error:", err)
		os.Exit(2)
	}
	ctx, cancel := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer cancel()
	switch command {
	case "join":
		err = client.Join(ctx)
	case "doctor":
		err = client.Doctor(ctx)
	case "run":
		identity, identityErr := dataplaneconnect.ReadIdentity(cfg.IdentityFile)
		if identityErr != nil {
			err = identityErr
			break
		}
		runtime, composeErr := connectorcomposition.New(ctx, connectorcomposition.Config{
			DataPlaneID:          string(identity.DataPlaneID),
			MCPProvider:          cfg.MCPProvider,
			SandboxProvider:      cfg.SandboxProvider,
			KubernetesNamespace:  cfg.KubernetesNamespace,
			KubernetesKubeconfig: cfg.KubernetesKubeconfig,
			DockerRuntime:        cfg.DockerRuntime,
			DockerNetwork:        cfg.DockerNetwork,
			DockerNamePrefix:     cfg.DockerNamePrefix,
			DockerMaxContainers:  cfg.DockerMaxContainers,
			SandboxTaskLeaseTTL:  cfg.SandboxTaskLeaseTTL,
			SandboxStateRedisURL: cfg.SandboxStateRedisURL,
		}, connectorcomposition.Dependencies{})
		if composeErr != nil {
			err = composeErr
			break
		}
		runtime.SetErrorReporter(func(providerErr error) {
			fmt.Fprintln(os.Stderr, "provider operation:", dataplaneconnect.Redact(providerErr.Error()))
		})
		client.SetCapabilitySource(runtime)
		defer func() {
			shutdownCtx, shutdownCancel := context.WithTimeout(context.Background(), 15*time.Second)
			defer shutdownCancel()
			_ = runtime.Close(shutdownCtx)
		}()
		if cfg.ConnectorGatewayURL != "" {
			transport, transportErr := connectortransport.NewClient(connectortransport.ClientConfig{
				ControlPlaneURL:          cfg.ConnectorGatewayURL,
				DataPlaneID:              string(identity.DataPlaneID),
				ConnectorInstanceID:      string(identity.ConnectorInstanceID),
				NodeCredential:           identity.NodeCredential,
				ConnectorVersion:         cfg.AgentVersion,
				Capabilities:             transportCapabilities(runtime),
				MaxConcurrentOps:         16,
				AllowInsecureDevelopment: cfg.AllowInsecureDevelopment,
				OnSessionError: func(sessionErr error) {
					fmt.Fprintln(os.Stderr, "connector reconnect:", dataplaneconnect.Redact(sessionErr.Error()))
				},
			}, runtime.Dispatcher())
			if transportErr != nil {
				err = transportErr
				break
			}
			client.SetConnectorStream(transport)
		}
		err = client.Run(ctx)
	default:
		usage()
		os.Exit(2)
	}
	if err != nil {
		fmt.Fprintln(os.Stderr, "data-plane-agent:", dataplaneconnect.Redact(err.Error()))
		os.Exit(1)
	}
}

func transportCapabilities(runtime *connectorcomposition.Runtime) []connectorproto.Capability {
	mcp, sandbox := runtime.Capabilities()
	capabilities := make([]connectorproto.Capability, 0, 2)
	if mcp || sandbox {
		capabilities = append(capabilities, connectorproto.Capability_CAPABILITY_OPERATIONS)
	}
	if mcp {
		capabilities = append(capabilities, connectorproto.Capability_CAPABILITY_PROXY, connectorproto.Capability_CAPABILITY_MCP)
	}
	if sandbox {
		capabilities = append(capabilities, connectorproto.Capability_CAPABILITY_SANDBOX)
	}
	return capabilities
}
func usage() {
	fmt.Fprintln(os.Stderr, "usage: data-plane-agent <version|join|doctor|run> [flags]")
}
