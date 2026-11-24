//go:build archviolation

package workflows

import (
	_ "github.com/agentarea/agentarea/agentarea-platform/internal/kernel/durable"            // allowed
	_ "github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections/api"   // allowed
	_ "github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections/store" // want depguard
	_ "go.temporal.io/sdk/workflow"                                                    // allowed
)
