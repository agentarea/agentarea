package database

import (
	"fmt"
	"log/slog"
	"os"
	"strings"
)

// BuildConnStr builds a PostgreSQL connection string from the AGENTAREA_DB_*
// variables every AgentArea service reads. Returns an empty string if the
// credentials (user/password) are missing.
func BuildConnStr(logger *slog.Logger) string {
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

	logger.Info("Using PostgreSQL connection", slog.String("host", dbHost), slog.String("database", dbName))
	return fmt.Sprintf("host=%s port=%s user=%s password=%s dbname=%s sslmode=%s",
		connValue(dbHost), connValue(dbPort), connValue(dbUser),
		connValue(dbPassword), connValue(dbName), connValue(sslMode))
}

// connValue quotes a keyword/value connection string value, so a password
// containing spaces, quotes or URL syntax survives intact.
func connValue(value string) string {
	escaped := strings.ReplaceAll(value, `\`, `\\`)
	escaped = strings.ReplaceAll(escaped, `'`, `\'`)
	return "'" + escaped + "'"
}
