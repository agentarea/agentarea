// Package static is the files main.py serves under /static (agentarea_api/static): the icons
// whose URLs the API emits for providers, MCP servers, channels and the platform's MCP identity.
package static

import (
	"embed"
	"io/fs"
)

//go:embed icons
var files embed.FS

// FS is the tree served at /static: icons/... .
func FS() fs.FS { return files }

// ProviderIcons is icons/providers.
func ProviderIcons() fs.FS {
	sub, err := fs.Sub(files, "icons/providers")
	if err != nil {
		panic(err)
	}
	return sub
}
