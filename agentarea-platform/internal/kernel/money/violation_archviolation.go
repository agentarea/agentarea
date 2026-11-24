//go:build archviolation

package money

import (
	_ "github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"         // allowed
	_ "github.com/agentarea/agentarea/agentarea-platform/internal/modules/projects/api" // want depguard
)
