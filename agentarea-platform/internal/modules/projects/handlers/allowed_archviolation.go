//go:build archviolation

package handlers

import (
	_ "github.com/agentarea/agentarea/agentarea-platform/internal/kernel/httpx"             // allowed
	_ "github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections/api"  // allowed
	_ "github.com/agentarea/agentarea/agentarea-platform/internal/modules/projects/service" // allowed
)
