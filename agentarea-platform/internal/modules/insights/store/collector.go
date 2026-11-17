package store

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"time"
)

// collectorTimeout bounds one batch, as the Python client's 5s timeout did.
const collectorTimeout = 5 * time.Second

// Collector posts analytics batches to {URL}/v1/events over the vendor transport.
type Collector struct {
	URL       string
	Transport http.RoundTripper
}

// Post sends batch; anything but a 2xx is an error.
func (c Collector) Post(ctx context.Context, batch []map[string]any) error {
	if c.Transport == nil {
		return errors.New("analytics collector: no outbound transport")
	}
	body, err := json.Marshal(batch)
	if err != nil {
		return err
	}
	ctx, cancel := context.WithTimeout(ctx, collectorTimeout)
	defer cancel()
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, c.URL+"/v1/events", bytes.NewReader(body))
	if err != nil {
		return err
	}
	req.Header.Set("Content-Type", "application/json")
	resp, err := (&http.Client{Transport: c.Transport}).Do(req)
	if err != nil {
		return err
	}
	defer func() { _ = resp.Body.Close() }()
	_, _ = io.Copy(io.Discard, io.LimitReader(resp.Body, 1<<16))
	if resp.StatusCode < 200 || resp.StatusCode > 299 {
		return fmt.Errorf("collector answered %s", resp.Status)
	}
	return nil
}
