//go:build archviolation

package store

import (
	_ "github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"    // allowed
	_ "github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope" // allowed
	_ "github.com/jackc/pgx/v5"                                           // allowed
)
