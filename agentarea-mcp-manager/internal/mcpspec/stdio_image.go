package mcpspec

import "strings"

// ImageServesStdio reports whether a docker-type spec runs an image whose
// server speaks stdio, as its registry package declares. Such a container has
// no port for the gateway to reach, and mcp-base's bridge cannot run inside an
// image it did not build. A declared port overrides the package: the spec then
// says the image listens.
func ImageServesStdio(jsonSpec map[string]any) bool {
	if jsonSpec["port"] != nil {
		return false
	}
	image, _ := jsonSpec["image"].(string)
	packages, _ := jsonSpec["packages"].([]any)
	var images []map[string]any
	for _, raw := range packages {
		pkg, ok := raw.(map[string]any)
		if ok && pkg["registryType"] == "oci" {
			images = append(images, pkg)
		}
	}
	var chosen map[string]any
	for _, pkg := range images {
		identifier, _ := pkg["identifier"].(string)
		if identifier != "" && imageName(identifier) == imageName(image) {
			chosen = pkg
			break
		}
	}
	if chosen == nil && len(images) == 1 {
		chosen = images[0]
	}
	transport, _ := chosen["transport"].(map[string]any)
	return transport["type"] == "stdio"
}

// imageName drops an image reference's digest and tag, keeping a registry
// host's port.
func imageName(reference string) string {
	if at := strings.Index(reference, "@"); at >= 0 {
		reference = reference[:at]
	}
	if colon := strings.LastIndex(reference, ":"); colon > strings.LastIndex(reference, "/") {
		reference = reference[:colon]
	}
	return reference
}
