package storage

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
	"regexp"
	"strconv"
	"strings"
	"sync"
	"time"
	"unicode/utf8"

	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/credentials"
	"github.com/aws/aws-sdk-go-v2/service/s3"
	"github.com/aws/smithy-go"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/blob"
)

const maxPathBytes = 512

var identifierRE = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$`)

// ErrInstanceNotFound is what Instances returns for an instance that no
// longer exists; its token is then refused.
var ErrInstanceNotFound = errors.New("MCP instance not found")

// Instance is what the API reads of an MCP instance on every request.
type Instance struct {
	WorkspaceID string
	Spec        map[string]any
}

// Instances loads an instance's current workspace and spec. Every request
// consults it, so deleting an instance or dropping its opt-in revokes its tokens.
type Instances interface {
	Instance(ctx context.Context, instanceID string) (Instance, error)
}

// ObjectStore is the S3 surface the API uses. It is the SDK's, not the
// kernel blob port's: a write must answer with the ETag it produced, which a
// later read could not give without racing another writer.
type ObjectStore interface {
	GetObject(context.Context, *s3.GetObjectInput, ...func(*s3.Options)) (*s3.GetObjectOutput, error)
	HeadObject(context.Context, *s3.HeadObjectInput, ...func(*s3.Options)) (*s3.HeadObjectOutput, error)
	PutObject(context.Context, *s3.PutObjectInput, ...func(*s3.Options)) (*s3.PutObjectOutput, error)
	DeleteObject(context.Context, *s3.DeleteObjectInput, ...func(*s3.Options)) (*s3.DeleteObjectOutput, error)
	ListObjectsV2(context.Context, *s3.ListObjectsV2Input, ...func(*s3.Options)) (*s3.ListObjectsV2Output, error)
}

// NewObjectStore is an S3 client over AGENTAREA_S3_* as the cluster blob
// profile builds it: static credentials, path-style against a custom endpoint.
func NewObjectStore(cfg blob.Config) (ObjectStore, error) {
	if cfg.AccessKey == "" || cfg.SecretKey == "" {
		return nil, errors.New("MCP storage needs AGENTAREA_S3_ACCESS_KEY and AGENTAREA_S3_SECRET_KEY")
	}
	var endpoint *string
	if cfg.Endpoint != "" {
		endpoint = aws.String(cfg.Endpoint)
	}
	return s3.New(s3.Options{
		Region:                     cfg.Region,
		Credentials:                aws.NewCredentialsCache(credentials.NewStaticCredentialsProvider(cfg.AccessKey, cfg.SecretKey, "")),
		BaseEndpoint:               endpoint,
		UsePathStyle:               cfg.Endpoint != "",
		RequestChecksumCalculation: aws.RequestChecksumCalculationWhenRequired,
		ResponseChecksumValidation: aws.ResponseChecksumValidationWhenRequired,
	}), nil
}

// Handler serves the MCP storage HTTP API at /mcp/{instance_id}/storage/...
type Handler struct {
	secret    []byte
	maxSize   int64
	bucket    string
	store     ObjectStore
	instances Instances
	log       *slog.Logger
	now       func() time.Time
	emulate   bool
	locks     sync.Map
}

// NewHandler serves bucket (AGENTAREA_S3_ARTIFACTS_BUCKET). Keys are
// workspaces/{workspace_id}/apps/{instance_id}/{path}, the layout of the
// platform's workspace files, so app objects show in Context. Tokens are
// checked against secret, the gateway secret.
func NewHandler(secret []byte, bucket string, store ObjectStore, instances Instances, writes ConditionalWrites, log *slog.Logger) (*Handler, error) {
	if len(secret) < 32 || bucket == "" || store == nil || instances == nil || log == nil {
		return nil, errors.New("MCP storage handler requires a signing secret of at least 32 bytes, bucket, object store, instance lookup and logger")
	}
	if writes != NativeConditionalWrites && writes != EmulatedConditionalWrites {
		return nil, fmt.Errorf("MCP storage conditional writes must be native or emulated, got %q", writes)
	}
	return &Handler{
		secret: secret, maxSize: MaxObjectBytes, bucket: bucket, store: store, instances: instances, log: log, now: time.Now,
		emulate: writes == EmulatedConditionalWrites,
	}, nil
}

func (h *Handler) lock(key string) func() {
	mu, _ := h.locks.LoadOrStore(key, &sync.Mutex{})
	m, _ := mu.(*sync.Mutex)
	m.Lock()
	return m.Unlock
}

// precondition checks If-Match (ifMatch set) or If-None-Match: * against the
// object as it is now, for a store that does not check it itself.
func (h *Handler) precondition(ctx context.Context, key, ifMatch string) error {
	head, err := h.store.HeadObject(ctx, &s3.HeadObjectInput{Bucket: aws.String(h.bucket), Key: aws.String(key)})
	switch {
	case err != nil && !isNotFound(err):
		return fmt.Errorf("head MCP storage object: %w", err)
	case ifMatch == "" && err == nil, ifMatch != "" && err != nil, ifMatch != "" && quoteETag(aws.ToString(head.ETag)) != ifMatch:
		return fail(http.StatusPreconditionFailed, "the object changed; read it again and retry")
	}
	return nil
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

type grant struct{ workspaceID, instanceID string }

func (h *Handler) serve(w http.ResponseWriter, r *http.Request) error {
	instanceID, rest, ok := splitPath(r.URL.EscapedPath())
	if !ok {
		return fail(http.StatusNotFound, "not found")
	}
	g, err := h.authenticate(r, instanceID)
	if err != nil {
		return err
	}
	if rest == "/objects" {
		if r.Method != http.MethodGet {
			return fail(http.StatusMethodNotAllowed, "method not allowed")
		}
		return h.list(w, r, g)
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
	key := objectPrefix(g) + relative
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

func (h *Handler) authenticate(r *http.Request, instanceID string) (grant, error) {
	token, ok := bearerToken(r.Header.Get("Authorization"))
	if !ok || token == "" {
		return grant{}, fail(http.StatusUnauthorized, "bearer token is required")
	}
	if !identifierRE.MatchString(instanceID) {
		return grant{}, fail(http.StatusBadRequest, "invalid instance_id")
	}
	inst, err := h.instances.Instance(r.Context(), instanceID)
	if errors.Is(err, ErrInstanceNotFound) {
		return grant{}, fail(http.StatusUnauthorized, "invalid MCP storage token")
	}
	if err != nil {
		h.log.Error("MCP storage could not load its MCP instance", "instance_id", instanceID, "error", err)
		return grant{}, fail(http.StatusServiceUnavailable, "MCP instance lookup failed")
	}
	if !identifierRE.MatchString(inst.WorkspaceID) {
		return grant{}, fail(http.StatusUnauthorized, "invalid MCP storage token")
	}
	g := grant{workspaceID: inst.WorkspaceID, instanceID: instanceID}
	err = verifyToken(token, h.secret, g.workspaceID, g.instanceID, h.now())
	if errors.Is(err, errClaimsMismatch) {
		return grant{}, fail(http.StatusForbidden, "the token does not grant this MCP instance")
	}
	if err != nil {
		return grant{}, fail(http.StatusUnauthorized, "invalid MCP storage token")
	}
	if enabled, err := Enabled(inst.Spec); err != nil || !enabled {
		return grant{}, fail(http.StatusForbidden, "storage is not enabled for this MCP instance")
	}
	return g, nil
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
	for _, c := range value {
		if c < 0x20 || c == 0x7f || c == '\\' {
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

func objectPrefix(g grant) string {
	return "workspaces/" + g.workspaceID + "/apps/" + g.instanceID + "/"
}

func (h *Handler) get(w http.ResponseWriter, r *http.Request, key string) error {
	out, err := h.store.GetObject(r.Context(), &s3.GetObjectInput{Bucket: aws.String(h.bucket), Key: aws.String(key)})
	if err != nil {
		if isNotFound(err) {
			return fail(http.StatusNotFound, "object not found")
		}
		return fmt.Errorf("get MCP storage object: %w", err)
	}
	defer func() {
		if err := out.Body.Close(); err != nil {
			h.log.Warn("MCP storage object body did not close", "key", key, "error", err)
		}
	}()
	writeObjectHeaders(w, out.ETag, out.ContentType, out.ContentLength)
	w.WriteHeader(http.StatusOK)
	if _, err := io.Copy(w, out.Body); err != nil {
		h.log.Warn("MCP storage read was interrupted", "key", key, "error", err)
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
	in := &s3.PutObjectInput{
		Bucket:         aws.String(h.bucket),
		Key:            aws.String(key),
		Body:           bytes.NewReader(data),
		ContentLength:  aws.Int64(int64(len(data))),
		ContentType:    aws.String(contentType),
		ChecksumSHA256: aws.String(base64.StdEncoding.EncodeToString(digest[:])),
		Metadata:       map[string]string{"sha256": hex.EncodeToString(digest[:])},
	}
	switch {
	case h.emulate:
		defer h.lock(key)()
		if err := h.precondition(r.Context(), key, quoteETag(ifMatch)); err != nil {
			return err
		}
	case ifMatch != "":
		in.IfMatch = aws.String(quoteETag(ifMatch))
	default:
		in.IfNoneMatch = aws.String("*")
	}
	out, err := h.store.PutObject(r.Context(), in)
	if err != nil {
		if isPreconditionFailed(err) || isNotFound(err) {
			return fail(http.StatusPreconditionFailed, "the object changed; read it again and retry")
		}
		return fmt.Errorf("put MCP storage object: %w", err)
	}
	etag := quoteETag(aws.ToString(out.ETag))
	w.Header().Set("ETag", etag)
	writeJSON(w, http.StatusOK, map[string]any{"etag": etag, "size": len(data)}, h.log)
	return nil
}

func (h *Handler) delete(w http.ResponseWriter, r *http.Request, key string) error {
	ifMatch := strings.TrimSpace(r.Header.Get("If-Match"))
	if ifMatch == "" {
		return fail(http.StatusPreconditionRequired, "a delete requires If-Match: <etag>")
	}
	ifMatch = quoteETag(ifMatch)
	if h.emulate {
		defer h.lock(key)()
	}
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
	in := &s3.DeleteObjectInput{Bucket: aws.String(h.bucket), Key: aws.String(key)}
	if !h.emulate {
		in.IfMatch = aws.String(ifMatch)
	}
	if _, err := h.store.DeleteObject(r.Context(), in); err != nil {
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

func (h *Handler) list(w http.ResponseWriter, r *http.Request, g grant) error {
	prefix := r.URL.Query().Get("prefix")
	if prefix != "" {
		if err := ValidatePath(strings.TrimSuffix(prefix, "/")); err != nil {
			return fail(http.StatusBadRequest, "prefix: "+err.Error())
		}
	}
	base := objectPrefix(g)
	objects := []listedObject{}
	var token *string
	for {
		page, err := h.store.ListObjectsV2(r.Context(), &s3.ListObjectsV2Input{
			Bucket: aws.String(h.bucket), Prefix: aws.String(base + prefix), ContinuationToken: token,
		})
		if err != nil {
			return fmt.Errorf("list MCP storage objects: %w", err)
		}
		for _, o := range page.Contents {
			item := listedObject{
				Path: strings.TrimPrefix(aws.ToString(o.Key), base),
				Size: aws.ToInt64(o.Size),
				ETag: quoteETag(aws.ToString(o.ETag)),
			}
			if o.LastModified != nil {
				item.LastModified = o.LastModified.UTC().Format(time.RFC3339)
			}
			objects = append(objects, item)
		}
		if !aws.ToBool(page.IsTruncated) || page.NextContinuationToken == nil {
			break
		}
		token = page.NextContinuationToken
	}
	writeJSON(w, http.StatusOK, map[string]any{"objects": objects}, h.log)
	return nil
}

func (h *Handler) writeError(w http.ResponseWriter, r *http.Request, err error) {
	var api *apiError
	if errors.As(err, &api) {
		if api.status == http.StatusUnauthorized {
			w.Header().Set("WWW-Authenticate", `Bearer realm="mcp-storage"`)
		}
		writeJSON(w, api.status, map[string]string{"error": api.message}, h.log)
		return
	}
	h.log.Error("MCP storage request failed", "method", r.Method, "path", r.URL.Path, "error", err)
	writeJSON(w, http.StatusBadGateway, map[string]string{"error": "object store request failed"}, h.log)
}

func writeJSON(w http.ResponseWriter, status int, body any, log *slog.Logger) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	if err := json.NewEncoder(w).Encode(body); err != nil {
		log.Warn("MCP storage response was not written", "error", err)
	}
}

func guessContentType(relative string) string {
	if t := mime.TypeByExtension(path.Ext(relative)); t != "" {
		return t
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

// isPreconditionFailed also takes 409 ConditionalRequestConflict, the answer
// S3 may give the loser of a concurrent conditional write.
func isPreconditionFailed(err error) bool {
	switch errorCode(err) {
	case "PreconditionFailed", "ConditionalRequestConflict":
		return true
	}
	status := httpStatus(err)
	return status == http.StatusPreconditionFailed || status == http.StatusConflict
}
