// Package mcpspec reads the parts of an MCP instance spec that decide what runs.
//
// The gate that admits an image and the code that starts it must agree on the
// argv, or admission judges one program and the host runs another. They read it
// from here for that reason: a spec shape understood by one and not the other is
// the bypass.
package mcpspec

// DockerArgv reads the invocation a docker-type spec asks for. The command
// arrives either as a list or, exactly as a command-type spec writes it, as a
// single string extended by args -- the catalog produces both shapes.
//
// --transport=stdio is dropped whichever field carried it: the gateway reaches
// the container over a port, so a container talking stdio is unreachable.
func DockerArgv(jsonSpec map[string]any) []string {
	var argv []string
	switch command := jsonSpec["command"].(type) {
	case string:
		if command != "" {
			argv = append(argv, command)
		}
	case []any:
		argv = append(argv, StringList(command)...)
	}
	argv = append(argv, StringList(jsonSpec["args"])...)

	kept := make([]string, 0, len(argv))
	for _, arg := range argv {
		if arg != "--transport=stdio" {
			kept = append(kept, arg)
		}
	}
	if len(kept) == 0 {
		return nil
	}
	return kept
}

// StringList reads a JSON array of strings, skipping anything else.
func StringList(raw any) []string {
	items, ok := raw.([]any)
	if !ok {
		return nil
	}
	out := make([]string, 0, len(items))
	for _, item := range items {
		if value, ok := item.(string); ok {
			out = append(out, value)
		}
	}
	if len(out) == 0 {
		return nil
	}
	return out
}
