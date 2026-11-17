// Package blob implements the kernel blob port over S3 with the AWS SDK for
// Go v2: SigV4, path-style addressing against a custom endpoint (RustFS,
// MinIO), explicit static credentials. The SDK's default credential chain and
// AWS_* variables are never read.
package blob

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"errors"
	"fmt"
	"io"
	"iter"
	"net/http"
	"net/url"
	"regexp"
	"strconv"
	"strings"
	"time"

	"github.com/aws/aws-sdk-go-v2/aws"
	v4 "github.com/aws/aws-sdk-go-v2/aws/signer/v4"
	awshttp "github.com/aws/aws-sdk-go-v2/aws/transport/http"
	"github.com/aws/aws-sdk-go-v2/credentials"
	"github.com/aws/aws-sdk-go-v2/service/s3"
	"github.com/aws/aws-sdk-go-v2/service/s3/types"
	"github.com/aws/smithy-go"

	kernel "github.com/agentarea/agentarea/agentarea-platform/internal/kernel/blob"
)

var sha256Hex = regexp.MustCompile(`^[0-9a-f]{64}$`)

// Client holds the two S3 clients Python builds: one against the internal
// endpoint for data operations, one against the public endpoint for signing
// URLs an outside caller can reach.
type Client struct {
	cfg      kernel.Config
	internal *s3.Client
	public   *s3.Client
}

// New builds the clients; no request is made.
func New(cfg kernel.Config) *Client {
	return &Client{cfg: cfg, internal: newS3(cfg, cfg.Endpoint), public: newS3(cfg, cfg.Signing())}
}

func newS3(cfg kernel.Config, endpoint string) *s3.Client {
	return s3.New(s3.Options{
		Region:      cfg.Region,
		Credentials: aws.NewCredentialsCache(credentials.NewStaticCredentialsProvider(cfg.AccessKey, cfg.SecretKey, "")),
		BaseEndpoint: func() *string {
			if endpoint == "" {
				return nil
			}
			return aws.String(endpoint)
		}(),
		UsePathStyle: endpoint != "",
		// S3-compatible stores do not all accept the default CRC trailers;
		// a checksum is sent only when the caller names one.
		RequestChecksumCalculation: aws.RequestChecksumCalculationWhenRequired,
		ResponseChecksumValidation: aws.ResponseChecksumValidationWhenRequired,
	})
}

// Bucket is the store of one bucket.
func (c *Client) Bucket(name string) *Store { return &Store{c: c, bucket: name} }

// Artifacts is the workspace file store's bucket (AGENTAREA_S3_ARTIFACTS_BUCKET).
func (c *Client) Artifacts() *Store { return c.Bucket(c.cfg.ArtifactsBucket) }

// Default is AGENTAREA_S3_BUCKET: harness files and event archives.
func (c *Client) Default() *Store { return c.Bucket(c.cfg.Bucket) }

// Store implements kernel.Store on one bucket.
type Store struct {
	c      *Client
	bucket string
}

var _ kernel.Store = (*Store)(nil)

func b64Checksum(hexDigest string) (string, error) {
	if !sha256Hex.MatchString(hexDigest) {
		return "", errors.New("sha256 must be a 64-character lowercase hex digest")
	}
	raw, _ := hex.DecodeString(hexDigest)
	return base64.StdEncoding.EncodeToString(raw), nil
}

// seekable gives the SDK a body it can hash for SigV4: over plain HTTP it
// refuses a stream it cannot rewind. Python holds the whole body in memory
// too (put_object(Body=bytes)).
func seekable(body io.Reader, size int64) (io.ReadSeeker, int64, error) {
	if rs, ok := body.(io.ReadSeeker); ok {
		if size < 0 {
			n, err := rs.Seek(0, io.SeekEnd)
			if err != nil {
				return nil, 0, err
			}
			if _, err := rs.Seek(0, io.SeekStart); err != nil {
				return nil, 0, err
			}
			size = n
		}
		return rs, size, nil
	}
	if size >= 0 {
		body = io.LimitReader(body, size+1)
	}
	data, err := io.ReadAll(body)
	if err != nil {
		return nil, 0, err
	}
	if size >= 0 && int64(len(data)) != size {
		return nil, 0, fmt.Errorf("body is %d bytes, declared %d", len(data), size)
	}
	return bytes.NewReader(data), int64(len(data)), nil
}

func (s *Store) Put(ctx context.Context, key string, body io.Reader, size int64, opts kernel.PutOptions) error {
	rs, n, err := seekable(body, size)
	if err != nil {
		return fmt.Errorf("put %s: %w", key, err)
	}
	in := &s3.PutObjectInput{Bucket: &s.bucket, Key: &key, Body: rs, ContentLength: aws.Int64(n)}
	if opts.ContentType != "" {
		in.ContentType = &opts.ContentType
	}
	if len(opts.Metadata) > 0 {
		in.Metadata = opts.Metadata
	}
	if opts.SHA256 != "" {
		sum, err := b64Checksum(opts.SHA256)
		if err != nil {
			return err
		}
		in.ChecksumSHA256 = &sum
	}
	if opts.IfMatch != "" {
		in.IfMatch = &opts.IfMatch
	}
	if opts.IfNoneMatch {
		in.IfNoneMatch = aws.String("*")
	}
	if _, err := s.c.internal.PutObject(ctx, in); err != nil {
		return mapErr(key, err)
	}
	return nil
}

func infoFromGet(key string, o *s3.GetObjectOutput) kernel.Info {
	info := kernel.Info{
		Key: key, Size: aws.ToInt64(o.ContentLength), ContentType: aws.ToString(o.ContentType),
		ETag: strings.Trim(aws.ToString(o.ETag), `"`), LastModified: aws.ToTime(o.LastModified), Metadata: lowerKeys(o.Metadata),
	}
	if m := info.Metadata["sha256"]; sha256Hex.MatchString(m) {
		info.SHA256 = m
	}
	return info
}

func (s *Store) Get(ctx context.Context, key string) (io.ReadCloser, kernel.Info, error) {
	o, err := s.c.internal.GetObject(ctx, &s3.GetObjectInput{Bucket: &s.bucket, Key: &key})
	if err != nil {
		return nil, kernel.Info{}, mapErr(key, err)
	}
	return o.Body, infoFromGet(key, o), nil
}

func (s *Store) Stat(ctx context.Context, key string) (kernel.Info, error) {
	o, err := s.c.internal.HeadObject(ctx, &s3.HeadObjectInput{Bucket: &s.bucket, Key: &key, ChecksumMode: types.ChecksumModeEnabled})
	if err != nil {
		return kernel.Info{}, mapErr(key, err)
	}
	info := kernel.Info{
		Key: key, Size: aws.ToInt64(o.ContentLength), ContentType: aws.ToString(o.ContentType),
		ETag: strings.Trim(aws.ToString(o.ETag), `"`), LastModified: aws.ToTime(o.LastModified), Metadata: lowerKeys(o.Metadata),
	}
	info.SHA256 = digestOf(info.Metadata, aws.ToString(o.ChecksumSHA256))
	return info, nil
}

// digestOf is sha256_hex_from_head: the metadata digest when valid, else the
// native checksum when it decodes to 32 bytes, else nothing.
func digestOf(meta map[string]string, checksumB64 string) string {
	if m := meta["sha256"]; sha256Hex.MatchString(m) {
		return m
	}
	if checksumB64 == "" {
		return ""
	}
	raw, err := base64.StdEncoding.Strict().DecodeString(checksumB64)
	if err != nil || len(raw) != sha256.Size {
		return ""
	}
	return hex.EncodeToString(raw)
}

func lowerKeys(m map[string]string) map[string]string {
	out := make(map[string]string, len(m))
	for k, v := range m {
		out[strings.ToLower(k)] = v
	}
	return out
}

func (s *Store) Delete(ctx context.Context, key string) error {
	_, err := s.c.internal.DeleteObject(ctx, &s3.DeleteObjectInput{Bucket: &s.bucket, Key: &key})
	if err != nil {
		return mapErr(key, err)
	}
	return nil
}

// copySource is bucket/key with the key URL-encoded per segment, as S3 requires.
func (s *Store) copySource(key string) string {
	parts := strings.Split(key, "/")
	for i, p := range parts {
		parts[i] = url.PathEscape(p)
	}
	return s.bucket + "/" + strings.Join(parts, "/")
}

func (s *Store) Copy(ctx context.Context, src, dst string, opts kernel.CopyOptions) error {
	in := &s3.CopyObjectInput{Bucket: &s.bucket, Key: &dst, CopySource: aws.String(s.copySource(src))}
	if opts.Replace {
		in.MetadataDirective = types.MetadataDirectiveReplace
		in.Metadata = opts.Metadata
		if opts.ContentType != "" {
			in.ContentType = &opts.ContentType
		}
	}
	if _, err := s.c.internal.CopyObject(ctx, in); err != nil {
		return mapErr(src, err)
	}
	return nil
}

func infoFromObject(o types.Object) kernel.Info {
	return kernel.Info{Key: aws.ToString(o.Key), Size: aws.ToInt64(o.Size), ETag: strings.Trim(aws.ToString(o.ETag), `"`), LastModified: aws.ToTime(o.LastModified)}
}

func (s *Store) List(ctx context.Context, prefix string) iter.Seq2[kernel.Info, error] {
	return func(yield func(kernel.Info, error) bool) {
		p := s3.NewListObjectsV2Paginator(s.c.internal, &s3.ListObjectsV2Input{Bucket: &s.bucket, Prefix: &prefix})
		for p.HasMorePages() {
			page, err := p.NextPage(ctx)
			if err != nil {
				yield(kernel.Info{}, mapErr(prefix, err))
				return
			}
			for _, o := range page.Contents {
				if !yield(infoFromObject(o), nil) {
					return
				}
			}
		}
	}
}

func (s *Store) ListDir(ctx context.Context, prefix string) ([]kernel.Info, []string, error) {
	var objects []kernel.Info
	var folders []string
	p := s3.NewListObjectsV2Paginator(s.c.internal, &s3.ListObjectsV2Input{Bucket: &s.bucket, Prefix: &prefix, Delimiter: aws.String("/")})
	for p.HasMorePages() {
		page, err := p.NextPage(ctx)
		if err != nil {
			return nil, nil, mapErr(prefix, err)
		}
		for _, o := range page.Contents {
			objects = append(objects, infoFromObject(o))
		}
		for _, f := range page.CommonPrefixes {
			folders = append(folders, aws.ToString(f.Prefix))
		}
	}
	return objects, folders, nil
}

func headersOf(h http.Header) map[string]string {
	out := map[string]string{}
	for k, v := range h {
		if strings.EqualFold(k, "host") || len(v) == 0 {
			continue
		}
		if lk := strings.ToLower(k); strings.HasPrefix(lk, "x-amz-") {
			k = lk
		}
		out[k] = v[0]
	}
	return out
}

// uriEncode is S3's canonical path encoding: every byte but the unreserved
// set and "/" is percent-encoded, '+' and ':' included, which url.PathEscape
// leaves alone and the store's own canonicalisation would not.
func uriEncode(path string) string {
	const hexDigits = "0123456789ABCDEF"
	var b strings.Builder
	for i := 0; i < len(path); i++ {
		c := path[i]
		if c >= 'a' && c <= 'z' || c >= 'A' && c <= 'Z' || c >= '0' && c <= '9' || c == '-' || c == '.' || c == '_' || c == '~' || c == '/' {
			b.WriteByte(c)
			continue
		}
		b.WriteByte('%')
		b.WriteByte(hexDigits[c>>4])
		b.WriteByte(hexDigits[c&15])
	}
	return b.String()
}

// objectURL is where the public client addresses key: path-style against a
// custom endpoint, virtual-host style on AWS.
func (s *Store) objectURL(key string) (*url.URL, error) {
	var u *url.URL
	path := "/" + key
	if endpoint := s.c.cfg.Signing(); endpoint != "" {
		base, err := url.Parse(strings.TrimRight(endpoint, "/"))
		if err != nil || base.Host == "" {
			return nil, errors.New("AGENTAREA_S3_PUBLIC_ENDPOINT is not a URL")
		}
		u = base
		path = "/" + s.bucket + path
		u.Path = strings.TrimRight(base.Path, "/") + path
	} else {
		host := "s3." + s.c.cfg.Region + ".amazonaws.com"
		if s.c.cfg.Region == "us-east-1" {
			host = "s3.amazonaws.com"
		}
		u = &url.URL{Scheme: "https", Host: s.bucket + "." + host, Path: path}
	}
	u.RawPath = uriEncode(u.Path)
	return u, nil
}

// presign signs a request against the public endpoint with the payload
// unsigned and every header in h part of the signature, which is what
// botocore's generate_presigned_url does and what the SDK's presign client
// does not: it drops Content-Type and hoists the checksum into the query, so
// the store would stop holding the uploader to either.
func (s *Store) presign(ctx context.Context, method, key string, h http.Header, ttl time.Duration) (kernel.Presigned, error) {
	if ttl <= 0 {
		return kernel.Presigned{}, errors.New("presign ttl must be positive")
	}
	u, err := s.objectURL(key)
	if err != nil {
		return kernel.Presigned{}, err
	}
	q := u.Query()
	q.Set("X-Amz-Expires", strconv.FormatInt(int64(ttl/time.Second), 10))
	u.RawQuery = q.Encode()
	req, err := http.NewRequestWithContext(ctx, method, u.String(), nil)
	if err != nil {
		return kernel.Presigned{}, err
	}
	req.Header = h
	creds, err := s.c.public.Options().Credentials.Retrieve(ctx)
	if err != nil {
		return kernel.Presigned{}, fmt.Errorf("presign %s: %w", key, err)
	}
	signer := v4.NewSigner(func(o *v4.SignerOptions) { o.DisableURIPathEscaping = true; o.DisableHeaderHoisting = true })
	signed, signedHeaders, err := signer.PresignHTTP(ctx, creds, req, "UNSIGNED-PAYLOAD", "s3", s.c.cfg.Region, time.Now())
	if err != nil {
		return kernel.Presigned{}, fmt.Errorf("presign %s: %w", key, err)
	}
	return kernel.Presigned{URL: signed, Headers: headersOf(signedHeaders), TTL: ttl}, nil
}

func (s *Store) PresignGet(ctx context.Context, key string, ttl time.Duration) (kernel.Presigned, error) {
	return s.presign(ctx, http.MethodGet, key, http.Header{}, ttl)
}

// PresignPut binds Content-Type, the SHA-256 checksum and the user metadata
// into the signature (put_object presign), so the store accepts only the
// declared bytes. Conditions are not part of a presigned write.
func (s *Store) PresignPut(ctx context.Context, key string, opts kernel.PutOptions, ttl time.Duration) (kernel.Presigned, error) {
	h := http.Header{}
	if opts.ContentType != "" {
		h.Set("Content-Type", opts.ContentType)
	}
	if opts.SHA256 != "" {
		sum, err := b64Checksum(opts.SHA256)
		if err != nil {
			return kernel.Presigned{}, err
		}
		h.Set("x-amz-checksum-sha256", sum)
	}
	for k, v := range opts.Metadata {
		h.Set("x-amz-meta-"+strings.ToLower(k), v)
	}
	return s.presign(ctx, http.MethodPut, key, h, ttl)
}

func mapErr(key string, err error) error {
	var notFound *types.NotFound
	var noKey *types.NoSuchKey
	if errors.As(err, &notFound) || errors.As(err, &noKey) {
		return fmt.Errorf("%s: %w", key, kernel.ErrNotFound)
	}
	var api smithy.APIError
	if errors.As(err, &api) {
		switch api.ErrorCode() {
		case "NoSuchKey", "NotFound", "404":
			return fmt.Errorf("%s: %w", key, kernel.ErrNotFound)
		case "PreconditionFailed", "412", "ConditionalRequestConflict":
			return fmt.Errorf("%s: %w", key, kernel.ErrPreconditionFailed)
		}
	}
	var re *awshttp.ResponseError
	if errors.As(err, &re) {
		switch re.HTTPStatusCode() {
		case http.StatusNotFound:
			return fmt.Errorf("%s: %w", key, kernel.ErrNotFound)
		case http.StatusPreconditionFailed:
			return fmt.Errorf("%s: %w", key, kernel.ErrPreconditionFailed)
		}
	}
	return fmt.Errorf("s3 %s: %w", key, err)
}
