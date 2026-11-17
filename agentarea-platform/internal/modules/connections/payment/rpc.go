package payment

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"math/big"
	"net/http"
	"strings"
	"time"
)

const rpcTimeout = 30 * time.Second

// rpcCall is pympp's _rpc_call: a JSON-RPC 2.0 POST through p.RPC.
func (p Protocols) rpcCall(ctx context.Context, url, method string, params []any) (json.RawMessage, error) {
	if p.RPC == nil {
		return nil, errors.New("payment protocols have no RPC transport")
	}
	body, err := json.Marshal(map[string]any{"jsonrpc": "2.0", "method": method, "params": params, "id": 1})
	if err != nil {
		return nil, err
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, url, bytes.NewReader(body))
	if err != nil {
		return nil, fmt.Errorf("%s: %w", method, err)
	}
	req.Header.Set("Content-Type", "application/json")
	client := &http.Client{Transport: p.RPC, Timeout: rpcTimeout}
	resp, err := client.Do(req)
	if err != nil {
		return nil, fmt.Errorf("%s: %w", method, err)
	}
	defer func() { _ = resp.Body.Close() }()
	raw, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, fmt.Errorf("%s: %w", method, err)
	}
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return nil, fmt.Errorf("%s: RPC answered %d", method, resp.StatusCode)
	}
	var out map[string]json.RawMessage
	if err := json.Unmarshal(raw, &out); err != nil {
		return nil, fmt.Errorf("%s: RPC answer is not a JSON object: %w", method, err)
	}
	if rpcErr, ok := out["error"]; ok {
		return nil, fmt.Errorf("%s: RPC error: %s", method, rpcErr)
	}
	result, ok := out["result"]
	if !ok {
		return nil, fmt.Errorf("%s: RPC answer has no result", method)
	}
	return result, nil
}

// rpcQuantity is int(result, 16) of a hex string result.
func (p Protocols) rpcQuantity(ctx context.Context, url, method string, params []any) (*big.Int, error) {
	raw, err := p.rpcCall(ctx, url, method, params)
	if err != nil {
		return nil, err
	}
	var text string
	if err := json.Unmarshal(raw, &text); err != nil {
		return nil, fmt.Errorf("%s: result %s is not a hex string", method, raw)
	}
	n, ok := pyHexInt(text)
	if !ok {
		return nil, fmt.Errorf("%s: result %q is not a hex number", method, text)
	}
	return n, nil
}

// pyHexInt is Python's int(s, 16): optional sign and 0x prefix, single
// underscores between digits, surrounding whitespace.
func pyHexInt(s string) (*big.Int, bool) {
	s = strings.TrimSpace(s)
	neg := false
	if s != "" && (s[0] == '+' || s[0] == '-') {
		neg, s = s[0] == '-', s[1:]
	}
	if len(s) >= 2 && s[0] == '0' && (s[1] == 'x' || s[1] == 'X') {
		s = strings.TrimPrefix(s[2:], "_")
	}
	if s == "" || s[0] == '_' || s[len(s)-1] == '_' || strings.Contains(s, "__") ||
		strings.Trim(s, "0123456789abcdefABCDEF_") != "" {
		return nil, false
	}
	n, ok := new(big.Int).SetString(strings.ReplaceAll(s, "_", ""), 16)
	if !ok {
		return nil, false
	}
	if neg {
		n.Neg(n)
	}
	return n, true
}
