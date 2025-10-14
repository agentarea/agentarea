package secrets

import (
	"context"
	"crypto/aes"
	"crypto/cipher"
	"crypto/hmac"
	"crypto/sha256"
	"database/sql"
	"encoding/base64"
	"errors"
	"fmt"
	"log/slog"
	"os"
	"strings"
	"time"

	_ "github.com/jackc/pgx/v5/stdlib" // PostgreSQL driver
)

// DatabaseSecretResolver retrieves secrets from PostgreSQL database
type DatabaseSecretResolver struct {
	db     *sql.DB
	logger *slog.Logger
	key    []byte // Fernet encryption key
}

// NewDatabaseSecretResolver creates a resolver that reads from PostgreSQL
func NewDatabaseSecretResolver(logger *slog.Logger) (*DatabaseSecretResolver, error) {
	// Get database connection string from environment
	dbHost := os.Getenv("POSTGRES_HOST")
	if dbHost == "" {
		dbHost = "db"
	}
	dbPort := os.Getenv("POSTGRES_PORT")
	if dbPort == "" {
		dbPort = "5432"
	}
	dbUser := os.Getenv("POSTGRES_USER")
	if dbUser == "" {
		return nil, errors.New("POSTGRES_USER environment variable is required")
	}
	dbPassword := os.Getenv("POSTGRES_PASSWORD")
	if dbPassword == "" {
		return nil, errors.New("POSTGRES_PASSWORD environment variable is required")
	}
	dbName := os.Getenv("POSTGRES_DB")
	if dbName == "" {
		dbName = "aiagents"
	}

	// Get encryption key from environment
	encryptionKey := os.Getenv("SECRET_MANAGER_ENCRYPTION_KEY")
	if encryptionKey == "" {
		logger.Warn("SECRET_MANAGER_ENCRYPTION_KEY not set, secrets will not be decryptable")
		return nil, errors.New("SECRET_MANAGER_ENCRYPTION_KEY is required for database secret manager")
	}

	// Fernet key is already 32 bytes base64url-encoded, decode it
	keyBytes, err := base64.URLEncoding.DecodeString(encryptionKey)
	if err != nil {
		return nil, fmt.Errorf("failed to decode encryption key: %w", err)
	}

	// Verify key length (Fernet requires exactly 32 bytes)
	if len(keyBytes) != 32 {
		return nil, fmt.Errorf("invalid Fernet key length: got %d bytes, expected 32", len(keyBytes))
	}

	// Build connection string
	connStr := fmt.Sprintf(
		"postgres://%s:%s@%s:%s/%s?sslmode=disable",
		dbUser, dbPassword, dbHost, dbPort, dbName,
	)

	// Connect to database
	db, err := sql.Open("pgx", connStr)
	if err != nil {
		return nil, fmt.Errorf("failed to connect to database: %w", err)
	}

	// Test connection
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	if err := db.PingContext(ctx); err != nil {
		return nil, fmt.Errorf("failed to ping database: %w", err)
	}

	logger.Info("Initialized database secret resolver",
		slog.String("db_host", dbHost),
		slog.String("db_name", dbName))

	return &DatabaseSecretResolver{
		db:     db,
		logger: logger,
		key:    keyBytes,
	}, nil
}

// ResolveSecrets resolves all secrets for an MCP instance from database
func (dr *DatabaseSecretResolver) ResolveSecrets(instanceID string, envVars map[string]string) (map[string]string, error) {
	resolved := make(map[string]string)

	for key, value := range envVars {
		// Check if this is a secret reference or a plain value
		if strings.HasPrefix(value, "secret_ref:") {
			// This is a secret reference, resolve it from database
			secretName := strings.TrimPrefix(value, "secret_ref:")
			secretValue, err := dr.getSecretFromDatabase(instanceID, secretName)
			if err != nil {
				dr.logger.Error("Failed to resolve secret from database",
					slog.String("instance_id", instanceID),
					slog.String("secret_key", key),
					slog.String("secret_name", secretName),
					slog.String("error", err.Error()))
				return nil, fmt.Errorf("failed to resolve secret %s: %w", key, err)
			}
			resolved[key] = secretValue
		} else {
			// This is a plain value, use as-is
			resolved[key] = value
		}
	}

	dr.logger.Debug("Resolved secrets for instance from database",
		slog.String("instance_id", instanceID),
		slog.Int("total_vars", len(envVars)),
		slog.Int("resolved_secrets", len(resolved)))

	return resolved, nil
}

// getSecretFromDatabase retrieves and decrypts a secret from PostgreSQL
func (dr *DatabaseSecretResolver) getSecretFromDatabase(instanceID, secretName string) (string, error) {
	// Use the same secret key pattern as Python:
	// mcp_instance_{instance_id}_{env_name}
	fullSecretName := fmt.Sprintf("mcp_instance_%s_%s", instanceID, secretName)

	dr.logger.Debug("Retrieving secret from database",
		slog.String("instance_id", instanceID),
		slog.String("secret_name", secretName),
		slog.String("full_secret_name", fullSecretName))

	// Query database for the encrypted secret by full secret name
	var encryptedValue string
	query := `SELECT encrypted_value FROM encrypted_secrets WHERE secret_name = $1 LIMIT 1`

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	err := dr.db.QueryRowContext(ctx, query, fullSecretName).Scan(&encryptedValue)
	if err == sql.ErrNoRows {
		return "", fmt.Errorf("secret not found: %s", fullSecretName)
	}
	if err != nil {
		return "", fmt.Errorf("database query failed: %w", err)
	}

	// Decrypt the secret using Fernet
	decryptedValue, err := dr.fernetDecrypt(encryptedValue)
	if err != nil {
		return "", fmt.Errorf("failed to decrypt secret: %w", err)
	}

	dr.logger.Info("Successfully retrieved secret from database",
		slog.String("instance_id", instanceID),
		slog.String("secret_name", secretName))

	return decryptedValue, nil
}

// fernetDecrypt decrypts a Fernet-encrypted string
// Fernet format: Version (1 byte) | Timestamp (8 bytes) | IV (16 bytes) | Ciphertext | HMAC (32 bytes)
func (dr *DatabaseSecretResolver) fernetDecrypt(encryptedData string) (string, error) {
	// Decode base64
	data, err := base64.URLEncoding.DecodeString(encryptedData)
	if err != nil {
		return "", fmt.Errorf("base64 decode failed: %w", err)
	}

	// Validate minimum length
	if len(data) < 57 { // 1 + 8 + 16 + 32 = 57 minimum
		return "", errors.New("encrypted data too short")
	}

	// Parse Fernet token structure
	version := data[0]
	if version != 0x80 {
		return "", fmt.Errorf("unsupported Fernet version: %x", version)
	}

	// Extract components
	// timestamp := data[1:9]   // Not used for decryption
	iv := data[9:25]
	ciphertext := data[25 : len(data)-32]
	mac := data[len(data)-32:]

	// Verify HMAC
	signingKey := dr.deriveSigningKey()
	h := hmac.New(sha256.New, signingKey)
	h.Write(data[:len(data)-32])
	expectedMAC := h.Sum(nil)
	if !hmac.Equal(mac, expectedMAC) {
		return "", errors.New("HMAC verification failed")
	}

	// Decrypt using AES-128-CBC
	encryptionKey := dr.deriveEncryptionKey()
	block, err := aes.NewCipher(encryptionKey)
	if err != nil {
		return "", fmt.Errorf("failed to create cipher: %w", err)
	}

	mode := cipher.NewCBCDecrypter(block, iv)
	plaintext := make([]byte, len(ciphertext))
	mode.CryptBlocks(plaintext, ciphertext)

	// Remove PKCS7 padding
	plaintext, err = dr.removePKCS7Padding(plaintext)
	if err != nil {
		return "", fmt.Errorf("failed to remove padding: %w", err)
	}

	return string(plaintext), nil
}

// deriveSigningKey derives the signing key from Fernet key
func (dr *DatabaseSecretResolver) deriveSigningKey() []byte {
	// Fernet uses the first 16 bytes for signing
	return dr.key[:16]
}

// deriveEncryptionKey derives the encryption key from Fernet key
func (dr *DatabaseSecretResolver) deriveEncryptionKey() []byte {
	// Fernet uses the last 16 bytes for encryption
	return dr.key[16:]
}

// removePKCS7Padding removes PKCS7 padding from decrypted data
func (dr *DatabaseSecretResolver) removePKCS7Padding(data []byte) ([]byte, error) {
	if len(data) == 0 {
		return nil, errors.New("empty data")
	}

	paddingLen := int(data[len(data)-1])
	if paddingLen > len(data) || paddingLen == 0 {
		return nil, errors.New("invalid padding")
	}

	// Verify padding
	for i := len(data) - paddingLen; i < len(data); i++ {
		if data[i] != byte(paddingLen) {
			return nil, errors.New("invalid padding bytes")
		}
	}

	return data[:len(data)-paddingLen], nil
}

// Close closes the database connection
func (dr *DatabaseSecretResolver) Close() error {
	dr.logger.Info("Closing database secret resolver")
	if dr.db != nil {
		return dr.db.Close()
	}
	return nil
}
