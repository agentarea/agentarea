package domain

import "time"

// OAuthLink is an mcp_oauth_links row (the grant side: no route consumes it).
type OAuthLink struct {
	ID             string
	WorkspaceID    string
	CreatedBy      string
	MCPInstanceID  string
	Token          string
	AccessControl  string
	ProviderConfig map[string]any
	IsActive       bool
	ExpiresAt      *time.Time
	AccessCount    int32
	LastAccessedAt *time.Time
	CreatedAt      time.Time
}

// LinkTokenBytes is LINK_TOKEN_BYTES: the token is URL-safe base64 of this many bytes.
const LinkTokenBytes = 32

// CheckAccessControl is the constructor check of MCPOAuthLink.
func CheckAccessControl(v string) error {
	if v == AccessWorkspace || v == AccessPublic {
		return nil
	}
	return &Invalid{"Invalid access_control '" + v + "'. Must be one of {'workspace', 'public'}"}
}

// LinkExpiry is expires_at for a link created now with expires_in_days (0: none).
func LinkExpiry(now time.Time, days *int) *time.Time {
	if days == nil || *days == 0 {
		return nil
	}
	t := now.Add(time.Duration(*days) * 24 * time.Hour)
	return &t
}
