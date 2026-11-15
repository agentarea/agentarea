// Package servicetest holds the sandbox service's test doubles.
package servicetest

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"io"
	"iter"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/blob"
)

type object struct {
	data []byte
	info blob.Info
}

// MemStore is an S3 bucket in memory: conditional puts, checksums, copies.
type MemStore struct {
	mu   sync.Mutex
	objs map[string]object
	tag  int
	// FailCopy, when set, can fail a Copy before it writes.
	FailCopy func(src, dst string) error
}

// NewMemStore is an empty bucket.
func NewMemStore() *MemStore { return &MemStore{objs: map[string]object{}} }

func (m *MemStore) Put(_ context.Context, key string, body io.Reader, _ int64, o blob.PutOptions) error {
	data, err := io.ReadAll(body)
	if err != nil {
		return err
	}
	m.mu.Lock()
	defer m.mu.Unlock()
	cur, exists := m.objs[key]
	if o.IfNoneMatch && exists {
		return blob.ErrPreconditionFailed
	}
	if o.IfMatch != "" && (!exists || cur.info.ETag != o.IfMatch) {
		return blob.ErrPreconditionFailed
	}
	sum := sha256.Sum256(data)
	digest := hex.EncodeToString(sum[:])
	if o.SHA256 != "" && o.SHA256 != digest {
		return errors.New("checksum mismatch")
	}
	meta := map[string]string{}
	for k, v := range o.Metadata {
		meta[strings.ToLower(k)] = v
	}
	m.tag++
	info := blob.Info{Key: key, Size: int64(len(data)), ContentType: o.ContentType, ETag: "e" + strconv.Itoa(m.tag),
		LastModified: time.Date(2026, 11, 12, 10, 0, 0, 0, time.UTC), Metadata: meta}
	if regexp.MustCompile(`^[0-9a-f]{64}$`).MatchString(meta["sha256"]) {
		info.SHA256 = meta["sha256"]
	}
	m.objs[key] = object{data: data, info: info}
	return nil
}

func (m *MemStore) Get(_ context.Context, key string) (io.ReadCloser, blob.Info, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	o, ok := m.objs[key]
	if !ok {
		return nil, blob.Info{}, blob.ErrNotFound
	}
	return io.NopCloser(bytes.NewReader(o.data)), o.info, nil
}

func (m *MemStore) Stat(_ context.Context, key string) (blob.Info, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	o, ok := m.objs[key]
	if !ok {
		return blob.Info{}, blob.ErrNotFound
	}
	return o.info, nil
}

func (m *MemStore) Delete(_ context.Context, key string) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	delete(m.objs, key)
	return nil
}

func (m *MemStore) Copy(_ context.Context, src, dst string, o blob.CopyOptions) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	if m.FailCopy != nil {
		if err := m.FailCopy(src, dst); err != nil {
			return err
		}
	}
	s, ok := m.objs[src]
	if !ok {
		return blob.ErrNotFound
	}
	info := s.info
	info.Key = dst
	if o.Replace {
		info.ContentType, info.Metadata = o.ContentType, o.Metadata
	}
	m.tag++
	info.ETag = "e" + strconv.Itoa(m.tag)
	m.objs[dst] = object{data: s.data, info: info}
	return nil
}

func (m *MemStore) keys(prefix string) []string {
	m.mu.Lock()
	defer m.mu.Unlock()
	var ks []string
	for k := range m.objs {
		if strings.HasPrefix(k, prefix) {
			ks = append(ks, k)
		}
	}
	sort.Strings(ks)
	return ks
}

func (m *MemStore) List(_ context.Context, prefix string) iter.Seq2[blob.Info, error] {
	return func(yield func(blob.Info, error) bool) {
		for _, k := range m.keys(prefix) {
			m.mu.Lock()
			info := m.objs[k].info
			m.mu.Unlock()
			if !yield(info, nil) {
				return
			}
		}
	}
}

func (m *MemStore) ListDir(_ context.Context, prefix string) ([]blob.Info, []string, error) {
	var objs []blob.Info
	var folders []string
	seen := map[string]bool{}
	for _, k := range m.keys(prefix) {
		rest := k[len(prefix):]
		if i := strings.Index(rest, "/"); i >= 0 {
			f := prefix + rest[:i+1]
			if !seen[f] {
				seen[f] = true
				folders = append(folders, f)
			}
			continue
		}
		m.mu.Lock()
		objs = append(objs, m.objs[k].info)
		m.mu.Unlock()
	}
	return objs, folders, nil
}

func (m *MemStore) PresignGet(_ context.Context, key string, ttl time.Duration) (blob.Presigned, error) {
	return blob.Presigned{URL: "https://s3.test/" + key, TTL: ttl}, nil
}

func (m *MemStore) PresignPut(_ context.Context, key string, o blob.PutOptions, ttl time.Duration) (blob.Presigned, error) {
	return blob.Presigned{URL: "https://s3.test/" + key + "?put", TTL: ttl, Headers: map[string]string{"Content-Type": o.ContentType}}, nil
}

// Has reports whether key holds an object.
func (m *MemStore) Has(key string) bool {
	m.mu.Lock()
	defer m.mu.Unlock()
	_, ok := m.objs[key]
	return ok
}
