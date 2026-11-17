package app

import (
	"runtime/debug"
	"strings"
)

// buildVersion is the main module's version as the toolchain stamped it.
func buildVersion() string {
	if bi, ok := debug.ReadBuildInfo(); ok {
		return strings.TrimPrefix(bi.Main.Version, "v")
	}
	return "(unknown)"
}
