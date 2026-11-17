//go:build archviolation

package domain

import (
	_ "database/sql"                                                                 // want depguard
	_ "github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"            // want depguard
	_ "github.com/agentarea/agentarea/agentarea-platform/internal/modules/catalog/service" // want depguard
	_ "github.com/agentarea/agentarea/agentarea-platform/internal/modules/projects/api"    // allowed
	_ "strings"                                                                      // allowed
)
