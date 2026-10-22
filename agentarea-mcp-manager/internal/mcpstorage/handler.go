package mcpstorage

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"mime"
	"net/http"
	"net/url"
	"path"
	"strconv"
	"strings"
	"time"
	"unicode/utf8"

	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/service/s3"
	"github.com/aws/smithy-go"

	"github.com/agentarea/mcp-manager/internal/activationauth"
	"github.com/agentarea/mcp-manager/internal/models"
	"github.com/agentarea/mcp-manager/internal/workspace"
)

// Route is where the manager mounts the API, next to the instance's MCP
// endpoint.
const Route = "/mcp/:instance_id/storage/*path"

const maxPathBytes = 512

// ErrInstanceNotFound is what Instances returns for an instance that no longer
// exists; its token is then refused.
var ErrInstanceNotFound = errors.New("MCP instance not found")

// Instances loads the current spec of an MCP instance. Every request consults
// it, so deleting an instance or dropping its opt-in revokes its tokens.
type Instances interface {
	Instance(ctx context.Context, instanceID string) (*models.MCPServerInstance, error)
}

// ObjectStore is the S3 surface the API uses.
type ObjectStore interface {
	GetObject(context.Context, *s3.GetObjectInput, ...func(*s3.Options)) (*s3.GetObjectOutput, error)
	HeadObject(context.Context, *s3.HeadObjectInput, ...func(*s3.Options)) (*s3.HeadObjectOutput, error)
	PutObject(context.Context, *s3.PutObjectInput, ...func(*s3.Options)) (*s3.PutObjectOutput, error)
	DeleteObject(context.Context, *s3.DeleteObjectInput, ...func(*s3.Options)) (*s3.DeleteObjectOutput, error)
	ListObjectsV2(context.Context, *s3.ListObjectsV2Input, ...func(*s3.Options)) (*s3.ListObjectsV2Output, error)
}

// NewObjectStore builds the S3 client for the artifacts bucket the sandbox
// workspace repository already uses.
func NewObjectStore(ctx context.Context, cfg workspace.RepositoryConfig) (ObjectStore, error) {
	if cfg.Bucket == "" {
		return nil, errors.New("MCP storage S3 bucket is required")
	}
	awsCfg, err := workspace.S3Config(ctx, cfg.Region, cfg.AccessKey, cfg.SecretKey)
	if err != nil {
		return nil, fmt.Errorf("load MCP storage S3 configuration: %w", err)
	}
	return s3.NewFromConfig(awsCfg, func(options *s3.Options) {
		options.UsePathStyle = cfg.ForcePathStyle
		if cfg.Endpoint != "" {
			options.BaseEndpoint = aws.String(cfg.Endpoint)
		}
	}), nil
}

// Handler serves the MCP storage HTTP API.
type Handler struct {
	secret    []byte
	maxSize   int64
	bucket    string
	store     ObjectStore
	instances Instances
	logger    *slog.Logger
	now       func() time.Time
}

// NewHandler returns the API over bucket. Keys are
// workspaces/{workspace_id}/apps/{instance_id}/{path}: the layout the
// platform's workspace files use, so app objects show in Context. Tokens are
// checked against secret, the manager's gateway secret.
func NewHandler(secret []byte, bucket string, store ObjectStore, instances Instances, logger *slog.Logger) (*Handler, error) {
	if len(secret) < 32 || bucket == "" || store == nil || instances == nil || logger == nil {
		return nil, errors.New("MCP storage handler requires a signing secret of at least 32 bytes, bucket, object store, instance lookup and logger")
	}
	return &Handler{secret: secret, maxSize: MaxObjectBytes, bucket: bucket, store: store, instances: instances, logger: logger, now: time.Now}, nil
}

type apiError struct {
	status  int
	message string
}

func (e *apiError) Error() string { return e.message }

func fail(status int, message string) error { return &apiError{status: status, message: message} }

func (h *Handler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	if err := h.serve(w, r); err != nil {
		h.writeError(w, r, err)
	}
}

func (h *Handler) serve(w http.ResponseWriter, r *http.Request) error {
	instanceID, rest, ok := splitPath(r.URL.EscapedPath())
	if !ok {
		return fail(http.StatusNotFound, "not found")
	}
	identity, err := h.authenticate(r, instanceID)
	if err != nil {
		return err
	}
	if rest == "/objects" {
		if r.Method != http.MethodGet {
			return fail(http.StatusMethodNotAllowed, "method not allowed")
		}
		return h.list(w, r, identity)
	}
	escaped, ok := strings.CutPrefix(rest, "/objects/")
	if !ok {
		return fail(http.StatusNotFound, "not found")
	}
	relative, err := url.PathUnescape(escaped)
	if err != nil {
		return fail(http.StatusBadRequest, "path is not valid percent-encoding")
	}
	if err := ValidatePath(relative); err != nil {
		return fail(http.StatusBadRequest, err.Error())
	}
	key := objectPrefix(identity) + relative
	switch r.Method {
	case http.MethodGet:
		return h.get(w, r, key)
	case http.MethodHead:
		return h.head(w, r, key)
	case http.MethodPut:
		return h.put(w, r, key, relative)
	case http.MethodDelete:
		return h.delete(w, r, key)
	default:
		return fail(http.StatusMethodNotAllowed, "method not allowed")
	}
}

// splitPath takes /mcp/{instance_id}/storage{rest} apart.
func splitPath(escaped string) (instanceID, rest string, ok bool) {
	tail, ok := strings.CutPrefix(escaped, "/mcp/")
	if !ok {
		return "", "", false
	}
	instanceID, rest, ok = strings.Cut(tail, "/storage")
	if !ok || instanceID == "" || strings.Contains(instanceID, "/") {
		return "", "", false
	}
	return instanceID, rest, true
}

func (h *Handler) authenticate(r *http.Request, instanceID string) (activationauth.Identity, error) {
	token, err := activationauth.BearerToken(r.Header.Get("Authorization"))
	if err != nil || token == "" {
		return activationauth.Identity{}, fail(http.StatusUnauthorized, "bearer token is required")
	}
	if err := workspace.ValidateIdentifier("instance_id", instanceID); err != nil {
		return activationauth.Identity{}, fail(http.StatusBadRequest, err.Error())
	}
	instance, err := h.instances.Instance(r.Context(), instanceID)
	if errors.Is(err, ErrInstanceNotFound) {
		return activationauth.Identity{}, fail(http.StatusUnauthorized, "invalid MCP storage token")
	}
	if err != nil {
		h.logger.Error("MCP storage could not load its MCP instance",
			slog.String("instance_id", instanceID), slog.String("error", err.Error()))
		return activationauth.Identity{}, fail(http.StatusServiceUnavailable, "MCP instance lookup failed")
	}
	if instance == nil || workspace.ValidateIdentifier("workspace_id", instance.WorkspaceID) != nil {
		return activationauth.Identity{}, fail(http.StatusUnauthorized, "invalid MCP storage token")
	}
	granted := identity(instance.WorkspaceID, instanceID)
	err = activationauth.Verify(token, h.secret, activationauth.ScopeStorage, granted, activationauth.BodySHA256(nil), h.now())
	if errors.Is(err, activationauth.ErrClaimsMismatch) {
		return activationauth.Identity{}, fail(http.StatusForbidden, "the token does not grant this MCP instance")
	}
	if err != nil {
		return activationauth.Identity{}, fail(http.StatusUnauthorized, "invalid MCP storage token")
	}
	if enabled, err := Enabled(instance.JSONSpec); err != nil || !enabled {
		return activationauth.Identity{}, fail(http.StatusForbidden, "storage is not enabled for this MCP instance")
	}
	return granted, nil
}

// ValidatePath accepts a relative object path: no leading slash, no empty, "."
// or ".." segment, no backslash or control character, valid UTF-8, at most 512
// bytes.
func ValidatePath(value string) error {
	if value == "" {
		return errors.New("path is required")
	}
	if len(value) > maxPathBytes {
		return fmt.Errorf("path exceeds %d bytes", maxPathBytes)
	}
	if !utf8.ValidString(value) {
		return errors.New("path must be valid UTF-8")
	}
	for _, character := range value {
		if character < 0x20 || character == 0x7f || character == '\\' {
			return errors.New("path must not contain control characters or backslashes")
		}
	}
	for _, segment := range strings.Split(value, "/") {
		if segment == "" || segment == "." || segment == ".." {
			return errors.New(`path must be relative, without empty, "." or ".." segments`)
		}
	}
	return nil
}

func objectPrefix(identity activationauth.Identity) string {
	return "workspaces/" + identity.WorkspaceID + "/apps/" + identity.InstanceID + "/"
}

func (h *Handler) get(w http.ResponseWriter, r *http.Request, key string) error {
	out, err := h.store.GetObject(r.Context(), &s3.GetObjectInput{Bucket: aws.String(h.bucket), Key: aws.String(key)})
	if err != nil {
		if isNotFound(err) {
			return fail(http.StatusNotFound, "object not found")
		}
		return fmt.Errorf("get MCP storage object: %w", err)
	}
	defer out.Body.Close()
	writeObjectHeaders(w, out.ETag, out.ContentType, out.ContentLength)
	w.WriteHeader(http.StatusOK)
	if _, err := io.Copy(w, out.Body); err != nil {
		h.logger.Warn("MCP storage read was interrupted", slog.String("key", key), slog.String("error", err.Error()))
	}
	return nil
}

func (h *Handler) head(w http.ResponseWriter, r *http.Request, key string) error {
	out, err := h.store.HeadObject(r.Context(), &s3.HeadObjectInput{Bucket: aws.String(h.bucket), Key: aws.String(key)})
	if err != nil {
		if isNotFound(err) {
			return fail(http.StatusNotFound, "object not found")
		}
		return fmt.Errorf("head MCP storage object: %w", err)
	}
	writeObjectHeaders(w, out.ETag, out.ContentType, out.ContentLength)
	w.WriteHeader(http.StatusOK)
	return nil
}

func writeObjectHeaders(w http.ResponseWriter, etag, contentType *string, size *int64) {
	w.Header().Set("ETag", quoteETag(aws.ToString(etag)))
	w.Header().Set("Content-Type", aws.ToString(contentType))
	if size != nil {
		w.Header().Set("Content-Length", strconv.FormatInt(*size, 10))
	}
}

func (h *Handler) put(w http.ResponseWriter, r *http.Request, key, relative string) error {
	ifMatch, ifNoneMatch := strings.TrimSpace(r.Header.Get("If-Match")), strings.TrimSpace(r.Header.Get("If-None-Match"))
	switch {
	case ifMatch == "" && ifNoneMatch == "":
		return fail(http.StatusPreconditionRequired, `a write requires If-Match: <etag> or If-None-Match: *`)
	case ifMatch != "" && ifNoneMatch != "":
		return fail(http.StatusBadRequest, "send exactly one of If-Match and If-None-Match")
	case ifNoneMatch != "" && ifNoneMatch != "*":
		return fail(http.StatusBadRequest, `If-None-Match accepts only "*"`)
	}
	if r.ContentLength > h.maxSize {
		return fail(http.StatusRequestEntityTooLarge, fmt.Sprintf("object exceeds %d bytes", h.maxSize))
	}
	data, err := io.ReadAll(http.MaxBytesReader(w, r.Body, h.maxSize))
	if err != nil {
		var tooLarge *http.MaxBytesError
		if errors.As(err, &tooLarge) {
			return fail(http.StatusRequestEntityTooLarge, fmt.Sprintf("object exceeds %d bytes", h.maxSize))
		}
		return fail(http.StatusBadRequest, "could not read the request body")
	}
	contentType := strings.TrimSpace(r.Header.Get("Content-Type"))
	if contentType == "" {
		contentType = guessContentType(relative)
	}
	digest := sha256.Sum256(data)
	// The same metadata ArtifactService.put writes, so the platform's head()
	// and its verified downloads treat app objects like any workspace file.
	input := &s3.PutObjectInput{
		Bucket:         aws.String(h.bucket),
		Key:            aws.String(key),
		Body:           bytes.NewReader(data),
		ContentLength:  aws.Int64(int64(len(data))),
		ContentType:    aws.String(contentType),
		ChecksumSHA256: aws.String(base64.StdEncoding.EncodeToString(digest[:])),
		Metadata:       map[string]string{"sha256": hex.EncodeToString(digest[:])},
	}
	if ifMatch != "" {
		input.IfMatch = aws.String(quoteETag(ifMatch))
	} else {
		input.IfNoneMatch = aws.String("*")
	}
	out, err := h.store.PutObject(r.Context(), input)
	if err != nil {
		// If-Match against a missing object is a failed precondition too.
		if isPreconditionFailed(err) || isNotFound(err) {
			return fail(http.StatusPreconditionFailed, "the object changed; read it again and retry")
		}
		return fmt.Errorf("put MCP storage object: %w", err)
	}
	etag := quoteETag(aws.ToString(out.ETag))
	w.Header().Set("ETag", etag)
	writeJSON(w, http.StatusOK, map[string]any{"etag": etag, "size": len(data)})
	return nil
}

func (h *Handler) delete(w http.ResponseWriter, r *http.Request, key string) error {
	ifMatch := strings.TrimSpace(r.Header.Get("If-Match"))
	if ifMatch == "" {
		return fail(http.StatusPreconditionRequired, "a delete requires If-Match: <etag>")
	}
	ifMatch = quoteETag(ifMatch)
	// Object stores that ignore If-Match on DELETE would turn a stale delete
	// into a lost update, so the ETag is checked here as well; the store's own
	// check closes the window between the two where it is supported.
	head, err := h.store.HeadObject(r.Context(), &s3.HeadObjectInput{Bucket: aws.String(h.bucket), Key: aws.String(key)})
	if err != nil {
		if isNotFound(err) {
			return fail(http.StatusNotFound, "object not found")
		}
		return fmt.Errorf("head MCP storage object: %w", err)
	}
	if quoteETag(aws.ToString(head.ETag)) != ifMatch {
		return fail(http.StatusPreconditionFailed, "the object changed; read it again and retry")
	}
	_, err = h.store.DeleteObject(r.Context(), &s3.DeleteObjectInput{Bucket: aws.String(h.bucket), Key: aws.String(key), IfMatch: aws.String(ifMatch)})
	if err != nil {
		if isPreconditionFailed(err) {
			return fail(http.StatusPreconditionFailed, "the object changed; read it again and retry")
		}
		if isNotFound(err) {
			return fail(http.StatusNotFound, "object not found")
		}
		return fmt.Errorf("delete MCP storage object: %w", err)
	}
	w.WriteHeader(http.StatusNoContent)
	return nil
}

type listedObject struct {
	Path         string `json:"path"`
	Size         int64  `json:"size"`
	ETag         string `json:"etag"`
	LastModified string `json:"last_modified"`
}

func (h *Handler) list(w http.ResponseWriter, r *http.Request, identity activationauth.Identity) error {
	prefix := r.URL.Query().Get("prefix")
	if prefix != "" {
		if err := ValidatePath(strings.TrimSuffix(prefix, "/")); err != nil {
			return fail(http.StatusBadRequest, "prefix: "+err.Error())
		}
	}
	base := objectPrefix(identity)
	objects := []listedObject{}
	var token *string
	for {
		page, err := h.store.ListObjectsV2(r.Context(), &s3.ListObjectsV2Input{
			Bucket:            aws.String(h.bucket),
			Prefix:            aws.String(base + prefix),
			ContinuationToken: token,
		})
		if err != nil {
			return fmt.Errorf("list MCP storage objects: %w", err)
		}
		for _, object := range page.Contents {
			item := listedObject{
				Path: strings.TrimPrefix(aws.ToString(object.Key), base),
				Size: aws.ToInt64(object.Size),
				ETag: quoteETag(aws.ToString(object.ETag)),
			}
			if object.LastModified != nil {
				item.LastModified = object.LastModified.UTC().Format(time.RFC3339)
			}
			objects = append(objects, item)
		}
		if !aws.ToBool(page.IsTruncated) || page.NextContinuationToken == nil {
			break
		}
		token = page.NextContinuationToken
	}
	writeJSON(w, http.StatusOK, map[string]any{"objects": objects})
	return nil
}

func (h *Handler) writeError(w http.ResponseWriter, r *http.Request, err error) {
	var api *apiError
	if errors.As(err, &api) {
		if api.status == http.StatusUnauthorized {
			w.Header().Set("WWW-Authenticate", `Bearer realm="mcp-storage"`)
		}
		writeJSON(w, api.status, map[string]string{"error": api.message})
		return
	}
	h.logger.Error("MCP storage request failed",
		slog.String("method", r.Method),
		slog.String("path", r.URL.Path),
		slog.String("error", err.Error()))
	writeJSON(w, http.StatusBadGateway, map[string]string{"error": "object store request failed"})
}

func writeJSON(w http.ResponseWriter, status int, body any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(body)
}

func guessContentType(relative string) string {
	if contentType := mime.TypeByExtension(path.Ext(relative)); contentType != "" {
		return contentType
	}
	return "application/octet-stream"
}

func quoteETag(etag string) string {
	if etag == "" || strings.HasPrefix(etag, `"`) || strings.HasPrefix(etag, "W/") {
		return etag
	}
	return `"` + etag + `"`
}

func errorCode(err error) string {
	var apiErr smithy.APIError
	if errors.As(err, &apiErr) {
		return apiErr.ErrorCode()
	}
	return ""
}

func httpStatus(err error) int {
	var withStatus interface{ HTTPStatusCode() int }
	if errors.As(err, &withStatus) {
		return withStatus.HTTPStatusCode()
	}
	return 0
}

func isNotFound(err error) bool {
	switch errorCode(err) {
	case "NoSuchKey", "NotFound":
		return true
	}
	return httpStatus(err) == http.StatusNotFound
}

// A concurrent conditional write that loses on S3 may surface as 409
// ConditionalRequestConflict instead of 412; both mean "retry from a fresh read".
func isPreconditionFailed(err error) bool {
	switch errorCode(err) {
	case "PreconditionFailed", "ConditionalRequestConflict":
		return true
	}
	status := httpStatus(err)
	return status == http.StatusPreconditionFailed || status == http.StatusConflict
}
