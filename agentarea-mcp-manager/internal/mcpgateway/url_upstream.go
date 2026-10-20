package mcpgateway

import (
	"errors"
	"fmt"
	"log/slog"
	"net/http"
	"net/http/httputil"
	"net/url"
	"strings"

	"github.com/agentarea/mcp-manager/internal/egress"
)

const managedByPlatform = "platform"

// forwardedURLHeaders are the caller's MCP protocol headers, the only ones a
// URL server receives from it; Mcp-* headers pass as well. The caller's own
// Authorization and Cookie belong to this hop, not to the member's server.
var forwardedURLHeaders = map[string]bool{"Accept": true, "Content-Type": true, "Last-Event-Id": true}

// serveURL proxies to a URL MCP server. There is no workload, so nothing here
// touches the lifecycle; the instance's credentials are added on the way out
// and never leave this process otherwise.
func (g *Gateway) serveURL(response http.ResponseWriter, request *http.Request, instanceID string, server *URLServer) {
	if server.AuthConfigID != "" {
		http.Error(response, "MCP instance authenticates through an auth config, which the gateway does not resolve", http.StatusConflict)
		return
	}
	if server.ManagedBy == managedByPlatform {
		http.Error(response, "MCP instance is a platform-managed connection, which the gateway does not proxy", http.StatusConflict)
		return
	}
	target, err := url.Parse(server.EndpointURL)
	if err != nil || (target.Scheme != "http" && target.Scheme != "https") || target.Host == "" {
		http.Error(response, "MCP instance has no http(s) endpoint_url", http.StatusBadGateway)
		return
	}
	headers, err := g.urlHeaders(instanceID, server)
	if err != nil {
		g.logger.Error("MCP instance credentials could not be resolved", slog.String("instance_id", instanceID), slog.String("error", err.Error()))
		http.Error(response, "MCP instance credentials could not be resolved", http.StatusBadGateway)
		return
	}

	proxy := &httputil.ReverseProxy{
		Transport:     g.urlTransport,
		FlushInterval: -1,
		Rewrite: func(outbound *httputil.ProxyRequest) {
			outbound.SetURL(target)
			outbound.Out.URL.Path = target.Path
			outbound.Out.URL.RawPath = target.RawPath
			outbound.Out.URL.RawQuery = target.RawQuery
			forwarded := http.Header{}
			for name, values := range outbound.In.Header {
				if forwardedURLHeaders[name] || strings.HasPrefix(name, "Mcp-") {
					forwarded[name] = values
				}
			}
			for name, value := range headers {
				forwarded.Set(name, value)
			}
			outbound.Out.Header = forwarded
		},
		ModifyResponse: func(upstreamResponse *http.Response) error {
			upstreamResponse.Header.Del(StartingHeader)
			upstreamResponse.Header.Del(StartFailureHeader)
			// A member's server must not set cookies on the platform's origin.
			upstreamResponse.Header.Del("Set-Cookie")
			return nil
		},
		ErrorHandler: func(writer http.ResponseWriter, _ *http.Request, proxyErr error) {
			g.logger.Warn("MCP URL upstream request failed", slog.String("instance_id", instanceID), slog.String("error", proxyErr.Error()))
			var refused *egress.PrivateAddressError
			if errors.As(proxyErr, &refused) {
				http.Error(writer, refused.Error(), http.StatusForbidden)
				return
			}
			http.Error(writer, "MCP upstream request failed", http.StatusBadGateway)
		},
	}
	proxy.ServeHTTP(response, request)
}

// urlHeaders mirrors MCPServerInstanceService._outbound_headers: the plain
// headers, then every secret the instance names, which wins over a plain one.
func (g *Gateway) urlHeaders(instanceID string, server *URLServer) (map[string]string, error) {
	headers := make(map[string]string, len(server.Headers)+len(server.EnvVars))
	for name, value := range server.Headers {
		headers[name] = value
	}
	if len(server.EnvVars) == 0 {
		return headers, nil
	}
	resolved, err := g.urlSecrets.ResolveInstanceEnvVars(instanceID, server.EnvVars)
	if err != nil {
		return nil, err
	}
	for _, name := range server.EnvVars {
		value, ok := resolved[name]
		if !ok {
			return nil, fmt.Errorf("secret header %q was not resolved", name)
		}
		headers[name] = value
	}
	return headers, nil
}
