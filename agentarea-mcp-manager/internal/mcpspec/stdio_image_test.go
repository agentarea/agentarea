package mcpspec

import "testing"

func ociPackage(identifier, transport string) map[string]any {
	return map[string]any{
		"registryType": "oci",
		"identifier":   identifier,
		"transport":    map[string]any{"type": transport},
	}
}

func TestImageServesStdio(t *testing.T) {
	for name, tc := range map[string]struct {
		spec map[string]any
		want bool
	}{
		"its package speaks stdio": {
			spec: map[string]any{"image": "mcp/fetch", "packages": []any{ociPackage("mcp/fetch", "stdio")}},
			want: true,
		},
		"tag and registry host on the image": {
			spec: map[string]any{
				"image":    "docker.io/vendor/server:latest",
				"packages": []any{ociPackage("docker.io/vendor/server", "stdio")},
			},
			want: true,
		},
		"the only image package names another tag": {
			spec: map[string]any{"image": "vendor/server:2", "packages": []any{ociPackage("vendor/server:1", "stdio")}},
			want: true,
		},
		"its package serves HTTP": {
			spec: map[string]any{"image": "vendor/server:1", "packages": []any{ociPackage("vendor/server:1", "streamable-http")}},
		},
		"a port says it listens": {
			spec: map[string]any{
				"image": "mcp/fetch", "port": float64(8000),
				"packages": []any{ociPackage("mcp/fetch", "stdio")},
			},
		},
		"a null port is no port": {
			spec: map[string]any{
				"image": "mcp/fetch", "port": nil,
				"packages": []any{ociPackage("mcp/fetch", "stdio")},
			},
			want: true,
		},
		"no packages": {
			spec: map[string]any{"image": "vendor/server:1"},
		},
		"only npm packages speak stdio": {
			spec: map[string]any{"image": "vendor/server:1", "packages": []any{map[string]any{
				"registryType": "npm", "identifier": "server", "transport": map[string]any{"type": "stdio"},
			}}},
		},
	} {
		t.Run(name, func(t *testing.T) {
			if got := ImageServesStdio(tc.spec); got != tc.want {
				t.Fatalf("ImageServesStdio() = %v, want %v", got, tc.want)
			}
		})
	}
}
