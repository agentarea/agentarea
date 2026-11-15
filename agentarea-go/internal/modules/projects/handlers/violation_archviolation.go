//go:build archviolation

package handlers

import (
	_ "database/sql"                                                                // want depguard
	_ "github.com/agentarea/agentarea/agentarea-go/internal/modules/agents/service" // want depguard
	_ "github.com/agentarea/agentarea/agentarea-go/internal/modules/agents/store"   // want depguard
	_ "github.com/agentarea/agentarea/agentarea-go/internal/profiles/cluster"       // want depguard
	_ "github.com/jackc/pgx/v5"                                                     // want depguard
)

var cache = map[string]int{} // want gochecknoglobals

func init() { cache["x"] = 1 } // want gochecknoinits
