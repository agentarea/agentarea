package workspace

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"path"
	"sort"
	"strings"

	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/service/s3"
	"github.com/aws/smithy-go"
)

const (
	attachmentInputPrefix   = "inputs/attachments/"
	maxHydrationViewBytes   = 16 * 1024 * 1024
	maxHydrationPinAdvances = 3
)

type hydrationViewRecord struct {
	SchemaVersion int     `json:"schema_version"`
	Prefix        string  `json:"prefix"`
	Entries       []Entry `json:"entries"`
}

// IsAttachmentInputPath accepts exactly inputs/attachments/<one segment>, the
// only shape the platform stages follow-up files into.
func IsAttachmentInputPath(value string) bool {
	normalized, err := NormalizeRelativePath(value)
	if err != nil || normalized != value || !strings.HasPrefix(value, attachmentInputPrefix) {
		return false
	}
	name := strings.TrimPrefix(value, attachmentInputPrefix)
	return name != "" && !strings.Contains(name, "/")
}

// additiveAttachmentDiff reports the paths current adds to previous when every
// previous entry is unchanged and every new entry is an attachment file.
func additiveAttachmentDiff(previous, current []Entry) ([]string, bool) {
	currentByPath := make(map[string]Entry, len(current))
	for _, entry := range current {
		if entry.Deleted {
			return nil, false
		}
		if _, duplicate := currentByPath[entry.RelativePath]; duplicate {
			return nil, false
		}
		currentByPath[entry.RelativePath] = entry
	}
	kept := make(map[string]struct{}, len(previous))
	for _, entry := range previous {
		if _, duplicate := kept[entry.RelativePath]; duplicate {
			return nil, false
		}
		if successor, ok := currentByPath[entry.RelativePath]; !ok || successor != entry {
			return nil, false
		}
		kept[entry.RelativePath] = struct{}{}
	}
	added := make([]string, 0, len(current)-len(previous))
	for _, entry := range current {
		if _, ok := kept[entry.RelativePath]; ok {
			continue
		}
		if !IsAttachmentInputPath(entry.RelativePath) {
			return nil, false
		}
		added = append(added, entry.RelativePath)
	}
	if len(added) == 0 {
		return nil, false
	}
	sort.Strings(added)
	return added, true
}

// hydrationView returns the canonical bytes whose SHA-256 is the revision, so a
// stored view proves its own identity.
func hydrationView(prefix string, entries []Entry) ([]byte, string, error) {
	if entries == nil {
		entries = []Entry{}
	}
	canonical, err := json.Marshal(hydrationViewRecord{SchemaVersion: SchemaVersion, Prefix: prefix, Entries: entries})
	if err != nil {
		return nil, "", fmt.Errorf("encode workspace hydration revision: %w", err)
	}
	digest := sha256.Sum256(canonical)
	return canonical, hex.EncodeToString(digest[:]), nil
}

func (r *Repository) hydrationPinKey(workspaceID, taskID, prefix string) string {
	prefixDigest := sha256.Sum256([]byte(prefix))
	return path.Join(r.taskPrefix(workspaceID, taskID), "hydration-revisions", hex.EncodeToString(prefixDigest[:])+".json")
}

func (r *Repository) hydrationViewKey(workspaceID, taskID, revision string) string {
	return path.Join(r.taskPrefix(workspaceID, taskID), "hydration-views", revision+".json")
}

func (r *Repository) storeHydrationView(ctx context.Context, workspaceID, taskID, revision string, view []byte) error {
	key := r.hydrationViewKey(workspaceID, taskID, revision)
	if _, err := r.client.PutObject(ctx, &s3.PutObjectInput{
		Bucket:        aws.String(r.cfg.Bucket),
		Key:           aws.String(key),
		Body:          bytes.NewReader(view),
		ContentLength: aws.Int64(int64(len(view))),
		ContentType:   aws.String("application/json"),
		IfNoneMatch:   aws.String("*"),
	}); err != nil {
		if verifyErr := r.verifyExistingManifest(ctx, key, revision); verifyErr != nil {
			return fmt.Errorf("store hydration view %s: %w", revision, errors.Join(err, verifyErr))
		}
	}
	return nil
}

var errHydrationViewMissing = errors.New("hydration view missing")

func (r *Repository) loadHydrationView(ctx context.Context, workspaceID, taskID, prefix, revision string) ([]Entry, error) {
	if !isSHA256Hex(revision) {
		return nil, fmt.Errorf("invalid hydration revision %q", revision)
	}
	object, err := r.client.GetObject(ctx, &s3.GetObjectInput{
		Bucket: aws.String(r.cfg.Bucket),
		Key:    aws.String(r.hydrationViewKey(workspaceID, taskID, revision)),
	})
	if err != nil {
		var apiErr smithy.APIError
		if errors.As(err, &apiErr) && (apiErr.ErrorCode() == "NoSuchKey" || apiErr.ErrorCode() == "NotFound" || apiErr.ErrorCode() == "404") {
			return nil, fmt.Errorf("%w: %s", errHydrationViewMissing, revision)
		}
		return nil, fmt.Errorf("load hydration view %s: %w", revision, err)
	}
	defer object.Body.Close()
	body, err := io.ReadAll(io.LimitReader(object.Body, maxHydrationViewBytes+1))
	if err != nil {
		return nil, fmt.Errorf("read hydration view %s: %w", revision, err)
	}
	digest := sha256.Sum256(body)
	if len(body) > maxHydrationViewBytes || hex.EncodeToString(digest[:]) != revision {
		return nil, fmt.Errorf("hydration view %s does not match its revision", revision)
	}
	var view hydrationViewRecord
	decoder := json.NewDecoder(bytes.NewReader(body))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(&view); err != nil {
		return nil, fmt.Errorf("decode hydration view %s: %w", revision, err)
	}
	if view.SchemaVersion != SchemaVersion || view.Prefix != prefix {
		return nil, fmt.Errorf("hydration view %s identity mismatch", revision)
	}
	for _, entry := range view.Entries {
		if err := entry.Validate(); err != nil {
			return nil, fmt.Errorf("hydration view %s: %w", revision, err)
		}
	}
	return view.Entries, nil
}

// HydrationAdditions returns the entries a live sandbox hydrated from
// fromRevision lacks under toRevision. Anything other than a pure addition of
// inputs/attachments/<name> files is a conflict.
func (r *Repository) HydrationAdditions(ctx context.Context, workspaceID, taskID, prefix, fromRevision, toRevision string) ([]Entry, error) {
	if err := ValidateIdentifier("workspace_id", workspaceID); err != nil {
		return nil, err
	}
	if err := ValidateIdentifier("task_id", taskID); err != nil {
		return nil, err
	}
	previous, err := r.loadHydrationView(ctx, workspaceID, taskID, prefix, fromRevision)
	if err != nil {
		return nil, fmt.Errorf("%w: %w", ErrWorkspaceConflict, err)
	}
	current, err := r.loadHydrationView(ctx, workspaceID, taskID, prefix, toRevision)
	if err != nil {
		return nil, fmt.Errorf("%w: %w", ErrWorkspaceConflict, err)
	}
	paths, ok := additiveAttachmentDiff(previous, current)
	if !ok {
		return nil, fmt.Errorf("%w: hydration view %s is not an additive attachment change from %s", ErrWorkspaceConflict, toRevision, fromRevision)
	}
	byPath := make(map[string]Entry, len(current))
	for _, entry := range current {
		byPath[entry.RelativePath] = entry
	}
	additions := make([]Entry, 0, len(paths))
	for _, relativePath := range paths {
		additions = append(additions, byPath[relativePath])
	}
	return additions, nil
}

func (r *Repository) readHydrationPin(ctx context.Context, key, workspaceID, taskID, prefix string) (hydrationRevisionRecord, string, error) {
	object, err := r.client.GetObject(ctx, &s3.GetObjectInput{Bucket: aws.String(r.cfg.Bucket), Key: aws.String(key)})
	if err != nil {
		return hydrationRevisionRecord{}, "", err
	}
	defer object.Body.Close()
	existingBody, readErr := io.ReadAll(io.LimitReader(object.Body, 64*1024+1))
	if readErr != nil || len(existingBody) > 64*1024 {
		return hydrationRevisionRecord{}, "", fmt.Errorf("read hydration revision pin: invalid size or body: %w", readErr)
	}
	var existing hydrationRevisionRecord
	decoder := json.NewDecoder(bytes.NewReader(existingBody))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(&existing); err != nil {
		return hydrationRevisionRecord{}, "", fmt.Errorf("decode hydration revision pin: %w", err)
	}
	if existing.SchemaVersion != SchemaVersion || existing.WorkspaceID != workspaceID || existing.TaskID != taskID || existing.Prefix != prefix {
		return hydrationRevisionRecord{}, "", fmt.Errorf("%w: hydration revision pin identity mismatch", ErrWorkspaceConflict)
	}
	return existing, aws.ToString(object.ETag), nil
}

// advanceHydrationPin moves the pin from existing to revision only for a pure
// attachment addition, by If-Match CAS. A lost race re-reads the pin and
// re-checks against whatever won; it never overwrites.
func (r *Repository) advanceHydrationPin(
	ctx context.Context,
	key string,
	existing hydrationRevisionRecord,
	etag string,
	entries []Entry,
	view []byte,
	revision string,
	pin []byte,
) error {
	var lastPutErr error
	for attempt := 0; ; attempt++ {
		if existing.RevisionSHA256 == revision {
			return nil
		}
		conflict := fmt.Errorf("%w: immutable task input revision changed from %s to %s", ErrWorkspaceConflict, existing.RevisionSHA256, revision)
		previous, err := r.loadHydrationView(ctx, existing.WorkspaceID, existing.TaskID, existing.Prefix, existing.RevisionSHA256)
		if errors.Is(err, errHydrationViewMissing) {
			return conflict
		}
		if err != nil {
			return fmt.Errorf("%w: %w", conflict, err)
		}
		if _, ok := additiveAttachmentDiff(previous, entries); !ok {
			return conflict
		}
		if etag == "" {
			return fmt.Errorf("%w: hydration revision pin has no ETag for a conditional advance", conflict)
		}
		if attempt >= maxHydrationPinAdvances {
			return fmt.Errorf("%w: hydration revision pin kept changing; last put: %v", conflict, lastPutErr)
		}
		if err := r.storeHydrationView(ctx, existing.WorkspaceID, existing.TaskID, revision, view); err != nil {
			return err
		}
		_, putErr := r.client.PutObject(ctx, &s3.PutObjectInput{
			Bucket:        aws.String(r.cfg.Bucket),
			Key:           aws.String(key),
			Body:          bytes.NewReader(pin),
			ContentLength: aws.Int64(int64(len(pin))),
			ContentType:   aws.String("application/json"),
			IfMatch:       aws.String(etag),
		})
		if putErr == nil {
			return nil
		}
		lastPutErr = putErr
		reread, rereadETag, readErr := r.readHydrationPin(ctx, key, existing.WorkspaceID, existing.TaskID, existing.Prefix)
		if readErr != nil {
			return fmt.Errorf("advance hydration revision pin: %v; re-read pin: %w", putErr, readErr)
		}
		existing, etag = reread, rereadETag
	}
}

func isSHA256Hex(value string) bool {
	return len(value) == sha256.Size*2 && isLowerHex(value)
}
