package workspace

import (
	"encoding/json"
	"fmt"
	"net/url"
	"path"
	"regexp"
	"strings"
)

const SchemaVersion = 1

var identifierPattern = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$`)

// ManifestRef is the immutable, credential-free workspace identity carried by
// Redis and workflow payloads. Transfer URLs are deliberately not part of it.
type ManifestRef struct {
	SchemaVersion  int    `json:"schema_version"`
	WorkspaceID    string `json:"workspace_id"`
	TaskID         string `json:"task_id"`
	Generation     int64  `json:"generation"`
	ManifestURI    string `json:"manifest_uri"`
	ManifestSHA256 string `json:"manifest_sha256"`
	BaseGeneration int64  `json:"base_generation"`
	FencingToken   int64  `json:"fencing_token"`
}

type Entry struct {
	RelativePath        string `json:"relative_path"`
	ObjectURI           string `json:"object_uri,omitempty"`
	ObjectVersionOrETag string `json:"object_version_or_etag,omitempty"`
	SHA256              string `json:"sha256,omitempty"`
	// Size has no omitempty: a zero-length stream (empty stdout/stderr) is a
	// valid ref with size 0, and dropping the key makes strict consumers reject
	// the ref as malformed.
	Size        int64  `json:"size"`
	ContentType string `json:"content_type,omitempty"`
	Mode        uint32 `json:"mode,omitempty"`
	Deleted     bool   `json:"deleted,omitempty"`
}

type Manifest struct {
	SchemaVersion  int     `json:"schema_version"`
	WorkspaceID    string  `json:"workspace_id"`
	TaskID         string  `json:"task_id"`
	Generation     int64   `json:"generation"`
	BaseGeneration int64   `json:"base_generation"`
	FencingToken   int64   `json:"fencing_token"`
	Entries        []Entry `json:"entries"`
}

// Download is an activation-only transfer descriptor. URL must never be
// persisted or published; it is valid only for one short-lived HTTP request.
type Download struct {
	RelativePath string            `json:"relative_path"`
	URL          string            `json:"url"`
	Headers      map[string]string `json:"headers,omitempty"`
	SHA256       string            `json:"sha256"`
	Size         int64             `json:"size"`
	ContentType  string            `json:"content_type,omitempty"`
	Mode         uint32            `json:"mode,omitempty"`
}

type Hydration struct {
	Generation   int64      `json:"generation"`
	FencingToken int64      `json:"fencing_token"`
	Downloads    []Download `json:"downloads,omitempty"`
}

type ChangeDescriptor struct {
	RelativePath string `json:"relative_path"`
	SHA256       string `json:"sha256,omitempty"`
	Size         int64  `json:"size,omitempty"`
	ContentType  string `json:"content_type,omitempty"`
	Mode         uint32 `json:"mode,omitempty"`
	Deleted      bool   `json:"deleted,omitempty"`
}

type Upload struct {
	ChangeDescriptor
	URL       string            `json:"url"`
	ObjectURI string            `json:"object_uri"`
	Headers   map[string]string `json:"headers,omitempty"`
}

type WritebackRequest struct {
	WorkspaceID    string   `json:"workspace_id"`
	TaskID         string   `json:"task_id"`
	BaseGeneration int64    `json:"base_generation"`
	FencingToken   int64    `json:"fencing_token"`
	Uploads        []Upload `json:"uploads,omitempty"`
}

type UploadReceipt struct {
	RelativePath string `json:"relative_path"`
	ObjectURI    string `json:"object_uri,omitempty"`
	Deleted      bool   `json:"deleted,omitempty"`
}

type WritebackResponse struct {
	Receipts []UploadReceipt `json:"receipts,omitempty"`
}

func (r ManifestRef) Validate() error {
	if r.SchemaVersion != SchemaVersion {
		return fmt.Errorf("unsupported workspace manifest schema_version %d", r.SchemaVersion)
	}
	if err := ValidateIdentifier("workspace_id", r.WorkspaceID); err != nil {
		return err
	}
	if err := ValidateIdentifier("task_id", r.TaskID); err != nil {
		return err
	}
	if r.Generation < 0 || r.BaseGeneration < 0 || r.BaseGeneration > r.Generation {
		return fmt.Errorf("invalid workspace generation")
	}
	if len(r.ManifestSHA256) != 64 || !isLowerHex(r.ManifestSHA256) {
		return fmt.Errorf("manifest_sha256 must be a lowercase SHA-256 hex digest")
	}
	if r.FencingToken <= 0 {
		return fmt.Errorf("invalid fencing_token")
	}
	parsed, err := url.Parse(r.ManifestURI)
	if err != nil || parsed.Scheme != "s3" || parsed.Host == "" || parsed.Path == "" || parsed.RawQuery != "" || parsed.Fragment != "" {
		return fmt.Errorf("manifest_uri must be an immutable s3 URI without query or fragment")
	}
	expectedSuffix := "/" + path.Join(
		"workspaces",
		r.WorkspaceID,
		"tasks",
		r.TaskID,
		"manifests",
		fmt.Sprintf("%d-%s.json", r.Generation, r.ManifestSHA256),
	)
	if !strings.HasSuffix(parsed.Path, expectedSuffix) {
		return fmt.Errorf("manifest_uri does not match workspace/task/generation identity")
	}
	return nil
}

func ValidateIdentifier(name, value string) error {
	if !identifierPattern.MatchString(value) {
		return fmt.Errorf("invalid %s", name)
	}
	return nil
}

func NormalizeRelativePath(value string) (string, error) {
	if value == "" || strings.ContainsRune(value, '\\') || strings.HasPrefix(value, "/") {
		return "", fmt.Errorf("path must be a POSIX relative path")
	}
	clean := path.Clean(value)
	if clean == "." || clean == ".." || strings.HasPrefix(clean, "../") || clean != value {
		return "", fmt.Errorf("path must be normalized and must not traverse")
	}
	return clean, nil
}

func (e Entry) Validate() error {
	if _, err := NormalizeRelativePath(e.RelativePath); err != nil {
		return fmt.Errorf("invalid workspace entry %q: %w", e.RelativePath, err)
	}
	if e.Deleted {
		if e.ObjectURI != "" || e.ObjectVersionOrETag != "" || e.SHA256 != "" || e.Size != 0 {
			return fmt.Errorf("tombstone %q contains object identity", e.RelativePath)
		}
		return nil
	}
	if e.Size < 0 || len(e.SHA256) != 64 || !isLowerHex(e.SHA256) || e.ObjectVersionOrETag == "" {
		return fmt.Errorf("entry %q lacks immutable size/hash/version identity", e.RelativePath)
	}
	parsed, err := url.Parse(e.ObjectURI)
	if err != nil || parsed.Scheme != "s3" || parsed.Host == "" || parsed.Path == "" || parsed.RawQuery != "" || parsed.Fragment != "" {
		return fmt.Errorf("entry %q has invalid object_uri", e.RelativePath)
	}
	if !strings.HasSuffix(parsed.Path, "/objects/"+e.SHA256) {
		return fmt.Errorf("entry %q object_uri does not match its digest", e.RelativePath)
	}
	return nil
}

func DecodeManifest(data []byte) (Manifest, error) {
	var manifest Manifest
	decoder := json.NewDecoder(strings.NewReader(string(data)))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(&manifest); err != nil {
		return Manifest{}, fmt.Errorf("decode workspace manifest: %w", err)
	}
	seen := make(map[string]struct{}, len(manifest.Entries))
	for _, entry := range manifest.Entries {
		if err := entry.Validate(); err != nil {
			return Manifest{}, err
		}
		if _, exists := seen[entry.RelativePath]; exists {
			return Manifest{}, fmt.Errorf("duplicate workspace path %q", entry.RelativePath)
		}
		seen[entry.RelativePath] = struct{}{}
	}
	return manifest, nil
}

func isLowerHex(value string) bool {
	for _, char := range value {
		if (char < '0' || char > '9') && (char < 'a' || char > 'f') {
			return false
		}
	}
	return true
}
