// Package authz implements the kernel authz port over OpenFGA's HTTP API,
// sending the requests rebac/openfga_client.py sends: no retries, no
// consistency preference (the server default), the pinned model id on checks
// and list-objects but not on reads and writes, an optional bearer token.
package authz

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strconv"
	"strings"
	"time"

	"go.opentelemetry.io/otel/attribute"
	"go.opentelemetry.io/otel/metric"

	kauthz "github.com/agentarea/agentarea/agentarea-platform/internal/kernel/authz"
)

const (
	readPageSize = 100
	// batchCheckSize is the server's default OPENFGA_MAX_CHECKS_PER_BATCH_CHECK.
	batchCheckSize = 50
	maxBody        = 16 << 20
	maxErrorBody   = 64 << 10
)

// api is the HTTP surface the client and the bootstrap share.
type api struct {
	base  string
	token string
	hc    *http.Client
}

func newAPI(baseURL, token string, timeout time.Duration, rt http.RoundTripper) api {
	return api{
		base:  strings.TrimRight(baseURL, "/"),
		token: token,
		hc: &http.Client{
			Timeout:   timeout,
			Transport: rt,
			// A redirect is an answer, as in httpx: the token never follows one.
			CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse },
		},
	}
}

// call sends one request and returns the status and body; err is a transport
// failure only.
func (a api) call(ctx context.Context, method, path string, query url.Values, body any) (int, []byte, error) {
	var payload io.Reader
	if body != nil {
		raw, err := json.Marshal(body)
		if err != nil {
			return 0, nil, err
		}
		payload = bytes.NewReader(raw)
	}
	target := a.base + path
	if len(query) > 0 {
		target += "?" + query.Encode()
	}
	req, err := http.NewRequestWithContext(ctx, method, target, payload)
	if err != nil {
		return 0, nil, err
	}
	if body != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	if a.token != "" {
		req.Header.Set("Authorization", "Bearer "+a.token)
	}
	resp, err := a.hc.Do(req)
	if err != nil {
		return 0, nil, err
	}
	defer func() { _ = resp.Body.Close() }()
	limit := int64(maxBody)
	if resp.StatusCode >= 300 {
		limit = maxErrorBody
	}
	raw, err := io.ReadAll(io.LimitReader(resp.Body, limit))
	if err != nil {
		return 0, nil, err
	}
	return resp.StatusCode, raw, nil
}

// Client is the kernel authz.Graph over one OpenFGA store.
type Client struct {
	api      api
	storeID  string
	modelID  string
	duration metric.Float64Histogram
}

var _ kauthz.Graph = (*Client)(nil)

// NewClient builds a Client for storeID; modelID may be empty (the store's
// latest model answers). rt nil is http.DefaultTransport; meter is required.
func NewClient(baseURL, storeID, modelID, token string, timeout time.Duration, rt http.RoundTripper, meter metric.Meter) (*Client, error) {
	if strings.TrimSpace(storeID) == "" {
		return nil, errors.New("OpenFGA store_id is required when OpenFGA is enabled")
	}
	if timeout <= 0 {
		return nil, errors.New("OpenFGA timeout must be positive")
	}
	if meter == nil {
		return nil, errors.New("OpenFGA client needs a meter")
	}
	hist, err := meter.Float64Histogram(
		"agentarea.authz.duration",
		metric.WithUnit("s"),
		metric.WithDescription("Time spent answering authorization questions, by operation."),
	)
	if err != nil {
		return nil, err
	}
	return &Client{api: newAPI(baseURL, token, timeout, rt), storeID: storeID, modelID: modelID, duration: hist}, nil
}

// StoreID is the store every call addresses.
func (c *Client) StoreID() string { return c.storeID }

// ModelID is the pinned model id, empty when none is pinned.
func (c *Client) ModelID() string { return c.modelID }

// post sends body to /stores/<id>/<endpoint>, timed as operation.
func (c *Client) post(ctx context.Context, operation, endpoint string, body any) (int, []byte, error) {
	started := time.Now()
	defer func() {
		c.duration.Record(ctx, time.Since(started).Seconds(), metric.WithAttributes(attribute.String("operation", operation)))
	}()
	return c.api.call(ctx, http.MethodPost, "/stores/"+url.PathEscape(c.storeID)+"/"+endpoint, nil, body)
}

type tupleKey struct {
	User     string `json:"user"`
	Relation string `json:"relation"`
	Object   string `json:"object"`
}

func keyOf(t kauthz.Tuple) tupleKey {
	return tupleKey{User: t.User, Relation: t.Relation, Object: t.Object}
}

type checkRequest struct {
	TupleKey             tupleKey `json:"tuple_key"`
	AuthorizationModelID string   `json:"authorization_model_id,omitempty"`
}

// Check asks whether subject has relation on objectType:objectID.
func (c *Client) Check(ctx context.Context, subject, relation, objectType, objectID string) (bool, error) {
	body := checkRequest{
		TupleKey:             tupleKey{User: subject, Relation: relation, Object: kauthz.ObjectRef(objectType, objectID)},
		AuthorizationModelID: c.modelID,
	}
	status, raw, err := c.post(ctx, "openfga_check", "check", body)
	if err != nil {
		return false, &kauthz.UnavailableError{Op: "check", Err: err}
	}
	if status != http.StatusOK {
		return false, &kauthz.ResponseError{Op: "check", Status: status, Body: string(raw)}
	}
	var out struct {
		Allowed bool `json:"allowed"`
	}
	if err := json.Unmarshal(raw, &out); err != nil {
		return false, &kauthz.ResponseError{Op: "check", Status: status, Body: "undecodable response: " + err.Error()}
	}
	return out.Allowed, nil
}

type batchItem struct {
	TupleKey      tupleKey `json:"tuple_key"`
	CorrelationID string   `json:"correlation_id"`
}

type batchRequest struct {
	Checks               []batchItem `json:"checks"`
	AuthorizationModelID string      `json:"authorization_model_id,omitempty"`
}

// BatchCheck answers items in order, batchCheckSize per request. An item the
// server could not answer fails the call: no answer is read as a denial.
func (c *Client) BatchCheck(ctx context.Context, items []kauthz.CheckItem) ([]bool, error) {
	out := make([]bool, 0, len(items))
	for start := 0; start < len(items); start += batchCheckSize {
		chunk := items[start:min(start+batchCheckSize, len(items))]
		answers, err := c.batch(ctx, chunk)
		if err != nil {
			return nil, err
		}
		out = append(out, answers...)
	}
	return out, nil
}

func (c *Client) batch(ctx context.Context, items []kauthz.CheckItem) ([]bool, error) {
	body := batchRequest{Checks: make([]batchItem, len(items)), AuthorizationModelID: c.modelID}
	for i, it := range items {
		body.Checks[i] = batchItem{
			TupleKey:      tupleKey{User: it.Subject, Relation: it.Relation, Object: kauthz.ObjectRef(it.ObjectType, it.ObjectID)},
			CorrelationID: strconv.Itoa(i),
		}
	}
	status, raw, err := c.post(ctx, "openfga_batch_check", "batch-check", body)
	if err != nil {
		return nil, &kauthz.UnavailableError{Op: "batch-check", Err: err}
	}
	if status != http.StatusOK {
		return nil, &kauthz.ResponseError{Op: "batch_check", Status: status, Body: string(raw)}
	}
	var resp struct {
		Result map[string]struct {
			Allowed bool            `json:"allowed"`
			Error   json.RawMessage `json:"error"`
		} `json:"result"`
	}
	if err := json.Unmarshal(raw, &resp); err != nil {
		return nil, &kauthz.ResponseError{Op: "batch_check", Status: status, Body: "undecodable response: " + err.Error()}
	}
	answers := make([]bool, len(items))
	for i := range items {
		r, ok := resp.Result[strconv.Itoa(i)]
		if !ok {
			return nil, &kauthz.ResponseError{Op: "batch_check", Status: status, Body: "no answer for check " + strconv.Itoa(i)}
		}
		if len(r.Error) > 0 && string(r.Error) != "null" {
			return nil, &kauthz.ResponseError{Op: "batch_check", Status: status, Body: string(r.Error)}
		}
		answers[i] = r.Allowed
	}
	return answers, nil
}

type listObjectsRequest struct {
	Type                 string `json:"type"`
	Relation             string `json:"relation"`
	User                 string `json:"user"`
	AuthorizationModelID string `json:"authorization_model_id,omitempty"`
}

// ListObjects returns the bare ids ("type:" stripped) of objectType objects
// subject has relation on.
func (c *Client) ListObjects(ctx context.Context, subject, relation, objectType string) ([]string, error) {
	body := listObjectsRequest{Type: objectType, Relation: relation, User: subject, AuthorizationModelID: c.modelID}
	status, raw, err := c.post(ctx, "openfga_list_objects", "list-objects", body)
	if err != nil {
		return nil, &kauthz.UnavailableError{Op: "list-objects", Err: err}
	}
	if status != http.StatusOK {
		return nil, &kauthz.ResponseError{Op: "list_objects", Status: status, Body: string(raw)}
	}
	var out struct {
		Objects []string `json:"objects"`
	}
	if err := json.Unmarshal(raw, &out); err != nil {
		return nil, &kauthz.ResponseError{Op: "list_objects", Status: status, Body: "undecodable response: " + err.Error()}
	}
	ids := make([]string, len(out.Objects))
	for i, obj := range out.Objects {
		ids[i] = strings.TrimPrefix(obj, objectType+":")
	}
	return ids, nil
}

type readKey struct {
	User     string `json:"user,omitempty"`
	Relation string `json:"relation,omitempty"`
	Object   string `json:"object"`
}

type readRequest struct {
	PageSize          int     `json:"page_size"`
	TupleKey          readKey `json:"tuple_key"`
	ContinuationToken string  `json:"continuation_token,omitempty"`
}

type storedTuple struct {
	Key *tupleKey `json:"key"`
	tupleKey
}

// Read returns every tuple q selects, following continuation tokens.
func (c *Client) Read(ctx context.Context, q kauthz.Query) ([]kauthz.Tuple, error) {
	if err := q.Validate(); err != nil {
		return nil, err
	}
	key := readKey{User: q.User, Relation: q.Relation, Object: q.Type + ":" + q.ID}
	var out []kauthz.Tuple
	token := ""
	for {
		status, raw, err := c.post(ctx, "openfga_read", "read", readRequest{PageSize: readPageSize, TupleKey: key, ContinuationToken: token})
		if err != nil {
			return nil, &kauthz.UnavailableError{Op: "read", Err: err}
		}
		if status != http.StatusOK {
			return nil, &kauthz.ResponseError{Op: "query_tuples", Status: status, Body: string(raw)}
		}
		var page struct {
			Tuples            []storedTuple `json:"tuples"`
			ContinuationToken string        `json:"continuation_token"`
		}
		if err := json.Unmarshal(raw, &page); err != nil {
			return nil, &kauthz.ResponseError{Op: "query_tuples", Status: status, Body: "undecodable response: " + err.Error()}
		}
		for _, st := range page.Tuples {
			k := st.tupleKey
			if st.Key != nil {
				k = *st.Key
			}
			t := kauthz.Tuple{User: k.User, Relation: k.Relation, Object: k.Object}
			if q.Matches(t) {
				out = append(out, t)
			}
		}
		if page.ContinuationToken == "" {
			return out, nil
		}
		if page.ContinuationToken == token {
			return nil, &kauthz.ResponseError{Op: "query_tuples", Status: status, Body: "continuation token did not advance"}
		}
		token = page.ContinuationToken
	}
}

type tupleKeys struct {
	TupleKeys []tupleKey `json:"tuple_keys"`
}

type writeRequest struct {
	Writes  *tupleKeys `json:"writes,omitempty"`
	Deletes *tupleKeys `json:"deletes,omitempty"`
}

func keys(ts []kauthz.Tuple) *tupleKeys {
	if len(ts) == 0 {
		return nil
	}
	k := &tupleKeys{TupleKeys: make([]tupleKey, len(ts))}
	for i, t := range ts {
		k.TupleKeys[i] = keyOf(t)
	}
	return k
}

// Write writes and deletes in one atomic request. A delete-only request
// answered 404 is done, as Python's delete_tuple has it.
func (c *Client) Write(ctx context.Context, writes, deletes []kauthz.Tuple) error {
	if len(writes) == 0 && len(deletes) == 0 {
		return nil
	}
	status, raw, err := c.post(ctx, "openfga_write", "write", writeRequest{Writes: keys(writes), Deletes: keys(deletes)})
	if err != nil {
		return &kauthz.UnavailableError{Op: "write", Err: err}
	}
	switch {
	case status == http.StatusOK || status == http.StatusNoContent:
		return nil
	case status == http.StatusNotFound && len(writes) == 0:
		return nil
	}
	return &kauthz.ResponseError{Op: "write", Status: status, Body: string(raw)}
}

func (c *Client) String() string {
	return fmt.Sprintf("openfga(%s store=%s model=%s)", c.api.base, c.storeID, c.modelID)
}
