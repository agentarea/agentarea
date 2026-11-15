//go:build archviolation

package handlers

import (
	_ "github.com/agentarea/agentarea/agentarea-go/internal/kernel/httpx"             // allowed
	_ "github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/api"  // allowed
	_ "github.com/agentarea/agentarea/agentarea-go/internal/modules/projects/service" // allowed
)
