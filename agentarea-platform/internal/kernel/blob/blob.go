// Package blob is the object store (AGENTAREA_S3_*): one file store scoped by
// key prefix, holding workspace files, task attachments, artifacts and logos.
// Credentials are passed explicitly; the AWS SDK's default chain is never
// used (aa-env-vars: AWS_* is not ours).
//
// A Store is bound to one bucket. Python writes whole objects with one
// put_object and never uses multipart, so neither does this port; a body is a
// single request.
package blob

import (
	"context"
	"errors"
	"io"
	"iter"
	"time"
)

// ErrNotFound is a key with no object.
var ErrNotFound = errors.New("object not found")

// ErrPreconditionFailed is a conditional write that lost: If-Match against a
// changed object, or If-None-Match against one that exists (the
// compare-and-swap the workspace manifest pointer and app storage rely on).
var ErrPreconditionFailed = errors.New("object precondition failed")

// Info describes one object.
type Info struct {
	Key         string
	Size        int64
	ContentType string
	// ETag has its quotes stripped, as Python keeps it, and is what IfMatch takes.
	ETag         string
	LastModified time.Time
	// Metadata is the user metadata, keys lowercased (x-amz-meta-*).
	Metadata map[string]string
	// SHA256 is the object's lowercase-hex digest: the "sha256" user metadata
	// when it is a valid digest and, for Stat only, else the S3-native
	// ChecksumSHA256. Empty when neither exists, so a caller can fail loudly
	// rather than guess (artifacts/service.py sha256_hex_from_head).
	SHA256 string
}

// PutOptions are the headers of a write.
type PutOptions struct {
	ContentType string
	// Metadata is stored as user metadata (x-amz-meta-*).
	Metadata map[string]string
	// SHA256 is the lowercase-hex digest of the body. When set it is sent as
	// ChecksumSHA256, so the store rejects a body that does not hash to it.
	SHA256 string
	// IfMatch makes the write conditional on the object's current ETag.
	IfMatch string
	// IfNoneMatch makes the write conditional on there being no object.
	IfNoneMatch bool
}

// CopyOptions are the headers of a server-side copy. By default metadata and
// content type are copied with the object, so the sha256 metadata survives a
// move; Replace swaps them for the ones given.
type CopyOptions struct {
	Replace     bool
	ContentType string
	Metadata    map[string]string
}

// Presigned is a URL plus the headers the caller must send with it: those
// are part of the signature, so a request without them is refused.
type Presigned struct {
	URL     string
	Headers map[string]string
	TTL     time.Duration
}

// Store is the port the cluster profile implements over S3.
type Store interface {
	// Put writes one object. size is the body length, or -1 when unknown.
	// A lost condition is ErrPreconditionFailed.
	Put(ctx context.Context, key string, body io.Reader, size int64, opts PutOptions) error
	// Get returns ErrNotFound for a missing key; the caller closes the body.
	Get(ctx context.Context, key string) (io.ReadCloser, Info, error)
	// Stat is a HEAD with checksum mode on; ErrNotFound for a missing key.
	Stat(ctx context.Context, key string) (Info, error)
	// Delete succeeds for a missing key, as S3 does.
	Delete(ctx context.Context, key string) error
	// Copy is server-side within the bucket; the bytes never leave the store.
	Copy(ctx context.Context, src, dst string, opts CopyOptions) error
	// List yields every object under prefix, in key order.
	List(ctx context.Context, prefix string) iter.Seq2[Info, error]
	// ListDir is one delimited level: the objects directly under prefix and
	// the "folders" (common prefixes, trailing slash kept) below it. Python
	// uses it to skip whole subtrees (tasks/, .trash/) without walking them.
	ListDir(ctx context.Context, prefix string) (objects []Info, folders []string, err error)
	// PresignGet returns a GET URL valid for ttl, signed against the public
	// endpoint (AGENTAREA_S3_PUBLIC_ENDPOINT, else the internal one). No
	// response-header overrides: what the object serves is what it was stored with.
	PresignGet(ctx context.Context, key string, ttl time.Duration) (Presigned, error)
	// PresignPut returns a PUT URL valid for ttl. ContentType, SHA256 and
	// Metadata are bound into the signature and returned as Headers, which the
	// uploader must send unchanged.
	PresignPut(ctx context.Context, key string, opts PutOptions, ttl time.Duration) (Presigned, error)
}
