//go:build archviolation

package store

import (
	_ "github.com/agentarea/agentarea/agentarea-go/internal/kernel/db"    // allowed
	_ "github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope" // allowed
	_ "github.com/jackc/pgx/v5"                                           // allowed
)
