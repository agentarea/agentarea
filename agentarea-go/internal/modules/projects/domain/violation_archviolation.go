//go:build archviolation

package domain

import (
	_ "database/sql"                                                                 // want depguard
	_ "github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"            // want depguard
	_ "github.com/agentarea/agentarea/agentarea-go/internal/modules/catalog/service" // want depguard
	_ "github.com/agentarea/agentarea/agentarea-go/internal/modules/projects/api"    // allowed
	_ "strings"                                                                      // allowed
)
