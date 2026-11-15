//go:build suite

package harness

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strings"
	"testing"
	"time"
)

// Client is one caller of the backend under test. Its credential is fixed at
// construction; Anonymous sends none.
type Client struct {
	Name    string
	baseURL string
	http    *http.Client
	bearer  func(testing.TB) string
}

func newClient(name, baseURL string, bearer func(testing.TB) string) *Client {
	return &Client{
		Name:    name,
		baseURL: baseURL,
		// Redirects are part of the behaviour under test (FastAPI's 307 on a
		// missing trailing slash), so they are returned, never followed.
		http: &http.Client{
			Timeout:       30 * time.Second,
			CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse },
		},
		bearer: bearer,
	}
}

// Anonymous is a client with no credential.
func Anonymous(t testing.TB) *Client {
	return newClient("anonymous", Current(t).BaseURL, nil)
}

// Bearer is a client sending a fixed bearer token (an API key, an agent key,
// a hand-made or expired token).
func Bearer(t testing.TB, name, token string) *Client {
	return newClient(name, Current(t).BaseURL, func(testing.TB) string { return token })
}

// Request is one call. Body is marshalled as JSON unless it is a []byte or an
// io.Reader, which are sent as is.
type Request struct {
	Method string
	Path   string
	Body   any
	Header http.Header
}

// Response is a fully read reply.
type Response struct {
	t      testing.TB
	req    string
	Status int
	Header http.Header
	Body   []byte
}

// Do sends r and reads the whole reply. A transport failure fails the test.
func (c *Client) Do(t testing.TB, r Request) *Response {
	t.Helper()
	req := c.newRequest(t, r)
	resp, err := c.http.Do(req)
	if err != nil {
		t.Fatalf("%s %s %s: %v", c.Name, r.Method, r.Path, err)
	}
	defer func() { _ = resp.Body.Close() }()
	body, err := io.ReadAll(resp.Body)
	if err != nil {
		t.Fatalf("%s %s %s: reading body: %v", c.Name, r.Method, r.Path, err)
	}
	return &Response{t: t, req: c.Name + " " + r.Method + " " + r.Path, Status: resp.StatusCode, Header: resp.Header, Body: body}
}

func (c *Client) newRequest(t testing.TB, r Request) *http.Request {
	t.Helper()
	var body io.Reader
	contentType := ""
	switch b := r.Body.(type) {
	case nil:
	case []byte:
		body = bytes.NewReader(b)
	case io.Reader:
		body = b
	default:
		raw, err := json.Marshal(b)
		if err != nil {
			t.Fatalf("marshal body for %s %s: %v", r.Method, r.Path, err)
		}
		body = bytes.NewReader(raw)
		contentType = "application/json"
	}
	req, err := http.NewRequest(r.Method, c.url(r.Path), body)
	if err != nil {
		t.Fatalf("%s %s: %v", r.Method, r.Path, err)
	}
	if contentType != "" {
		req.Header.Set("Content-Type", contentType)
	}
	if c.bearer != nil {
		req.Header.Set("Authorization", "Bearer "+c.bearer(t))
	}
	for k, vs := range r.Header {
		for _, v := range vs {
			req.Header.Add(k, v)
		}
	}
	return req
}

func (c *Client) url(path string) string {
	if strings.HasPrefix(path, "http://") || strings.HasPrefix(path, "https://") {
		return path
	}
	return c.baseURL + path
}

func (c *Client) Get(t testing.TB, path string) *Response {
	t.Helper()
	return c.Do(t, Request{Method: http.MethodGet, Path: path})
}

func (c *Client) Post(t testing.TB, path string, body any) *Response {
	t.Helper()
	return c.Do(t, Request{Method: http.MethodPost, Path: path, Body: body})
}

func (c *Client) Put(t testing.TB, path string, body any) *Response {
	t.Helper()
	return c.Do(t, Request{Method: http.MethodPut, Path: path, Body: body})
}

func (c *Client) Patch(t testing.TB, path string, body any) *Response {
	t.Helper()
	return c.Do(t, Request{Method: http.MethodPatch, Path: path, Body: body})
}

func (c *Client) Delete(t testing.TB, path string) *Response {
	t.Helper()
	return c.Do(t, Request{Method: http.MethodDelete, Path: path})
}

// Expect fails the test unless the status is one of want; the body is in the message.
func (r *Response) Expect(want ...int) *Response {
	r.t.Helper()
	for _, w := range want {
		if r.Status == w {
			return r
		}
	}
	r.t.Fatalf("%s: status %d, want %v; body: %s", r.req, r.Status, want, truncate(r.Body, 2000))
	return r
}

// JSON decodes the body into a generic value (numbers as json.Number).
func (r *Response) JSON() any {
	r.t.Helper()
	var v any
	dec := json.NewDecoder(bytes.NewReader(r.Body))
	dec.UseNumber()
	if err := dec.Decode(&v); err != nil {
		r.t.Fatalf("%s: body is not JSON (%v): %s", r.req, err, truncate(r.Body, 2000))
	}
	return v
}

// Object is JSON() asserted to be an object.
func (r *Response) Object() map[string]any {
	r.t.Helper()
	obj, ok := r.JSON().(map[string]any)
	if !ok {
		r.t.Fatalf("%s: body is not a JSON object: %s", r.req, truncate(r.Body, 2000))
	}
	return obj
}

// Array is JSON() asserted to be an array.
func (r *Response) Array() []any {
	r.t.Helper()
	arr, ok := r.JSON().([]any)
	if !ok {
		r.t.Fatalf("%s: body is not a JSON array: %s", r.req, truncate(r.Body, 2000))
	}
	return arr
}

// Decode unmarshals the body into v.
func (r *Response) Decode(v any) {
	r.t.Helper()
	if err := json.Unmarshal(r.Body, v); err != nil {
		r.t.Fatalf("%s: decode %T: %v; body: %s", r.req, v, err, truncate(r.Body, 2000))
	}
}

// Match compares the JSON body with want (see Match) and fails the test on a difference.
func (r *Response) Match(want any) *Response {
	r.t.Helper()
	if err := Compare(r.JSON(), want); err != nil {
		r.t.Fatalf("%s: body differs: %v\nbody: %s", r.req, err, truncate(r.Body, 4000))
	}
	return r
}

// ContentType is the media type without parameters.
func (r *Response) ContentType() string {
	ct, _, _ := strings.Cut(r.Header.Get("Content-Type"), ";")
	return strings.TrimSpace(ct)
}

func truncate(b []byte, n int) string {
	if len(b) <= n {
		return string(b)
	}
	return fmt.Sprintf("%s... (%d bytes)", b[:n], len(b))
}
