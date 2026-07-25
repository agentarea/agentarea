package workspace

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
	"net/url"
	"os"
	"path"
	"sort"
	"strconv"
	"strings"
	"time"

	"github.com/aws/aws-sdk-go-v2/aws"
	v4 "github.com/aws/aws-sdk-go-v2/aws/signer/v4"
	awsconfig "github.com/aws/aws-sdk-go-v2/config"
	"github.com/aws/aws-sdk-go-v2/service/s3"
	"github.com/aws/aws-sdk-go-v2/service/s3/types"
)

var (
	ErrWorkspaceConflict = errors.New("workspace_conflict")
	ErrQuotaExceeded     = errors.New("workspace_quota_exceeded")
)

type RepositoryConfig struct {
	Bucket         string
	Prefix         string
	Region         string
	Endpoint       string
	SignedURLTTL   time.Duration
	MaxFiles       int
	MaxFileBytes   int64
	MaxBytes       int64
	ForcePathStyle bool
}

type s3Client interface {
	GetObject(context.Context, *s3.GetObjectInput, ...func(*s3.Options)) (*s3.GetObjectOutput, error)
	HeadObject(context.Context, *s3.HeadObjectInput, ...func(*s3.Options)) (*s3.HeadObjectOutput, error)
	PutObject(context.Context, *s3.PutObjectInput, ...func(*s3.Options)) (*s3.PutObjectOutput, error)
}

type s3Presigner interface {
	PresignGetObject(context.Context, *s3.GetObjectInput, ...func(*s3.PresignOptions)) (*v4.PresignedHTTPRequest, error)
	PresignPutObject(context.Context, *s3.PutObjectInput, ...func(*s3.PresignOptions)) (*v4.PresignedHTTPRequest, error)
}

type Repository struct {
	cfg     RepositoryConfig
	client  s3Client
	presign s3Presigner
}

type UploadPlan struct {
	BaseRef      ManifestRef
	NextManifest Manifest
	Uploads      []Upload
	currentETag  string
	changedPaths map[string]struct{}
}

type leaseRecord struct {
	Owner        string    `json:"owner"`
	FencingToken int64     `json:"fencing_token"`
	ExpiresAt    time.Time `json:"expires_at"`
}

func ConfigFromEnv() RepositoryConfig {
	maxFiles, _ := strconv.Atoi(os.Getenv("SANDBOX_WORKSPACE_MAX_FILES"))
	if maxFiles <= 0 {
		maxFiles = 10_000
	}
	maxFileBytes, _ := strconv.ParseInt(os.Getenv("SANDBOX_WORKSPACE_MAX_FILE_BYTES"), 10, 64)
	if maxFileBytes <= 0 {
		maxFileBytes = 256 * 1024 * 1024
	}
	maxBytes, _ := strconv.ParseInt(os.Getenv("SANDBOX_WORKSPACE_MAX_BYTES"), 10, 64)
	if maxBytes <= 0 {
		maxBytes = 2 * 1024 * 1024 * 1024
	}
	ttl, err := time.ParseDuration(os.Getenv("SANDBOX_WORKSPACE_SIGNED_URL_TTL"))
	if err != nil || ttl <= 0 {
		ttl = time.Hour
	}
	return RepositoryConfig{
		Bucket:         firstEnv("SANDBOX_WORKSPACE_S3_BUCKET", "ARTIFACTS_BUCKET_NAME"),
		Prefix:         strings.Trim(os.Getenv("SANDBOX_WORKSPACE_S3_PREFIX"), "/"),
		Region:         firstEnvOr("us-east-1", "SANDBOX_WORKSPACE_S3_REGION", "AWS_REGION"),
		Endpoint:       strings.TrimRight(firstEnv("SANDBOX_WORKSPACE_S3_ENDPOINT", "AWS_ENDPOINT_URL"), "/"),
		SignedURLTTL:   ttl,
		MaxFiles:       maxFiles,
		MaxFileBytes:   maxFileBytes,
		MaxBytes:       maxBytes,
		ForcePathStyle: os.Getenv("SANDBOX_WORKSPACE_S3_FORCE_PATH_STYLE") != "false",
	}
}

func NewRepositoryFromEnv(ctx context.Context) (*Repository, error) {
	cfg := ConfigFromEnv()
	if cfg.Bucket == "" {
		return nil, fmt.Errorf("workspace S3 bucket is required; set SANDBOX_WORKSPACE_S3_BUCKET or ARTIFACTS_BUCKET_NAME")
	}
	awsCfg, err := awsconfig.LoadDefaultConfig(ctx, awsconfig.WithRegion(cfg.Region))
	if err != nil {
		return nil, fmt.Errorf("load workspace S3 configuration: %w", err)
	}
	client := s3.NewFromConfig(awsCfg, func(options *s3.Options) {
		options.UsePathStyle = cfg.ForcePathStyle
		if cfg.Endpoint != "" {
			options.BaseEndpoint = aws.String(cfg.Endpoint)
		}
	})
	return NewRepository(cfg, client, s3.NewPresignClient(client))
}

func NewRepository(cfg RepositoryConfig, client s3Client, presigner s3Presigner) (*Repository, error) {
	if cfg.Bucket == "" || client == nil || presigner == nil {
		return nil, fmt.Errorf("workspace bucket, S3 client, and presigner are required")
	}
	if cfg.SignedURLTTL <= 0 {
		cfg.SignedURLTTL = time.Hour
	}
	if cfg.MaxFiles <= 0 {
		cfg.MaxFiles = 10_000
	}
	if cfg.MaxFileBytes <= 0 {
		cfg.MaxFileBytes = 256 * 1024 * 1024
	}
	if cfg.MaxBytes <= 0 {
		cfg.MaxBytes = 2 * 1024 * 1024 * 1024
	}
	cfg.Prefix = strings.Trim(cfg.Prefix, "/")
	return &Repository{cfg: cfg, client: client, presign: presigner}, nil
}

func (r *Repository) PrepareHydration(ctx context.Context, ref ManifestRef) (Hydration, Manifest, error) {
	manifest, err := r.loadManifest(ctx, ref)
	if err != nil {
		return Hydration{}, Manifest{}, err
	}
	if _, err := r.validateCurrentLease(ctx, ref); err != nil {
		return Hydration{}, Manifest{}, err
	}
	downloads := make([]Download, 0, len(manifest.Entries))
	for _, entry := range manifest.Entries {
		if entry.Deleted {
			continue
		}
		bucket, key, err := r.authorizeObjectURI(ref.WorkspaceID, ref.TaskID, entry.ObjectURI, "objects/"+entry.SHA256)
		if err != nil {
			return Hydration{}, Manifest{}, err
		}
		input := &s3.GetObjectInput{Bucket: aws.String(bucket), Key: aws.String(key)}
		if strings.HasPrefix(entry.ObjectVersionOrETag, "version:") {
			input.VersionId = aws.String(strings.TrimPrefix(entry.ObjectVersionOrETag, "version:"))
		} else {
			input.IfMatch = aws.String(strings.Trim(entry.ObjectVersionOrETag, `"`))
		}
		signed, err := r.presign.PresignGetObject(ctx, input, func(options *s3.PresignOptions) {
			options.Expires = r.cfg.SignedURLTTL
		})
		if err != nil {
			return Hydration{}, Manifest{}, fmt.Errorf("sign workspace input %q: %w", entry.RelativePath, err)
		}
		downloads = append(downloads, Download{
			RelativePath: entry.RelativePath,
			URL:          signed.URL,
			Headers:      flattenHeaders(signed.SignedHeader),
			SHA256:       entry.SHA256,
			Size:         entry.Size,
			ContentType:  entry.ContentType,
			Mode:         entry.Mode,
		})
	}
	return Hydration{Generation: ref.Generation, FencingToken: ref.FencingToken, Downloads: downloads}, manifest, nil
}

func (r *Repository) ValidateCurrentLease(ctx context.Context, ref ManifestRef) error {
	_, err := r.validateCurrentLease(ctx, ref)
	return err
}

// ValidateCurrentManifest checks pointer identity without requiring an active
// lease. Recovery uses it after a runner crash, when the lease may already
// have expired but a no-write execution can still be finalized safely.
func (r *Repository) ValidateCurrentManifest(ctx context.Context, ref ManifestRef) error {
	if err := ref.Validate(); err != nil {
		return err
	}
	current, err := r.loadCurrentRef(ctx, ref.WorkspaceID, ref.TaskID)
	if err != nil {
		return err
	}
	if current != ref {
		return fmt.Errorf("%w: workspace manifest is no longer current", ErrWorkspaceConflict)
	}
	return nil
}

// StoreExecutionOutput persists a bounded command stream as an immutable,
// content-addressed task object. The returned entry contains no credentials or
// signed transfer URL and is safe to persist in control-plane records.
func (r *Repository) StoreExecutionOutput(ctx context.Context, ref ManifestRef, executionID, stream string, content []byte) (Entry, error) {
	if err := ref.Validate(); err != nil {
		return Entry{}, err
	}
	if err := ValidateIdentifier("execution_id", executionID); err != nil {
		return Entry{}, err
	}
	if stream != "stdout" && stream != "stderr" {
		return Entry{}, fmt.Errorf("execution output stream must be stdout or stderr")
	}
	if int64(len(content)) > r.cfg.MaxFileBytes {
		return Entry{}, fmt.Errorf("%w: execution %s exceeds %d bytes", ErrQuotaExceeded, stream, r.cfg.MaxFileBytes)
	}
	if _, err := r.validateCurrentLease(ctx, ref); err != nil {
		return Entry{}, err
	}
	digest := sha256.Sum256(content)
	hash := hex.EncodeToString(digest[:])
	key := path.Join(r.taskPrefix(ref.WorkspaceID, ref.TaskID), "objects", hash)
	objectURI := r.objectURI(key)
	_, putErr := r.client.PutObject(ctx, &s3.PutObjectInput{
		Bucket:         aws.String(r.cfg.Bucket),
		Key:            aws.String(key),
		Body:           bytes.NewReader(content),
		ContentLength:  aws.Int64(int64(len(content))),
		ContentType:    aws.String("text/plain; charset=utf-8"),
		ChecksumSHA256: aws.String(base64.StdEncoding.EncodeToString(digest[:])),
		Metadata:       map[string]string{"sha256": hash},
		IfNoneMatch:    aws.String("*"),
	})
	if putErr != nil {
		if err := r.verifyObjectBody(ctx, ref.WorkspaceID, ref.TaskID, objectURI, hash, int64(len(content))); err != nil {
			return Entry{}, fmt.Errorf("store immutable execution %s: %w", stream, putErr)
		}
	}
	if err := r.verifyObjectBody(ctx, ref.WorkspaceID, ref.TaskID, objectURI, hash, int64(len(content))); err != nil {
		return Entry{}, fmt.Errorf("verify immutable execution %s: %w", stream, err)
	}
	head, err := r.headObject(ctx, objectURI)
	if err != nil {
		return Entry{}, fmt.Errorf("read immutable execution %s identity: %w", stream, err)
	}
	versionOrETag := ""
	if head.VersionId != nil && *head.VersionId != "" {
		versionOrETag = "version:" + *head.VersionId
	} else if head.ETag != nil {
		versionOrETag = strings.Trim(*head.ETag, `"`)
	}
	entry := Entry{
		RelativePath:        path.Join(".agentarea", "executions", executionID, stream+".txt"),
		ObjectURI:           objectURI,
		ObjectVersionOrETag: versionOrETag,
		SHA256:              hash,
		Size:                int64(len(content)),
		ContentType:         "text/plain; charset=utf-8",
		Mode:                0o600,
	}
	if err := entry.Validate(); err != nil {
		return Entry{}, fmt.Errorf("invalid execution output ref: %w", err)
	}
	return entry, nil
}

// PutExecutionOutput persists a bounded command stream as an immutable,
// content-addressed task object without requiring a workspace lease. The
// session model keeps the live workspace on the sandbox's own disk, so output
// offload only needs the task identity, not a manifest generation. The returned
// entry carries no credentials or signed transfer URL and is safe to persist in
// control-plane records.
func (r *Repository) PutExecutionOutput(ctx context.Context, workspaceID, taskID, executionID, stream string, content []byte) (Entry, error) {
	if err := ValidateIdentifier("workspace_id", workspaceID); err != nil {
		return Entry{}, err
	}
	if err := ValidateIdentifier("task_id", taskID); err != nil {
		return Entry{}, err
	}
	if err := ValidateIdentifier("execution_id", executionID); err != nil {
		return Entry{}, err
	}
	if stream != "stdout" && stream != "stderr" {
		return Entry{}, fmt.Errorf("execution output stream must be stdout or stderr")
	}
	if int64(len(content)) > r.cfg.MaxFileBytes {
		return Entry{}, fmt.Errorf("%w: execution %s exceeds %d bytes", ErrQuotaExceeded, stream, r.cfg.MaxFileBytes)
	}
	digest := sha256.Sum256(content)
	hash := hex.EncodeToString(digest[:])
	key := path.Join(r.taskPrefix(workspaceID, taskID), "objects", hash)
	objectURI := r.objectURI(key)
	_, putErr := r.client.PutObject(ctx, &s3.PutObjectInput{
		Bucket:         aws.String(r.cfg.Bucket),
		Key:            aws.String(key),
		Body:           bytes.NewReader(content),
		ContentLength:  aws.Int64(int64(len(content))),
		ContentType:    aws.String("text/plain; charset=utf-8"),
		ChecksumSHA256: aws.String(base64.StdEncoding.EncodeToString(digest[:])),
		Metadata:       map[string]string{"sha256": hash},
		IfNoneMatch:    aws.String("*"),
	})
	if putErr != nil {
		if err := r.verifyObjectBody(ctx, workspaceID, taskID, objectURI, hash, int64(len(content))); err != nil {
			return Entry{}, fmt.Errorf("store immutable execution %s: %w", stream, putErr)
		}
	}
	if err := r.verifyObjectBody(ctx, workspaceID, taskID, objectURI, hash, int64(len(content))); err != nil {
		return Entry{}, fmt.Errorf("verify immutable execution %s: %w", stream, err)
	}
	head, err := r.headObject(ctx, objectURI)
	if err != nil {
		return Entry{}, fmt.Errorf("read immutable execution %s identity: %w", stream, err)
	}
	versionOrETag := ""
	if head.VersionId != nil && *head.VersionId != "" {
		versionOrETag = "version:" + *head.VersionId
	} else if head.ETag != nil {
		versionOrETag = strings.Trim(*head.ETag, `"`)
	}
	entry := Entry{
		RelativePath:        path.Join(".agentarea", "executions", executionID, stream+".txt"),
		ObjectURI:           objectURI,
		ObjectVersionOrETag: versionOrETag,
		SHA256:              hash,
		Size:                int64(len(content)),
		ContentType:         "text/plain; charset=utf-8",
		Mode:                0o600,
	}
	if err := entry.Validate(); err != nil {
		return Entry{}, fmt.Errorf("invalid execution output ref: %w", err)
	}
	return entry, nil
}

func (r *Repository) PlanWriteback(ctx context.Context, ref ManifestRef, base Manifest, changes []ChangeDescriptor) (*UploadPlan, error) {
	if err := ref.Validate(); err != nil {
		return nil, err
	}
	if base.Generation != ref.Generation || base.WorkspaceID != ref.WorkspaceID || base.TaskID != ref.TaskID || base.FencingToken != ref.FencingToken {
		return nil, fmt.Errorf("%w: writeback base does not match manifest ref", ErrWorkspaceConflict)
	}
	currentETag, err := r.validateCurrentLease(ctx, ref)
	if err != nil {
		return nil, err
	}
	entries := make(map[string]Entry, len(base.Entries)+len(changes))
	for _, entry := range base.Entries {
		entries[entry.RelativePath] = entry
	}
	uploads := make([]Upload, 0, len(changes))
	changedPaths := make(map[string]struct{}, len(changes))
	for _, change := range changes {
		clean, err := NormalizeRelativePath(change.RelativePath)
		if err != nil || clean != change.RelativePath {
			return nil, fmt.Errorf("invalid output path %q", change.RelativePath)
		}
		if change.Deleted {
			entries[clean] = Entry{RelativePath: clean, Deleted: true}
			changedPaths[clean] = struct{}{}
			continue
		}
		if change.Size < 0 || len(change.SHA256) != 64 || !isLowerHex(change.SHA256) {
			return nil, fmt.Errorf("output %q lacks size/hash identity", clean)
		}
		if change.Size > r.cfg.MaxFileBytes {
			return nil, fmt.Errorf("%w: output %q exceeds %d bytes", ErrQuotaExceeded, clean, r.cfg.MaxFileBytes)
		}
		key := path.Join(r.taskPrefix(ref.WorkspaceID, ref.TaskID), "objects", change.SHA256)
		checksum, _ := hex.DecodeString(change.SHA256)
		put := &s3.PutObjectInput{
			Bucket:         aws.String(r.cfg.Bucket),
			Key:            aws.String(key),
			ContentLength:  aws.Int64(change.Size),
			ContentType:    optionalString(change.ContentType),
			ChecksumSHA256: aws.String(base64.StdEncoding.EncodeToString(checksum)),
			Metadata:       map[string]string{"sha256": change.SHA256},
		}
		signed, err := r.presign.PresignPutObject(ctx, put, func(options *s3.PresignOptions) {
			options.Expires = r.cfg.SignedURLTTL
		})
		if err != nil {
			return nil, fmt.Errorf("sign workspace output %q: %w", clean, err)
		}
		objectURI := r.objectURI(key)
		upload := Upload{
			ChangeDescriptor: change,
			URL:              signed.URL,
			ObjectURI:        objectURI,
			Headers:          flattenHeaders(signed.SignedHeader),
		}
		uploads = append(uploads, upload)
		changedPaths[clean] = struct{}{}
		entries[clean] = Entry{
			RelativePath: clean,
			ObjectURI:    objectURI,
			SHA256:       change.SHA256,
			Size:         change.Size,
			ContentType:  change.ContentType,
			Mode:         change.Mode,
		}
	}
	var liveFiles int
	var totalBytes int64
	for _, entry := range entries {
		if entry.Deleted {
			continue
		}
		liveFiles++
		if entry.Size > r.cfg.MaxFileBytes {
			return nil, fmt.Errorf("%w: workspace file %q exceeds %d bytes", ErrQuotaExceeded, entry.RelativePath, r.cfg.MaxFileBytes)
		}
		totalBytes += entry.Size
	}
	if liveFiles > r.cfg.MaxFiles {
		return nil, fmt.Errorf("%w: workspace files exceed %d", ErrQuotaExceeded, r.cfg.MaxFiles)
	}
	if totalBytes > r.cfg.MaxBytes {
		return nil, fmt.Errorf("%w: workspace bytes exceed %d", ErrQuotaExceeded, r.cfg.MaxBytes)
	}
	ordered := make([]Entry, 0, len(entries))
	for _, entry := range entries {
		ordered = append(ordered, entry)
	}
	sort.Slice(ordered, func(i, j int) bool { return ordered[i].RelativePath < ordered[j].RelativePath })
	next := Manifest{
		SchemaVersion:  SchemaVersion,
		WorkspaceID:    ref.WorkspaceID,
		TaskID:         ref.TaskID,
		Generation:     ref.Generation + 1,
		BaseGeneration: ref.Generation,
		FencingToken:   ref.FencingToken,
		Entries:        ordered,
	}
	return &UploadPlan{BaseRef: ref, NextManifest: next, Uploads: uploads, currentETag: currentETag, changedPaths: changedPaths}, nil
}

func (r *Repository) VerifyAndCommit(ctx context.Context, plan *UploadPlan) (ManifestRef, []Entry, error) {
	if plan == nil {
		return ManifestRef{}, nil, fmt.Errorf("upload plan is required")
	}
	currentETag, err := r.validateCurrentLease(ctx, plan.BaseRef)
	if err != nil {
		return ManifestRef{}, nil, err
	}
	if currentETag != plan.currentETag {
		return ManifestRef{}, nil, fmt.Errorf("%w: current pointer changed before commit", ErrWorkspaceConflict)
	}
	for index := range plan.Uploads {
		upload := &plan.Uploads[index]
		if err := r.verifyUpload(ctx, plan.BaseRef, upload); err != nil {
			return ManifestRef{}, nil, err
		}
		for entryIndex := range plan.NextManifest.Entries {
			entry := &plan.NextManifest.Entries[entryIndex]
			if entry.RelativePath != upload.RelativePath {
				continue
			}
			head, err := r.headObject(ctx, upload.ObjectURI)
			if err != nil {
				return ManifestRef{}, nil, err
			}
			if head.VersionId != nil && *head.VersionId != "" {
				entry.ObjectVersionOrETag = "version:" + *head.VersionId
			} else if head.ETag != nil {
				entry.ObjectVersionOrETag = strings.Trim(*head.ETag, `"`)
			}
		}
	}
	manifestBytes, err := json.Marshal(plan.NextManifest)
	if err != nil {
		return ManifestRef{}, nil, fmt.Errorf("encode next workspace manifest: %w", err)
	}
	hash := sha256.Sum256(manifestBytes)
	manifestHash := hex.EncodeToString(hash[:])
	manifestKey := r.manifestKey(plan.BaseRef.WorkspaceID, plan.BaseRef.TaskID, plan.NextManifest.Generation, manifestHash)
	if _, err := r.client.PutObject(ctx, &s3.PutObjectInput{
		Bucket:        aws.String(r.cfg.Bucket),
		Key:           aws.String(manifestKey),
		Body:          bytes.NewReader(manifestBytes),
		ContentLength: aws.Int64(int64(len(manifestBytes))),
		ContentType:   aws.String("application/json"),
		Metadata:      map[string]string{"sha256": manifestHash},
		IfNoneMatch:   aws.String("*"),
	}); err != nil {
		if verifyErr := r.verifyExistingManifest(ctx, manifestKey, manifestHash); verifyErr != nil {
			return ManifestRef{}, nil, fmt.Errorf("store immutable workspace manifest: %w", err)
		}
	}
	nextRef := ManifestRef{
		SchemaVersion:  SchemaVersion,
		WorkspaceID:    plan.BaseRef.WorkspaceID,
		TaskID:         plan.BaseRef.TaskID,
		Generation:     plan.NextManifest.Generation,
		ManifestURI:    r.objectURI(manifestKey),
		ManifestSHA256: manifestHash,
		BaseGeneration: plan.BaseRef.Generation,
		FencingToken:   plan.BaseRef.FencingToken,
	}
	pointerBytes, _ := json.Marshal(nextRef)
	if _, err := r.client.PutObject(ctx, &s3.PutObjectInput{
		Bucket:        aws.String(r.cfg.Bucket),
		Key:           aws.String(path.Join(r.taskPrefix(nextRef.WorkspaceID, nextRef.TaskID), "current.json")),
		Body:          bytes.NewReader(pointerBytes),
		ContentLength: aws.Int64(int64(len(pointerBytes))),
		ContentType:   aws.String("application/json"),
		IfMatch:       aws.String(plan.currentETag),
	}); err != nil {
		return ManifestRef{}, nil, fmt.Errorf("%w: advance workspace current pointer: %v", ErrWorkspaceConflict, err)
	}
	changedEntries := make([]Entry, 0, len(plan.changedPaths))
	for _, entry := range plan.NextManifest.Entries {
		if _, ok := plan.changedPaths[entry.RelativePath]; ok {
			changedEntries = append(changedEntries, entry)
		}
	}
	return nextRef, changedEntries, nil
}

// RecoverCommittedSuccessor detects the narrow crash window after a workspace
// generation was committed but before the execution record was finalized. It
// only accepts the direct successor created with the same fencing token; a
// different current pointer is a conflict, never evidence that this execution
// may be replayed.
func (r *Repository) RecoverCommittedSuccessor(ctx context.Context, baseRef ManifestRef) (ManifestRef, []Entry, bool, error) {
	if err := baseRef.Validate(); err != nil {
		return ManifestRef{}, nil, false, err
	}
	currentRef, err := r.loadCurrentRef(ctx, baseRef.WorkspaceID, baseRef.TaskID)
	if err != nil {
		return ManifestRef{}, nil, false, err
	}
	if currentRef == baseRef {
		return ManifestRef{}, nil, false, nil
	}
	if currentRef.WorkspaceID != baseRef.WorkspaceID ||
		currentRef.TaskID != baseRef.TaskID ||
		currentRef.Generation != baseRef.Generation+1 ||
		currentRef.BaseGeneration != baseRef.Generation ||
		currentRef.FencingToken != baseRef.FencingToken {
		return ManifestRef{}, nil, false, fmt.Errorf("%w: current workspace generation is not the execution's direct successor", ErrWorkspaceConflict)
	}
	baseManifest, err := r.loadManifest(ctx, baseRef)
	if err != nil {
		return ManifestRef{}, nil, false, err
	}
	currentManifest, err := r.loadManifest(ctx, currentRef)
	if err != nil {
		return ManifestRef{}, nil, false, err
	}
	baseEntries := make(map[string]Entry, len(baseManifest.Entries))
	for _, entry := range baseManifest.Entries {
		baseEntries[entry.RelativePath] = entry
	}
	changed := make([]Entry, 0)
	for _, entry := range currentManifest.Entries {
		if previous, exists := baseEntries[entry.RelativePath]; !exists || previous != entry {
			changed = append(changed, entry)
		}
		delete(baseEntries, entry.RelativePath)
	}
	if len(baseEntries) != 0 {
		return ManifestRef{}, nil, false, fmt.Errorf("%w: successor manifest removed paths without tombstones", ErrWorkspaceConflict)
	}
	return currentRef, changed, true, nil
}

func (r *Repository) loadManifest(ctx context.Context, ref ManifestRef) (Manifest, error) {
	if err := ref.Validate(); err != nil {
		return Manifest{}, err
	}
	_, key, err := r.authorizeObjectURI(ref.WorkspaceID, ref.TaskID, ref.ManifestURI, path.Join("manifests", fmt.Sprintf("%d-%s.json", ref.Generation, ref.ManifestSHA256)))
	if err != nil {
		return Manifest{}, err
	}
	output, err := r.client.GetObject(ctx, &s3.GetObjectInput{Bucket: aws.String(r.cfg.Bucket), Key: aws.String(key)})
	if err != nil {
		return Manifest{}, fmt.Errorf("load workspace manifest: %w", err)
	}
	defer output.Body.Close()
	data, err := io.ReadAll(io.LimitReader(output.Body, 16*1024*1024+1))
	if err != nil || len(data) > 16*1024*1024 {
		return Manifest{}, fmt.Errorf("read workspace manifest: invalid size or body: %w", err)
	}
	hash := sha256.Sum256(data)
	if hex.EncodeToString(hash[:]) != ref.ManifestSHA256 {
		return Manifest{}, fmt.Errorf("workspace manifest checksum mismatch")
	}
	manifest, err := DecodeManifest(data)
	if err != nil {
		return Manifest{}, err
	}
	if manifest.SchemaVersion != ref.SchemaVersion || manifest.WorkspaceID != ref.WorkspaceID || manifest.TaskID != ref.TaskID || manifest.Generation != ref.Generation || manifest.BaseGeneration != ref.BaseGeneration || manifest.FencingToken != ref.FencingToken {
		return Manifest{}, fmt.Errorf("workspace manifest identity mismatch")
	}
	var liveFiles int
	var total int64
	for _, entry := range manifest.Entries {
		if entry.Deleted {
			continue
		}
		liveFiles++
		if entry.Size > r.cfg.MaxFileBytes {
			return Manifest{}, fmt.Errorf("%w: workspace file %q exceeds %d bytes", ErrQuotaExceeded, entry.RelativePath, r.cfg.MaxFileBytes)
		}
		total += entry.Size
		if total > r.cfg.MaxBytes {
			return Manifest{}, fmt.Errorf("%w: workspace bytes exceed %d", ErrQuotaExceeded, r.cfg.MaxBytes)
		}
		if _, _, err := r.authorizeObjectURI(ref.WorkspaceID, ref.TaskID, entry.ObjectURI, "objects/"+entry.SHA256); err != nil {
			return Manifest{}, err
		}
	}
	if liveFiles > r.cfg.MaxFiles {
		return Manifest{}, fmt.Errorf("%w: workspace files exceed %d", ErrQuotaExceeded, r.cfg.MaxFiles)
	}
	return manifest, nil
}

// ReleaseLease expires only the lease identified by the ref's fencing token.
// The conditional write prevents a stale execution from releasing a newer
// owner's lease if it changes between the read and the write.
func (r *Repository) ReleaseLease(ctx context.Context, ref ManifestRef) error {
	if err := ref.Validate(); err != nil {
		return err
	}
	key := path.Join(r.taskPrefix(ref.WorkspaceID, ref.TaskID), "lease.json")
	leaseObject, err := r.client.GetObject(ctx, &s3.GetObjectInput{Bucket: aws.String(r.cfg.Bucket), Key: aws.String(key)})
	if err != nil {
		return fmt.Errorf("load workspace lease for release: %w", err)
	}
	leaseBytes, readErr := io.ReadAll(io.LimitReader(leaseObject.Body, 64*1024))
	leaseObject.Body.Close()
	if readErr != nil {
		return fmt.Errorf("read workspace lease for release: %w", readErr)
	}
	var lease leaseRecord
	if err := json.Unmarshal(leaseBytes, &lease); err != nil {
		return fmt.Errorf("decode workspace lease for release: %w", err)
	}
	if lease.Owner == "" || lease.FencingToken != ref.FencingToken {
		return fmt.Errorf("%w: refusing to release a newer workspace lease", ErrWorkspaceConflict)
	}
	if !lease.ExpiresAt.After(time.Now().UTC()) {
		return nil
	}
	if leaseObject.ETag == nil || *leaseObject.ETag == "" {
		return fmt.Errorf("workspace lease lacks immutable ETag")
	}
	lease.ExpiresAt = time.Unix(0, 0).UTC()
	body, err := json.Marshal(lease)
	if err != nil {
		return fmt.Errorf("encode released workspace lease: %w", err)
	}
	if _, err := r.client.PutObject(ctx, &s3.PutObjectInput{
		Bucket:        aws.String(r.cfg.Bucket),
		Key:           aws.String(key),
		Body:          bytes.NewReader(body),
		ContentLength: aws.Int64(int64(len(body))),
		ContentType:   aws.String("application/json"),
		IfMatch:       leaseObject.ETag,
	}); err != nil {
		return fmt.Errorf("%w: release workspace lease: %v", ErrWorkspaceConflict, err)
	}
	return nil
}

// RenewLease extends the active lease identified by the manifest's fencing
// token. The conditional write ensures a delayed runner cannot overwrite a
// lease acquired by a newer owner after the read.
func (r *Repository) RenewLease(ctx context.Context, ref ManifestRef, ttl time.Duration) error {
	if err := ref.Validate(); err != nil {
		return err
	}
	if ttl <= 0 {
		return fmt.Errorf("workspace lease renewal TTL must be positive")
	}
	key := path.Join(r.taskPrefix(ref.WorkspaceID, ref.TaskID), "lease.json")
	leaseObject, err := r.client.GetObject(ctx, &s3.GetObjectInput{Bucket: aws.String(r.cfg.Bucket), Key: aws.String(key)})
	if err != nil {
		return fmt.Errorf("load workspace lease for renewal: %w", err)
	}
	leaseBytes, readErr := io.ReadAll(io.LimitReader(leaseObject.Body, 64*1024))
	leaseObject.Body.Close()
	if readErr != nil {
		return fmt.Errorf("read workspace lease for renewal: %w", readErr)
	}
	var lease leaseRecord
	if err := json.Unmarshal(leaseBytes, &lease); err != nil {
		return fmt.Errorf("decode workspace lease for renewal: %w", err)
	}
	now := time.Now().UTC()
	if lease.Owner == "" || lease.FencingToken != ref.FencingToken || !lease.ExpiresAt.After(now) {
		return fmt.Errorf("%w: refusing to renew a stale workspace lease", ErrWorkspaceConflict)
	}
	if leaseObject.ETag == nil || *leaseObject.ETag == "" {
		return fmt.Errorf("workspace lease lacks immutable ETag")
	}
	if renewedUntil := now.Add(ttl); renewedUntil.After(lease.ExpiresAt) {
		lease.ExpiresAt = renewedUntil
	}
	body, err := json.Marshal(lease)
	if err != nil {
		return fmt.Errorf("encode renewed workspace lease: %w", err)
	}
	if _, err := r.client.PutObject(ctx, &s3.PutObjectInput{
		Bucket:        aws.String(r.cfg.Bucket),
		Key:           aws.String(key),
		Body:          bytes.NewReader(body),
		ContentLength: aws.Int64(int64(len(body))),
		ContentType:   aws.String("application/json"),
		IfMatch:       leaseObject.ETag,
	}); err != nil {
		return fmt.Errorf("%w: renew workspace lease: %v", ErrWorkspaceConflict, err)
	}
	return nil
}

func (r *Repository) verifyUpload(ctx context.Context, ref ManifestRef, upload *Upload) error {
	if upload == nil || upload.Deleted {
		return nil
	}
	_, _, err := r.authorizeObjectURI(ref.WorkspaceID, ref.TaskID, upload.ObjectURI, "objects/"+upload.SHA256)
	if err != nil {
		return err
	}
	head, err := r.headObject(ctx, upload.ObjectURI)
	if err != nil {
		return fmt.Errorf("verify uploaded object %q: %w", upload.RelativePath, err)
	}
	if head.ContentLength == nil || *head.ContentLength != upload.Size || head.Metadata["sha256"] != upload.SHA256 {
		return fmt.Errorf("uploaded object %q size/checksum metadata mismatch", upload.RelativePath)
	}
	bucket, key, _ := r.authorizeObjectURI(ref.WorkspaceID, ref.TaskID, upload.ObjectURI, "objects/"+upload.SHA256)
	object, err := r.client.GetObject(ctx, &s3.GetObjectInput{Bucket: aws.String(bucket), Key: aws.String(key)})
	if err != nil {
		return fmt.Errorf("read uploaded object %q: %w", upload.RelativePath, err)
	}
	defer object.Body.Close()
	hasher := sha256.New()
	written, err := io.Copy(hasher, io.LimitReader(object.Body, upload.Size+1))
	if err != nil || written != upload.Size || hex.EncodeToString(hasher.Sum(nil)) != upload.SHA256 {
		return fmt.Errorf("uploaded object %q body verification failed", upload.RelativePath)
	}
	return nil
}

func (r *Repository) verifyObjectBody(ctx context.Context, workspaceID, taskID, objectURI, expectedHash string, expectedSize int64) error {
	bucket, key, err := r.authorizeObjectURI(workspaceID, taskID, objectURI, "objects/"+expectedHash)
	if err != nil {
		return err
	}
	head, err := r.headObject(ctx, objectURI)
	if err != nil {
		return err
	}
	if head.ContentLength == nil || *head.ContentLength != expectedSize || head.Metadata["sha256"] != expectedHash {
		return fmt.Errorf("object size/checksum metadata mismatch")
	}
	object, err := r.client.GetObject(ctx, &s3.GetObjectInput{Bucket: aws.String(bucket), Key: aws.String(key)})
	if err != nil {
		return err
	}
	defer object.Body.Close()
	hasher := sha256.New()
	written, err := io.Copy(hasher, io.LimitReader(object.Body, expectedSize+1))
	if err != nil || written != expectedSize || hex.EncodeToString(hasher.Sum(nil)) != expectedHash {
		return fmt.Errorf("object body verification failed")
	}
	return nil
}

func (r *Repository) headObject(ctx context.Context, objectURI string) (*s3.HeadObjectOutput, error) {
	parsed, err := url.Parse(objectURI)
	if err != nil {
		return nil, err
	}
	return r.client.HeadObject(ctx, &s3.HeadObjectInput{Bucket: aws.String(parsed.Host), Key: aws.String(strings.TrimPrefix(parsed.Path, "/")), ChecksumMode: types.ChecksumModeEnabled})
}

func (r *Repository) authorizeObjectURI(workspaceID, taskID, objectURI, suffix string) (string, string, error) {
	parsed, err := url.Parse(objectURI)
	if err != nil || parsed.Scheme != "s3" || parsed.Host != r.cfg.Bucket || parsed.RawQuery != "" || parsed.Fragment != "" {
		return "", "", fmt.Errorf("workspace object uses an unauthorized bucket or URI")
	}
	key := strings.TrimPrefix(parsed.Path, "/")
	expected := path.Join(r.taskPrefix(workspaceID, taskID), suffix)
	if key != expected {
		return "", "", fmt.Errorf("workspace object is outside the authorized task prefix")
	}
	return parsed.Host, key, nil
}

func (r *Repository) taskPrefix(workspaceID, taskID string) string {
	return path.Join(r.cfg.Prefix, "workspaces", workspaceID, "tasks", taskID)
}

func (r *Repository) manifestKey(workspaceID, taskID string, generation int64, hash string) string {
	return path.Join(r.taskPrefix(workspaceID, taskID), "manifests", fmt.Sprintf("%d-%s.json", generation, hash))
}

func (r *Repository) objectURI(key string) string {
	return "s3://" + r.cfg.Bucket + "/" + key
}

func (r *Repository) validateCurrentLease(ctx context.Context, expected ManifestRef) (string, error) {
	prefix := r.taskPrefix(expected.WorkspaceID, expected.TaskID)
	currentObject, err := r.client.GetObject(ctx, &s3.GetObjectInput{Bucket: aws.String(r.cfg.Bucket), Key: aws.String(path.Join(prefix, "current.json"))})
	if err != nil {
		return "", fmt.Errorf("load workspace current pointer: %w", err)
	}
	currentBytes, readErr := io.ReadAll(io.LimitReader(currentObject.Body, 64*1024))
	currentObject.Body.Close()
	if readErr != nil {
		return "", fmt.Errorf("read workspace current pointer: %w", readErr)
	}
	var current ManifestRef
	if err := json.Unmarshal(currentBytes, &current); err != nil {
		return "", fmt.Errorf("decode workspace current pointer: %w", err)
	}
	if current != expected {
		return "", fmt.Errorf("%w: base manifest is not current", ErrWorkspaceConflict)
	}
	if currentObject.ETag == nil || *currentObject.ETag == "" {
		return "", fmt.Errorf("workspace current pointer lacks immutable ETag")
	}
	leaseObject, err := r.client.GetObject(ctx, &s3.GetObjectInput{Bucket: aws.String(r.cfg.Bucket), Key: aws.String(path.Join(prefix, "lease.json"))})
	if err != nil {
		return "", fmt.Errorf("load workspace lease: %w", err)
	}
	leaseBytes, readErr := io.ReadAll(io.LimitReader(leaseObject.Body, 64*1024))
	leaseObject.Body.Close()
	if readErr != nil {
		return "", fmt.Errorf("read workspace lease: %w", readErr)
	}
	var lease leaseRecord
	if err := json.Unmarshal(leaseBytes, &lease); err != nil {
		return "", fmt.Errorf("decode workspace lease: %w", err)
	}
	if lease.Owner == "" || lease.FencingToken != expected.FencingToken || !lease.ExpiresAt.After(time.Now().UTC()) {
		return "", fmt.Errorf("%w: workspace lease is stale or expired", ErrWorkspaceConflict)
	}
	return *currentObject.ETag, nil
}

func (r *Repository) loadCurrentRef(ctx context.Context, workspaceID, taskID string) (ManifestRef, error) {
	if err := ValidateIdentifier("workspace_id", workspaceID); err != nil {
		return ManifestRef{}, err
	}
	if err := ValidateIdentifier("task_id", taskID); err != nil {
		return ManifestRef{}, err
	}
	key := path.Join(r.taskPrefix(workspaceID, taskID), "current.json")
	object, err := r.client.GetObject(ctx, &s3.GetObjectInput{Bucket: aws.String(r.cfg.Bucket), Key: aws.String(key)})
	if err != nil {
		return ManifestRef{}, fmt.Errorf("load workspace current pointer: %w", err)
	}
	defer object.Body.Close()
	data, err := io.ReadAll(io.LimitReader(object.Body, 64*1024+1))
	if err != nil || len(data) > 64*1024 {
		return ManifestRef{}, fmt.Errorf("read workspace current pointer: invalid size or body: %w", err)
	}
	var ref ManifestRef
	decoder := json.NewDecoder(bytes.NewReader(data))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(&ref); err != nil {
		return ManifestRef{}, fmt.Errorf("decode workspace current pointer: %w", err)
	}
	if err := ref.Validate(); err != nil {
		return ManifestRef{}, fmt.Errorf("invalid workspace current pointer: %w", err)
	}
	if ref.WorkspaceID != workspaceID || ref.TaskID != taskID {
		return ManifestRef{}, fmt.Errorf("workspace current pointer identity mismatch")
	}
	return ref, nil
}

func (r *Repository) verifyExistingManifest(ctx context.Context, key, expectedHash string) error {
	object, err := r.client.GetObject(ctx, &s3.GetObjectInput{Bucket: aws.String(r.cfg.Bucket), Key: aws.String(key)})
	if err != nil {
		return err
	}
	defer object.Body.Close()
	hasher := sha256.New()
	if _, err := io.Copy(hasher, io.LimitReader(object.Body, 16*1024*1024+1)); err != nil {
		return err
	}
	if hex.EncodeToString(hasher.Sum(nil)) != expectedHash {
		return fmt.Errorf("immutable manifest identity collision")
	}
	return nil
}

func flattenHeaders(headers map[string][]string) map[string]string {
	if len(headers) == 0 {
		return nil
	}
	flattened := make(map[string]string, len(headers))
	for key, values := range headers {
		flattened[key] = strings.Join(values, ",")
	}
	return flattened
}

func optionalString(value string) *string {
	if value == "" {
		return nil
	}
	return aws.String(value)
}

func firstEnv(names ...string) string {
	for _, name := range names {
		if value := os.Getenv(name); value != "" {
			return value
		}
	}
	return ""
}

func firstEnvOr(fallback string, names ...string) string {
	if value := firstEnv(names...); value != "" {
		return value
	}
	return fallback
}
