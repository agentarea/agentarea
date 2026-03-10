package database

import (
	"fmt"
	"log/slog"
	"os"
)

// BuildConnStr builds a PostgreSQL connection string.
// It prefers DATABASE_URL if set, otherwise constructs from individual env vars.
// Returns an empty string if required credentials (user/password) are missing.
func BuildConnStr(logger *slog.Logger) string {
	// Prefer DATABASE_URL if available (already includes sslmode)
	if connStr := os.Getenv("DATABASE_URL"); connStr != "" {
		logger.Info("Using DATABASE_URL for PostgreSQL connection")
		return connStr
	}

	// Fall back to constructing from individual env vars
	dbHost := os.Getenv("POSTGRES_HOST")
	if dbHost == "" {
		dbHost = "db"
	}
	dbPort := os.Getenv("POSTGRES_PORT")
	if dbPort == "" {
		dbPort = "5432"
	}
	dbUser := os.Getenv("POSTGRES_USER")
	dbPassword := os.Getenv("POSTGRES_PASSWORD")
	if dbUser == "" || dbPassword == "" {
		return ""
	}
	dbName := os.Getenv("POSTGRES_DB")
	if dbName == "" {
		dbName = "aiagents"
	}

	sslMode := os.Getenv("POSTGRES_SSLMODE")
	if sslMode == "" {
		sslMode = "prefer"
	}

	return fmt.Sprintf("postgres://%s:%s@%s:%s/%s?sslmode=%s",
		dbUser, dbPassword, dbHost, dbPort, dbName, sslMode)
}
