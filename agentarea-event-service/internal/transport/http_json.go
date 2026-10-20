package transport

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"

	"github.com/agentarea/event-service/internal/template"
)

// HTTPJSONTransport calls a JSON API and takes the list at the entry's items
// path. The cursor template reads the last item.
type HTTPJSONTransport struct {
	caller *Caller
}

// Fetch sends the poll request and returns its items in the order sent.
func (t *HTTPJSONTransport) Fetch(ctx context.Context, f Fetch) (Result, error) {
	if f.Poll.Request == nil {
		return Result{}, fmt.Errorf("http_json poll has no request")
	}
	data, err := t.caller.Call(ctx, *f.Poll.Request, f.Values)
	if err != nil {
		return Result{}, err
	}
	return ReadItems(data, f.Poll.Items, f.Poll.Cursor)
}

// ReadItems takes the list at itemsPath ("" for a top-level list) and renders
// the cursor against its last item. Numbers stay exact (json.Number), so an
// id past 2^53 survives as it was sent.
func ReadItems(data []byte, itemsPath, cursorTemplate string) (Result, error) {
	decoder := json.NewDecoder(bytes.NewReader(data))
	decoder.UseNumber()
	var doc any
	if err := decoder.Decode(&doc); err != nil {
		return Result{}, fmt.Errorf("answer is not JSON: %w", err)
	}
	listed := doc
	if itemsPath != "" {
		var ok bool
		if listed, ok = template.Lookup(doc, itemsPath); !ok {
			return Result{}, fmt.Errorf("answer has no %q", itemsPath)
		}
	}
	items, ok := listed.([]any)
	if !ok {
		return Result{}, fmt.Errorf("%q in the answer is not a list", itemsPath)
	}
	if len(items) == 0 {
		return Result{}, nil
	}
	result := Result{Items: items}
	if cursorTemplate != "" {
		cursor, err := template.RenderCursor(cursorTemplate, items[len(items)-1])
		if err != nil {
			return Result{}, fmt.Errorf("cursor: %w", err)
		}
		result.Cursor = cursor
	}
	return result, nil
}
