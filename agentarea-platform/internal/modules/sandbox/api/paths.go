package api

import (
	"slices"
	"strings"
)

// ReservedRoots are the store's own top folders under a workspace: task files,
// upload staging, events and the trash. They are not workspace files.
func ReservedRoots() []string { return []string{"tasks", "staging", "events", ".trash"} }

// IsReservedPath is true for a path under one of ReservedRoots.
func IsReservedPath(p string) bool {
	for _, seg := range strings.Split(strings.TrimLeft(p, "/"), "/") {
		if seg == "" || seg == "." {
			continue
		}
		return slices.Contains(ReservedRoots(), seg)
	}
	return false
}
