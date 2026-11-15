//go:build archviolation

package money

import (
	_ "github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"         // allowed
	_ "github.com/agentarea/agentarea/agentarea-go/internal/modules/projects/api" // want depguard
)
