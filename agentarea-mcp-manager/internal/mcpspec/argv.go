// Package mcpspec reads the parts of an MCP instance spec that decide what runs.
//
// The gate that admits an image and the code that starts it must agree on the
// argv, or admission judges one program and the host runs another. They read it
// from here for that reason: a spec shape understood by one and not the other is
// the bypass.
package mcpspec

// DockerArgv reads the invocation a docker-type spec asks for.
//
// Three shapes reach it, all in use: a list, a single string extended by args the
// way a command-type spec writes it, and the older "cmd" key. Whichever arrives,
// this is the argv the container starts with, so it is also the argv admission
// must judge.
//
// --transport=stdio is dropped whichever field carried it: the gateway reaches
// the container over a port, so a container talking stdio is unreachable.
func DockerArgv(jsonSpec map[string]any) []string {
	var argv []string
	// "cmd" is the older name for the same thing and the runtime prefers it, so
	// the gate has to read it the same way round: judging "command" while the
	// host runs "cmd" approves one program and starts another.
	for _, key := range []string{"cmd", "command"} {
		switch value := jsonSpec[key].(type) {
		case string:
			if value != "" {
				argv = append(argv, value)
			}
		case []any:
			argv = append(argv, StringList(value)...)
		default:
			continue
		}
		break
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
