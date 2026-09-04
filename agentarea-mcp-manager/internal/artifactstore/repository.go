// Package artifactstore persists only files explicitly published from a live
// sandbox. It is intentionally separate from the task input manifest and from
// the ephemeral workspace snapshot lifecycle.
package artifactstore

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"hash"
	"io"
	"mime"
	"os"
	"path"
	"regexp"
	"sort"
	"strings"
	"time"

	"github.com/aws/aws-sdk-go-v2/aws"
	awsconfig "github.com/aws/aws-sdk-go-v2/config"
	"github.com/aws/aws-sdk-go-v2/service/s3"
	"github.com/aws/smithy-go"
	"github.com/google/uuid"

	"github.com/agentarea/mcp-manager/internal/workspace"
)

var (
	artifactIDPattern = regexp.MustCompile(`^art_[0-9a-f]{32}$`)
	sha256Pattern     = regexp.MustCompile(`^[0-9a-f]{64}$`)
)

var ErrArtifactNotFound = errors.New("artifact_not_found")
var ErrArtifactQuotaExceeded = errors.New("artifact_quota_exceeded")

type Config struct {
	Bucket         string
	Prefix         string
	Region         string
	Endpoint       string
	ForcePathStyle bool
	MaxBytes       int64
	MaxCount       int
	MaxTotalBytes  int64
}

type s3Client interface {
	GetObject(context.Context, *s3.GetObjectInput, ...func(*s3.Options)) (*s3.GetObjectOutput, error)
	HeadObject(context.Context, *s3.HeadObjectInput, ...func(*s3.Options)) (*s3.HeadObjectOutput, error)
	PutObject(context.Context, *s3.PutObjectInput, ...func(*s3.Options)) (*s3.PutObjectOutput, error)
	ListObjectsV2(context.Context, *s3.ListObjectsV2Input, ...func(*s3.Options)) (*s3.ListObjectsV2Output, error)
}

type Repository struct {
	cfg    Config
	client s3Client
}

type Artifact struct {
	ID          string    `json:"id"`
	Path        string    `json:"path"`
	Name        string    `json:"name"`
	Size        int64     `json:"size"`
	ContentType string    `json:"content_type"`
	SHA256      string    `json:"sha256"`
	CreatedAt   time.Time `json:"created_at"`
	objectKey   string
}

func ConfigFromWorkspace(workspaceConfig workspace.RepositoryConfig) Config {
	return Config{
		Bucket:         workspaceConfig.Bucket,
		Prefix:         workspaceConfig.Prefix,
		Region:         workspaceConfig.Region,
		Endpoint:       workspaceConfig.Endpoint,
		ForcePathStyle: workspaceConfig.ForcePathStyle,
		MaxBytes:       workspaceConfig.MaxFileBytes,
		MaxCount:       workspaceConfig.MaxFiles,
		MaxTotalBytes:  workspaceConfig.MaxBytes,
	}
}

func NewFromConfig(ctx context.Context, cfg Config) (*Repository, error) {
	if cfg.Bucket == "" {
		return nil, fmt.Errorf("artifact S3 bucket is required")
	}
	awsCfg, err := awsconfig.LoadDefaultConfig(ctx, awsconfig.WithRegion(cfg.Region))
	if err != nil {
		return nil, fmt.Errorf("load artifact S3 configuration: %w", err)
	}
	client := s3.NewFromConfig(awsCfg, func(options *s3.Options) {
		options.UsePathStyle = cfg.ForcePathStyle
		if cfg.Endpoint != "" {
			options.BaseEndpoint = aws.String(cfg.Endpoint)
		}
	})
	return New(cfg, client)
}

func New(cfg Config, client s3Client) (*Repository, error) {
	if cfg.Bucket == "" || client == nil {
		return nil, fmt.Errorf("artifact bucket and S3 client are required")
	}
	if cfg.MaxBytes <= 0 || cfg.MaxCount <= 0 || cfg.MaxTotalBytes <= 0 || cfg.MaxBytes > cfg.MaxTotalBytes {
		return nil, fmt.Errorf("artifact file, count, and total byte limits must be positive and internally consistent")
	}
	cfg.Prefix = strings.Trim(cfg.Prefix, "/")
	return &Repository{cfg: cfg, client: client}, nil
}

type quotaLedger struct {
	SchemaVersion int                   `json:"schema_version"`
	WorkspaceID   string                `json:"workspace_id"`
	TaskID        string                `json:"task_id"`
	Entries       map[string]quotaEntry `json:"entries"`
}

type quotaEntry struct {
	Size             int64     `json:"size"`
	Published        bool      `json:"published"`
	ReservationToken string    `json:"reservation_token,omitempty"`
	ReservedUntil    time.Time `json:"reserved_until,omitempty"`
}

const artifactLedgerSchemaVersion = 1
const artifactReservationTTL = time.Hour

func (r *Repository) Publish(ctx context.Context, workspaceID, taskID, sourcePath, contentType string, content []byte) (Artifact, error) {
	return r.PublishStream(ctx, workspaceID, taskID, sourcePath, contentType, bytes.NewReader(content), int64(len(content)))
}

// PublishStream promotes one live sandbox file without routing its bytes
// through JSON/base64 or retaining the whole object in manager memory. A
// bounded temporary spool establishes the digest before the content-addressed
// S3 key is chosen; the spool is removed on every path.
func (r *Repository) PublishStream(ctx context.Context, workspaceID, taskID, sourcePath, contentType string, source io.Reader, expectedSize int64) (Artifact, error) {
	if err := workspace.ValidateIdentifier("workspace_id", workspaceID); err != nil {
		return Artifact{}, err
	}
	if err := workspace.ValidateIdentifier("task_id", taskID); err != nil {
		return Artifact{}, err
	}
	normalized, err := workspace.NormalizeRelativePath(sourcePath)
	if err != nil {
		return Artifact{}, err
	}
	if source == nil || expectedSize < 0 || expectedSize > r.cfg.MaxBytes {
		return Artifact{}, fmt.Errorf("artifact exceeds %d byte limit", r.cfg.MaxBytes)
	}
	temp, err := os.CreateTemp("", "agentarea-artifact-*")
	if err != nil {
		return Artifact{}, fmt.Errorf("create artifact spool: %w", err)
	}
	tempName := temp.Name()
	defer func() {
		_ = temp.Close()
		_ = os.Remove(tempName)
	}()
	hasher := sha256.New()
	written, err := io.Copy(io.MultiWriter(temp, hasher), io.LimitReader(source, expectedSize+1))
	if err != nil {
		return Artifact{}, fmt.Errorf("spool artifact: %w", err)
	}
	if written != expectedSize {
		return Artifact{}, fmt.Errorf("artifact size changed during publication: got %d, expected %d", written, expectedSize)
	}
	if err := temp.Sync(); err != nil {
		return Artifact{}, fmt.Errorf("sync artifact spool: %w", err)
	}
	if _, err := temp.Seek(0, io.SeekStart); err != nil {
		return Artifact{}, fmt.Errorf("rewind artifact spool: %w", err)
	}
	digest := hasher.Sum(nil)
	hash := hex.EncodeToString(digest)
	id := deriveArtifactID(normalized, hash)
	reservationToken, err := r.reserveArtifact(ctx, workspaceID, taskID, id, expectedSize)
	if err != nil {
		return Artifact{}, err
	}
	reservationCommitted := false
	defer func() {
		if reservationToken != "" && !reservationCommitted {
			_ = r.releaseArtifactReservation(context.Background(), workspaceID, taskID, id, reservationToken)
		}
	}()
	name := path.Base(normalized)
	if contentType == "" {
		contentType = mime.TypeByExtension(path.Ext(name))
		if contentType == "" {
			contentType = "application/octet-stream"
		}
	}
	key := path.Join(r.artifactPrefix(workspaceID, taskID), id, name)
	now := time.Now().UTC()
	_, putErr := r.client.PutObject(ctx, &s3.PutObjectInput{
		Bucket:         aws.String(r.cfg.Bucket),
		Key:            aws.String(key),
		Body:           temp,
		ContentLength:  aws.Int64(expectedSize),
		ContentType:    aws.String(contentType),
		ChecksumSHA256: aws.String(base64.StdEncoding.EncodeToString(digest)),
		Metadata: map[string]string{
			"sha256":      hash,
			"source-path": base64.RawURLEncoding.EncodeToString([]byte(normalized)),
		},
		IfNoneMatch: aws.String("*"),
	})
	if putErr != nil {
		var apiErr smithy.APIError
		if !errors.As(putErr, &apiErr) || (apiErr.ErrorCode() != "PreconditionFailed" && apiErr.ErrorCode() != "412") {
			return Artifact{}, fmt.Errorf("publish artifact: %w", putErr)
		}
		head, err := r.client.HeadObject(ctx, &s3.HeadObjectInput{Bucket: aws.String(r.cfg.Bucket), Key: aws.String(key)})
		if err != nil || aws.ToInt64(head.ContentLength) != expectedSize || head.Metadata["sha256"] != hash {
			return Artifact{}, fmt.Errorf("artifact identity collision")
		}
		contentType = aws.ToString(head.ContentType)
		if head.LastModified != nil {
			now = head.LastModified.UTC()
		}
	}
	if reservationToken != "" {
		if err := r.publishArtifactReservation(ctx, workspaceID, taskID, id, reservationToken); err != nil {
			return Artifact{}, err
		}
	}
	reservationCommitted = true
	return Artifact{ID: id, Path: normalized, Name: name, Size: expectedSize, ContentType: contentType, SHA256: hash, CreatedAt: now, objectKey: key}, nil
}

func (r *Repository) List(ctx context.Context, workspaceID, taskID string) ([]Artifact, error) {
	if err := workspace.ValidateIdentifier("workspace_id", workspaceID); err != nil {
		return nil, err
	}
	if err := workspace.ValidateIdentifier("task_id", taskID); err != nil {
		return nil, err
	}
	prefix := r.artifactPrefix(workspaceID, taskID) + "/"
	ledger, _, err := r.loadQuotaLedger(ctx, workspaceID, taskID)
	if err != nil {
		return nil, err
	}
	var token *string
	items := make([]Artifact, 0)
	for {
		page, err := r.client.ListObjectsV2(ctx, &s3.ListObjectsV2Input{
			Bucket:            aws.String(r.cfg.Bucket),
			Prefix:            aws.String(prefix),
			ContinuationToken: token,
		})
		if err != nil {
			return nil, fmt.Errorf("list artifacts: %w", err)
		}
		for _, object := range page.Contents {
			key := aws.ToString(object.Key)
			relative := strings.TrimPrefix(key, prefix)
			parts := strings.Split(relative, "/")
			if len(parts) != 2 || !artifactIDPattern.MatchString(parts[0]) || parts[1] == "" {
				continue
			}
			entry, admitted := ledger.Entries[parts[0]]
			if !admitted || !entry.Published {
				continue
			}
			head, err := r.client.HeadObject(ctx, &s3.HeadObjectInput{
				Bucket: aws.String(r.cfg.Bucket),
				Key:    aws.String(key),
			})
			if err != nil {
				return nil, fmt.Errorf("read artifact metadata: %w", err)
			}
			hash := head.Metadata["sha256"]
			if !sha256Pattern.MatchString(hash) {
				return nil, fmt.Errorf("artifact %q has no valid content identity", parts[0])
			}
			encoded := head.Metadata["source-path"]
			decoded, decodeErr := base64.RawURLEncoding.DecodeString(encoded)
			if encoded == "" || decodeErr != nil {
				return nil, fmt.Errorf("artifact %q has invalid source path metadata", parts[0])
			}
			sourcePath, normalizeErr := workspace.NormalizeRelativePath(string(decoded))
			if normalizeErr != nil {
				return nil, fmt.Errorf("artifact %q has invalid source path: %w", parts[0], normalizeErr)
			}
			if deriveArtifactID(sourcePath, hash) != parts[0] {
				return nil, fmt.Errorf("artifact %q identity does not match its path and digest", parts[0])
			}
			createdAt := time.Time{}
			if head.LastModified != nil {
				createdAt = head.LastModified.UTC()
			} else if object.LastModified != nil {
				createdAt = object.LastModified.UTC()
			}
			if entry.Size != aws.ToInt64(head.ContentLength) {
				return nil, fmt.Errorf("artifact %q size does not match quota ledger", parts[0])
			}
			items = append(items, Artifact{
				ID:          parts[0],
				Path:        sourcePath,
				Name:        parts[1],
				Size:        aws.ToInt64(head.ContentLength),
				ContentType: aws.ToString(head.ContentType),
				SHA256:      hash,
				CreatedAt:   createdAt,
				objectKey:   key,
			})
		}
		if !aws.ToBool(page.IsTruncated) || page.NextContinuationToken == nil {
			break
		}
		token = page.NextContinuationToken
	}
	sort.Slice(items, func(i, j int) bool {
		if items[i].CreatedAt.Equal(items[j].CreatedAt) {
			return items[i].ID < items[j].ID
		}
		return items[i].CreatedAt.After(items[j].CreatedAt)
	})
	return items, nil
}

func (r *Repository) Get(ctx context.Context, workspaceID, taskID, artifactID string) (Artifact, []byte, error) {
	artifact, content, err := r.Open(ctx, workspaceID, taskID, artifactID)
	if err != nil {
		return Artifact{}, nil, err
	}
	defer content.Close()
	data, err := io.ReadAll(content)
	if err != nil {
		return Artifact{}, nil, fmt.Errorf("read artifact: %w", err)
	}
	return artifact, data, nil
}

// Open returns a verified streaming artifact body. Identity and metadata are
// validated before any bytes are exposed; size and SHA-256 are checked as the
// caller reaches EOF so the API can relay large artifacts in constant memory.
func (r *Repository) Open(ctx context.Context, workspaceID, taskID, artifactID string) (Artifact, io.ReadCloser, error) {
	if err := workspace.ValidateIdentifier("workspace_id", workspaceID); err != nil {
		return Artifact{}, nil, err
	}
	if err := workspace.ValidateIdentifier("task_id", taskID); err != nil {
		return Artifact{}, nil, err
	}
	if !artifactIDPattern.MatchString(artifactID) {
		return Artifact{}, nil, ErrArtifactNotFound
	}
	ledger, _, err := r.loadQuotaLedger(ctx, workspaceID, taskID)
	if err != nil {
		return Artifact{}, nil, err
	}
	ledgerEntry, admitted := ledger.Entries[artifactID]
	if !admitted || !ledgerEntry.Published {
		return Artifact{}, nil, ErrArtifactNotFound
	}
	prefix := path.Join(r.artifactPrefix(workspaceID, taskID), artifactID) + "/"
	page, err := r.client.ListObjectsV2(ctx, &s3.ListObjectsV2Input{Bucket: aws.String(r.cfg.Bucket), Prefix: aws.String(prefix), MaxKeys: aws.Int32(2)})
	if err != nil {
		return Artifact{}, nil, err
	}
	if len(page.Contents) != 1 {
		return Artifact{}, nil, ErrArtifactNotFound
	}
	key := aws.ToString(page.Contents[0].Key)
	object, err := r.client.GetObject(ctx, &s3.GetObjectInput{Bucket: aws.String(r.cfg.Bucket), Key: aws.String(key)})
	if err != nil {
		return Artifact{}, nil, err
	}
	size := aws.ToInt64(object.ContentLength)
	if size < 0 || size > r.cfg.MaxBytes {
		object.Body.Close()
		return Artifact{}, nil, fmt.Errorf("artifact exceeds %d byte limit", r.cfg.MaxBytes)
	}
	if size != ledgerEntry.Size {
		object.Body.Close()
		return Artifact{}, nil, fmt.Errorf("artifact size does not match quota ledger")
	}
	hash := object.Metadata["sha256"]
	if !sha256Pattern.MatchString(hash) {
		object.Body.Close()
		return Artifact{}, nil, fmt.Errorf("artifact checksum verification failed")
	}
	encoded := object.Metadata["source-path"]
	decoded, decodeErr := base64.RawURLEncoding.DecodeString(encoded)
	if encoded == "" || decodeErr != nil {
		object.Body.Close()
		return Artifact{}, nil, fmt.Errorf("artifact has invalid source path metadata")
	}
	sourcePath, normalizeErr := workspace.NormalizeRelativePath(string(decoded))
	if normalizeErr != nil {
		object.Body.Close()
		return Artifact{}, nil, fmt.Errorf("artifact has invalid source path: %w", normalizeErr)
	}
	if deriveArtifactID(sourcePath, hash) != artifactID {
		object.Body.Close()
		return Artifact{}, nil, fmt.Errorf("artifact identity does not match its path and digest")
	}
	createdAt := time.Time{}
	if object.LastModified != nil {
		createdAt = object.LastModified.UTC()
	}
	item := Artifact{ID: artifactID, Path: sourcePath, Name: path.Base(key), Size: size, ContentType: aws.ToString(object.ContentType), SHA256: hash, CreatedAt: createdAt, objectKey: key}
	return item, &verifyingReadCloser{source: object.Body, expectedSize: size, expectedSHA256: hash, hasher: sha256.New()}, nil
}

func (r *Repository) reserveArtifact(ctx context.Context, workspaceID, taskID, artifactID string, size int64) (string, error) {
	token := uuid.NewString()
	err := r.updateQuotaLedger(ctx, workspaceID, taskID, func(ledger *quotaLedger) (bool, error) {
		now := time.Now().UTC()
		pruned := false
		for id, entry := range ledger.Entries {
			if !entry.Published && !entry.ReservedUntil.IsZero() && !now.Before(entry.ReservedUntil) {
				delete(ledger.Entries, id)
				pruned = true
			}
		}
		if existing, ok := ledger.Entries[artifactID]; ok {
			if existing.Size != size {
				return false, fmt.Errorf("artifact quota identity collision")
			}
			if existing.Published {
				token = ""
				return pruned, nil
			}
			if now.Before(existing.ReservedUntil) {
				return false, fmt.Errorf("artifact publication is already in progress")
			}
			existing.ReservationToken = token
			existing.ReservedUntil = now.Add(artifactReservationTTL)
			ledger.Entries[artifactID] = existing
			return true, nil
		}
		var total int64
		for _, entry := range ledger.Entries {
			total += entry.Size
		}
		if len(ledger.Entries)+1 > r.cfg.MaxCount || size > r.cfg.MaxTotalBytes-total {
			return false, fmt.Errorf("%w: artifact count or total bytes would exceed policy", ErrArtifactQuotaExceeded)
		}
		ledger.Entries[artifactID] = quotaEntry{
			Size: size, ReservationToken: token,
			ReservedUntil: now.Add(artifactReservationTTL),
		}
		return true, nil
	})
	return token, err
}

func (r *Repository) publishArtifactReservation(ctx context.Context, workspaceID, taskID, artifactID, token string) error {
	return r.updateQuotaLedger(ctx, workspaceID, taskID, func(ledger *quotaLedger) (bool, error) {
		entry, ok := ledger.Entries[artifactID]
		if !ok || entry.ReservationToken != token || entry.Published {
			return false, fmt.Errorf("artifact reservation ownership was lost")
		}
		entry.Published = true
		entry.ReservationToken = ""
		entry.ReservedUntil = time.Time{}
		ledger.Entries[artifactID] = entry
		return true, nil
	})
}

func (r *Repository) releaseArtifactReservation(ctx context.Context, workspaceID, taskID, artifactID, token string) error {
	return r.updateQuotaLedger(ctx, workspaceID, taskID, func(ledger *quotaLedger) (bool, error) {
		entry, ok := ledger.Entries[artifactID]
		if !ok || entry.Published || entry.ReservationToken != token {
			return false, nil
		}
		delete(ledger.Entries, artifactID)
		return true, nil
	})
}

func (r *Repository) updateQuotaLedger(
	ctx context.Context,
	workspaceID, taskID string,
	mutate func(*quotaLedger) (bool, error),
) error {
	for attempts := 0; attempts < 32; attempts++ {
		ledger, etag, err := r.loadQuotaLedger(ctx, workspaceID, taskID)
		if err != nil {
			return err
		}
		changed, err := mutate(&ledger)
		if err != nil || !changed {
			return err
		}
		if err := r.putQuotaLedger(ctx, ledger, etag); err != nil {
			if isPreconditionFailed(err) {
				continue
			}
			return err
		}
		return nil
	}
	return fmt.Errorf("update artifact quota ledger after repeated concurrent conflicts")
}

func (r *Repository) loadQuotaLedger(ctx context.Context, workspaceID, taskID string) (quotaLedger, string, error) {
	ledger := quotaLedger{
		SchemaVersion: artifactLedgerSchemaVersion,
		WorkspaceID:   workspaceID,
		TaskID:        taskID,
		Entries:       make(map[string]quotaEntry),
	}
	object, err := r.client.GetObject(ctx, &s3.GetObjectInput{
		Bucket: aws.String(r.cfg.Bucket), Key: aws.String(r.quotaLedgerKey(workspaceID, taskID)),
	})
	if err != nil {
		if isNotFound(err) {
			return ledger, "", nil
		}
		return quotaLedger{}, "", fmt.Errorf("read artifact quota ledger: %w", err)
	}
	defer object.Body.Close()
	maxLedgerBytes := int64(r.cfg.MaxCount)*256 + 4096
	body, err := io.ReadAll(io.LimitReader(object.Body, maxLedgerBytes+1))
	if err != nil || int64(len(body)) > maxLedgerBytes {
		return quotaLedger{}, "", fmt.Errorf("read artifact quota ledger body: %w", err)
	}
	decoder := json.NewDecoder(bytes.NewReader(body))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(&ledger); err != nil {
		return quotaLedger{}, "", fmt.Errorf("decode artifact quota ledger: %w", err)
	}
	if ledger.SchemaVersion != artifactLedgerSchemaVersion || ledger.WorkspaceID != workspaceID || ledger.TaskID != taskID || ledger.Entries == nil {
		return quotaLedger{}, "", fmt.Errorf("artifact quota ledger identity is invalid")
	}
	var total int64
	for id, entry := range ledger.Entries {
		if !artifactIDPattern.MatchString(id) || entry.Size < 0 || entry.Size > r.cfg.MaxBytes {
			return quotaLedger{}, "", fmt.Errorf("artifact quota ledger entry is invalid")
		}
		total += entry.Size
		if total > r.cfg.MaxTotalBytes {
			return quotaLedger{}, "", fmt.Errorf("artifact quota ledger exceeds configured total")
		}
	}
	if len(ledger.Entries) > r.cfg.MaxCount {
		return quotaLedger{}, "", fmt.Errorf("artifact quota ledger exceeds configured count")
	}
	return ledger, aws.ToString(object.ETag), nil
}

func (r *Repository) putQuotaLedger(ctx context.Context, ledger quotaLedger, etag string) error {
	body, err := json.Marshal(ledger)
	if err != nil {
		return fmt.Errorf("encode artifact quota ledger: %w", err)
	}
	digest := sha256.Sum256(body)
	input := &s3.PutObjectInput{
		Bucket: aws.String(r.cfg.Bucket), Key: aws.String(r.quotaLedgerKey(ledger.WorkspaceID, ledger.TaskID)),
		Body: bytes.NewReader(body), ContentLength: aws.Int64(int64(len(body))),
		ContentType: aws.String("application/json"), ChecksumSHA256: aws.String(base64.StdEncoding.EncodeToString(digest[:])),
	}
	if etag == "" {
		input.IfNoneMatch = aws.String("*")
	} else {
		input.IfMatch = aws.String(etag)
	}
	if _, err := r.client.PutObject(ctx, input); err != nil {
		return fmt.Errorf("write artifact quota ledger: %w", err)
	}
	return nil
}

func (r *Repository) quotaLedgerKey(workspaceID, taskID string) string {
	return path.Join(r.artifactPrefix(workspaceID, taskID), "_quota-ledger.json")
}

func isPreconditionFailed(err error) bool {
	var apiErr smithy.APIError
	return errors.As(err, &apiErr) && (apiErr.ErrorCode() == "PreconditionFailed" || apiErr.ErrorCode() == "412")
}

func isNotFound(err error) bool {
	var apiErr smithy.APIError
	return errors.As(err, &apiErr) && (apiErr.ErrorCode() == "NoSuchKey" || apiErr.ErrorCode() == "NotFound" || apiErr.ErrorCode() == "404")
}

type verifyingReadCloser struct {
	source         io.ReadCloser
	expectedSize   int64
	expectedSHA256 string
	hasher         hash.Hash
	read           int64
	verified       bool
}

func (r *verifyingReadCloser) Read(buffer []byte) (int, error) {
	n, err := r.source.Read(buffer)
	if n > 0 {
		r.read += int64(n)
		_, _ = r.hasher.Write(buffer[:n])
		if r.read > r.expectedSize {
			return n, fmt.Errorf("artifact size exceeds declared length")
		}
	}
	if errors.Is(err, io.EOF) && !r.verified {
		r.verified = true
		if r.read != r.expectedSize || hex.EncodeToString(r.hasher.Sum(nil)) != r.expectedSHA256 {
			return n, fmt.Errorf("artifact checksum verification failed")
		}
	}
	return n, err
}

func (r *verifyingReadCloser) Close() error { return r.source.Close() }

func (r *Repository) artifactPrefix(workspaceID, taskID string) string {
	base := path.Join("workspaces", workspaceID, "tasks", taskID, "artifacts")
	if r.cfg.Prefix == "" {
		return base
	}
	return path.Join(r.cfg.Prefix, base)
}

func deriveArtifactID(sourcePath, hash string) string {
	identity := sha256.Sum256([]byte(sourcePath + "\x00" + hash))
	return "art_" + hex.EncodeToString(identity[:16])
}
