// Command agentarea is the open-core binary. Every role is a subcommand.
package main

import (
	"os"

	"github.com/agentarea/agentarea/agentarea-go/app"
)

func main() { os.Exit(app.Main(app.Default())) }
