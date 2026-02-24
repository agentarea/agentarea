// Security utilities for activation service
package main

import (
	"fmt"
	"net/url"
	"os/exec"
	"path/filepath"
	"regexp"
	"strings"
)

// SecurityConfig holds security-related configuration
type SecurityConfig struct {
	// Allowed image registries (empty = allow all)
	AllowedRegistries []string
	// Blocked image patterns
	BlockedPatterns []string
	// Max image name length
	MaxImageNameLength int
}

// DefaultSecurityConfig returns default security configuration
func DefaultSecurityConfig() *SecurityConfig {
	return &SecurityConfig{
		AllowedRegistries: []string{
			"docker.io",
			"ghcr.io",
			"gcr.io",
			"registry.gitlab.com",
			"public.ecr.aws",
		},
		BlockedPatterns: []string{
			"..",           // Path traversal
			"${",           // Shell interpolation
			"`",            // Command substitution
			"|",            // Pipe
			";",            // Command separator
			"&&",           // Command chaining
			"||",           // Command chaining
		},
		MaxImageNameLength: 256,
	}
}

// ValidateImageName validates that the image name is safe
func ValidateImageName(image string) error {
	cfg := DefaultSecurityConfig()

	// Check length
	if len(image) > cfg.MaxImageNameLength {
		return fmt.Errorf("image name too long (max %d characters)", cfg.MaxImageNameLength)
	}

	// Check for blocked patterns
	for _, pattern := range cfg.BlockedPatterns {
		if strings.Contains(image, pattern) {
			return fmt.Errorf("image name contains forbidden pattern: %s", pattern)
		}
	}

	// Parse as Docker image reference
	if err := validateDockerImageRef(image); err != nil {
		return fmt.Errorf("invalid docker image reference: %w", err)
	}

	return nil
}

// validateDockerImageRef validates a Docker image reference
func validateDockerImageRef(image string) error {
	// Basic regex for Docker image reference
	// Format: [registry/]repository[:tag|@digest]
	// Allows: lowercase letters, digits, hyphens, underscores, periods
	// Allows: namespace/repository structure
	imageRefRegex := regexp.MustCompile(`^[a-z0-9][a-z0-9._-]*(?:/[a-z0-9][a-z0-9._-]*)*(?::[\w][\w.-]{0,127})?$|^([a-zA-Z0-9][a-zA-Z0-9-]*\.[a-zA-Z0-9][a-zA-Z0-9-]*(?:\.[a-zA-Z0-9][a-zA-Z0-9-]*)*)/[a-z0-9][a-z0-9._-]*(?:/[a-z0-9][a-z0-9._-]*)*(?::[\w][\w.-]{0,127})?$`)

	if !imageRefRegex.MatchString(image) {
		return fmt.Errorf("image name does not match valid docker reference pattern")
	}

	return nil
}

// ValidateHash validates the image hash is safe
func ValidateHash(hash string) error {
	// Only allow hex characters (for SHA256)
	hashRegex := regexp.MustCompile(`^[a-fA-F0-9]{64}$`)
	if !hashRegex.MatchString(hash) {
		return fmt.Errorf("invalid image hash format (expected SHA256 hex)")
	}
	return nil
}

// ValidateFilePath validates that a path is within the allowed directory
func ValidateFilePath(baseDir, targetPath string) error {
	// Clean and join the paths
	cleanBase := filepath.Clean(baseDir)
	cleanTarget := filepath.Clean(targetPath)

	// Ensure the target path starts with the base directory
	if !strings.HasPrefix(cleanTarget, cleanBase) {
		return fmt.Errorf("path traversal detected: %s is outside of %s", targetPath, baseDir)
	}

	return nil
}

// SanitizeCommandArg sanitizes a command argument
func SanitizeCommandArg(arg string) error {
	// Check for shell metacharacters
	dangerousChars := []string{
		";", "&", "|", "`", "$", "(", ")", "<", ">", "{", "}",
		"'", "\"", "\\", "\n", "\r",
	}

	for _, char := range dangerousChars {
		if strings.Contains(arg, char) {
			return fmt.Errorf("command argument contains dangerous character: %q", char)
		}
	}

	return nil
}

// ValidateCommandArgs validates all command arguments are safe
func ValidateCommandArgs(args []string) error {
	for i, arg := range args {
		if err := SanitizeCommandArg(arg); err != nil {
			return fmt.Errorf("invalid argument at position %d: %w", i, err)
		}
	}
	return nil
}

// BuildSkopeoCommand builds a safe skopeo command
func BuildSkopeoCommand(image, imagePath string) (*exec.Cmd, error) {
	// Validate image name
	if err := ValidateImageName(image); err != nil {
		return nil, err
	}

	// Build command with direct argument passing (not shell)
	cmd := exec.Command("skopeo", "copy",
		"docker://"+image,
		"docker-archive:"+imagePath,
	)

	return cmd, nil
}

// SafeCommand creates a command with validated name and arguments.
// exec.Command does NOT invoke a shell; all values are passed directly to execve,
// so shell metacharacters in any string are inert.
//
// Call sites:
//   - Chroot path: name is the literal "chroot" — not user-controlled.
//   - Fallback path (Kata VMs): name is imageConfig.Entrypoint[0], read from the
//     hash-verified image's config.json on disk — not from the HTTP request.
func SafeCommand(name string, args ...string) (*exec.Cmd, error) {
	if err := SanitizeCommandArg(name); err != nil {
		return nil, fmt.Errorf("invalid command name: %w", err)
	}
	if err := ValidateCommandArgs(args); err != nil {
		return nil, err
	}
	return exec.Command(name, args...), nil // nosemgrep: go.lang.security.audit.dangerous-exec-command.dangerous-exec-command // lgtm[go/command-injection]
}

// ValidateManifestPath validates that a manifest path is safe
func ValidateManifestPath(manifestPath string) error {
	// Only allow filenames, not paths
	if strings.Contains(manifestPath, "/") || strings.Contains(manifestPath, "\\") {
		return fmt.Errorf("manifest path must be a filename, not a path")
	}

	// Check for path traversal attempts
	if strings.Contains(manifestPath, "..") {
		return fmt.Errorf("manifest path contains path traversal")
	}

	return nil
}

// ValidateLayerPath validates a layer path from manifest
func ValidateLayerPath(layerPath string) error {
	// Layer paths should be relative and not escape the directory
	if filepath.IsAbs(layerPath) {
		return fmt.Errorf("layer path must be relative")
	}

	cleanPath := filepath.Clean(layerPath)
	if strings.HasPrefix(cleanPath, "..") {
		return fmt.Errorf("layer path escapes extraction directory")
	}

	return nil
}

// ValidatePort validates that a port number is in valid range
func ValidatePort(port int) error {
	if port <= 0 || port > 65535 {
		return fmt.Errorf("port must be between 1 and 65535")
	}
	return nil
}

// IsValidURL validates a URL is safe
func IsValidURL(urlStr string) bool {
	u, err := url.Parse(urlStr)
	if err != nil {
		return false
	}

	// Only allow http and https
	if u.Scheme != "http" && u.Scheme != "https" {
		return false
	}

	// Block URLs with userinfo
	if u.User != nil {
		return false
	}

	return true
}

// ValidateHealthCheckPath validates a health check path is safe
// This prevents SSRF attacks via malicious health check paths
func ValidateHealthCheckPath(path string) error {
	if path == "" {
		return nil // Empty path is valid (means use TCP check)
	}

	// Path must start with /
	if !strings.HasPrefix(path, "/") {
		return fmt.Errorf("health check path must start with /")
	}

	// Block path traversal attempts
	if strings.Contains(path, "..") {
		return fmt.Errorf("health check path contains path traversal")
	}

	// Block null bytes
	if strings.Contains(path, "\x00") {
		return fmt.Errorf("health check path contains null bytes")
	}

	// Only allow safe characters in path
	// Allow: alphanumeric, /, -, _, ., ~, ?, =, &
	safePathPattern := regexp.MustCompile(`^[a-zA-Z0-9/_.~?=&-]+$`)
	if !safePathPattern.MatchString(path) {
		return fmt.Errorf("health check path contains invalid characters")
	}

	// Block potential protocol-relative URLs
	if strings.HasPrefix(path, "//") {
		return fmt.Errorf("health check path cannot start with //")
	}

	return nil
}

