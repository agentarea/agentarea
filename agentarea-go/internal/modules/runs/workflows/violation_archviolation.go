//go:build archviolation

package workflows

import (
	_ "github.com/agentarea/agentarea/agentarea-go/internal/kernel/durable"            // allowed
	_ "github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/api"   // allowed
	_ "github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/store" // want depguard
	_ "go.temporal.io/sdk/workflow"                                                    // allowed
)
