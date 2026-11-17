package blob

import (
	"crypto/md5" //nolint:gosec // S3 ETags are MD5
	"encoding/hex"
	"encoding/xml"
	"io"
	"net/http"
	"net/http/httptest"
	"net/url"
	"sort"
	"strconv"
	"strings"
	"sync"
	"testing"
	"time"
)

type fakeObject struct {
	body        []byte
	contentType string
	meta        map[string]string
	checksum    string
	etag        string
	modified    time.Time
}

// fakeS3 is a path-style S3 over a map, enough for the store: it records the
// last request's headers and refuses what a real store refuses (conditions).
type fakeS3 struct {
	mu       sync.Mutex
	bucket   string
	objects  map[string]*fakeObject
	requests []*http.Request
	pageSize int
	t        *testing.T
}

func newFakeS3(t *testing.T, bucket string) (*fakeS3, *httptest.Server) {
	f := &fakeS3{bucket: bucket, objects: map[string]*fakeObject{}, pageSize: 1000, t: t}
	srv := httptest.NewServer(f)
	t.Cleanup(srv.Close)
	return f, srv
}

func s3Error(w http.ResponseWriter, status int, code string) {
	w.Header().Set("Content-Type", "application/xml")
	w.WriteHeader(status)
	_, _ = w.Write([]byte(`<?xml version="1.0" encoding="UTF-8"?><Error><Code>` + code + `</Code><Message>` + code + `</Message></Error>`))
}

func (f *fakeS3) last() *http.Request {
	f.mu.Lock()
	defer f.mu.Unlock()
	return f.requests[len(f.requests)-1]
}

func (f *fakeS3) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.requests = append(f.requests, r.Clone(r.Context()))
	if !strings.HasPrefix(r.Header.Get("Authorization"), "AWS4-HMAC-SHA256 Credential=AKID/") {
		s3Error(w, http.StatusForbidden, "AccessDenied")
		return
	}
	path, _ := url.PathUnescape(strings.TrimPrefix(r.URL.EscapedPath(), "/"))
	bucket, key, _ := strings.Cut(path, "/")
	if bucket != f.bucket {
		s3Error(w, http.StatusNotFound, "NoSuchBucket")
		return
	}
	switch {
	case r.Method == http.MethodGet && key == "":
		f.list(w, r)
	case r.Method == http.MethodPut && r.Header.Get("x-amz-copy-source") != "":
		src, _ := url.PathUnescape(r.Header.Get("x-amz-copy-source"))
		_, srcKey, _ := strings.Cut(strings.TrimPrefix(src, "/"), "/")
		o, ok := f.objects[srcKey]
		if !ok {
			s3Error(w, http.StatusNotFound, "NoSuchKey")
			return
		}
		c := *o
		if r.Header.Get("x-amz-metadata-directive") == "REPLACE" {
			c.meta = metaOf(r)
			c.contentType = r.Header.Get("Content-Type")
		}
		f.objects[key] = &c
		w.Header().Set("Content-Type", "application/xml")
		_, _ = w.Write([]byte(`<CopyObjectResult><ETag>"` + c.etag + `"</ETag></CopyObjectResult>`))
	case r.Method == http.MethodPut:
		cur, exists := f.objects[key]
		if r.Header.Get("If-None-Match") == "*" && exists {
			s3Error(w, http.StatusPreconditionFailed, "PreconditionFailed")
			return
		}
		if m := r.Header.Get("If-Match"); m != "" && (!exists || cur.etag != strings.Trim(m, `"`)) {
			s3Error(w, http.StatusPreconditionFailed, "PreconditionFailed")
			return
		}
		body, _ := io.ReadAll(r.Body)
		sum := md5.Sum(body) //nolint:gosec
		o := &fakeObject{body: body, contentType: r.Header.Get("Content-Type"), meta: metaOf(r), checksum: r.Header.Get("x-amz-checksum-sha256"), etag: hex.EncodeToString(sum[:]), modified: time.Now()}
		f.objects[key] = o
		w.Header().Set("ETag", `"`+o.etag+`"`)
	case r.Method == http.MethodGet || r.Method == http.MethodHead:
		o, ok := f.objects[key]
		if !ok {
			if r.Method == http.MethodHead {
				w.WriteHeader(http.StatusNotFound)
				return
			}
			s3Error(w, http.StatusNotFound, "NoSuchKey")
			return
		}
		w.Header().Set("Content-Type", o.contentType)
		w.Header().Set("ETag", `"`+o.etag+`"`)
		w.Header().Set("Last-Modified", o.modified.UTC().Format(http.TimeFormat))
		for k, v := range o.meta {
			w.Header().Set("x-amz-meta-"+k, v)
		}
		if o.checksum != "" && r.Header.Get("x-amz-checksum-mode") == "ENABLED" {
			w.Header().Set("x-amz-checksum-sha256", o.checksum)
		}
		w.Header().Set("Content-Length", strconv.Itoa(len(o.body)))
		if r.Method == http.MethodGet {
			_, _ = w.Write(o.body)
		}
	case r.Method == http.MethodDelete:
		delete(f.objects, key)
		w.WriteHeader(http.StatusNoContent)
	default:
		s3Error(w, http.StatusNotImplemented, "NotImplemented")
	}
}

func metaOf(r *http.Request) map[string]string {
	m := map[string]string{}
	for k, v := range r.Header {
		if lk := strings.ToLower(k); strings.HasPrefix(lk, "x-amz-meta-") {
			m[strings.TrimPrefix(lk, "x-amz-meta-")] = v[0]
		}
	}
	return m
}

type listResult struct {
	XMLName               xml.Name       `xml:"ListBucketResult"`
	Name                  string         `xml:"Name"`
	IsTruncated           bool           `xml:"IsTruncated"`
	NextContinuationToken string         `xml:"NextContinuationToken,omitempty"`
	KeyCount              int            `xml:"KeyCount"`
	Contents              []listContents `xml:"Contents"`
	CommonPrefixes        []listPrefix   `xml:"CommonPrefixes"`
}

type listContents struct {
	Key          string `xml:"Key"`
	Size         int    `xml:"Size"`
	ETag         string `xml:"ETag"`
	LastModified string `xml:"LastModified"`
}

type listPrefix struct {
	Prefix string `xml:"Prefix"`
}

func (f *fakeS3) list(w http.ResponseWriter, r *http.Request) {
	q := r.URL.Query()
	prefix, delim, token := q.Get("prefix"), q.Get("delimiter"), q.Get("continuation-token")
	var keys []string
	for k := range f.objects {
		if strings.HasPrefix(k, prefix) {
			keys = append(keys, k)
		}
	}
	sort.Strings(keys)
	res := listResult{Name: f.bucket}
	seen := map[string]bool{}
	var entries []string
	for _, k := range keys {
		if delim != "" {
			if i := strings.Index(k[len(prefix):], delim); i >= 0 {
				p := k[:len(prefix)+i+1]
				if !seen[p] {
					seen[p] = true
					entries = append(entries, "P"+p)
				}
				continue
			}
		}
		entries = append(entries, "K"+k)
	}
	start := 0
	if token != "" {
		start, _ = strconv.Atoi(token)
	}
	end := min(start+f.pageSize, len(entries))
	for _, e := range entries[start:end] {
		if e[0] == 'P' {
			res.CommonPrefixes = append(res.CommonPrefixes, listPrefix{e[1:]})
			continue
		}
		o := f.objects[e[1:]]
		res.Contents = append(res.Contents, listContents{Key: e[1:], Size: len(o.body), ETag: `"` + o.etag + `"`, LastModified: o.modified.UTC().Format(time.RFC3339)})
	}
	if end < len(entries) {
		res.IsTruncated, res.NextContinuationToken = true, strconv.Itoa(end)
	}
	res.KeyCount = end - start
	w.Header().Set("Content-Type", "application/xml")
	_ = xml.NewEncoder(w).Encode(res)
}
