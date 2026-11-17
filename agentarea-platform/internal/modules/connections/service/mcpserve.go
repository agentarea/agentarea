package service

import "log/slog"

// Log is the service's logger, for the MCP surfaces built beside it.
func (s *Service) Log() *slog.Logger { return s.d.Log }

// APIURL is the API's public base.
func (s *Service) APIURL() string { return s.d.APIURL }

// ClientEndpointReady reports the ports /mcp/clients/{id} needs: the client
// bundles, the graph (use on the client) and the effective tool policy.
func (s *Service) ClientEndpointReady() bool {
	return s.d.ClientBundles != nil && s.d.Graph != nil && s.d.Policies != nil
}

// ProxyReady reports the ports the per-instance proxy needs: the graph
// (use_connection) and the effective tool policy it judges calls by.
func (s *Service) ProxyReady() bool { return s.d.Graph != nil && s.d.Policies != nil }
