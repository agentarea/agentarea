package database

import (
	"fmt"
	"log/slog"
	"os"
)

// BuildConnStr builds a PostgreSQL connection string.
// It prefers AGENTAREA_DB_URL if set, otherwise constructs from individual env vars.
// Returns an empty string if required credentials (user/password) are missing.
func BuildConnStr(logger *slog.Logger) string {
	// Prefer AGENTAREA_DB_URL if available (already includes sslmode)
	if connStr := os.Getenv("AGENTAREA_DB_URL"); connStr != "" {
		logger.Info("Using AGENTAREA_DB_URL for PostgreSQL connection")
		return connStr
	}

	// Fall back to constructing from individual env vars
	dbHost := os.Getenv("AGENTAREA_DB_HOST")
	if dbHost == "" {
		dbHost = "db"
	}
	dbPort := os.Getenv("AGENTAREA_DB_PORT")
	if dbPort == "" {
		dbPort = "5432"
	}
	dbUser := os.Getenv("AGENTAREA_DB_USER")
	dbPassword := os.Getenv("AGENTAREA_DB_PASSWORD")
	if dbUser == "" || dbPassword == "" {
		return ""
	}
	dbName := os.Getenv("AGENTAREA_DB_NAME")
	if dbName == "" {
		dbName = "agentarea"
	}

	sslMode := os.Getenv("AGENTAREA_DB_SSLMODE")
	if sslMode == "" {
		sslMode = "prefer"
	}

	return fmt.Sprintf("postgres://%s:%s@%s:%s/%s?sslmode=%s",
		dbUser, dbPassword, dbHost, dbPort, dbName, sslMode)
}
