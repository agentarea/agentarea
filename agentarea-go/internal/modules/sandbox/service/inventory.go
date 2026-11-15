package service

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"net/url"
	"time"

	"github.com/agentarea/agentarea/agentarea-go/internal/modules/sandbox/api"
)

const inventoryInvalid = "Sandbox inventory response is invalid"

// Sandboxes is list_sandboxes: the manager's live inventory, filtered to the
// caller's workspace and rejected whole if anything else slips in.
func (s *Service) Sandboxes(ctx context.Context, workspaceID string) (api.SandboxList, error) {
	secret := s.d.Manager.InspectSecret
	if secret == "" {
		return api.SandboxList{}, httpErr(http.StatusServiceUnavailable, "Sandbox inventory is not configured")
	}
	unavailable := httpErr(http.StatusServiceUnavailable, "Sandbox inventory is temporarily unavailable")
	resp, err := s.call(ctx, http.MethodGet, s.managerURL("/sandbox/sessions", url.Values{"workspace_id": {workspaceID}}), bearer(secret), nil, 10*time.Second)
	if err != nil {
		if ctx.Err() != nil {
			return api.SandboxList{}, ctx.Err()
		}
		s.d.Log.WarnContext(ctx, "sandbox inventory manager request failed", "error", err)
		return api.SandboxList{}, unavailable
	}
	if resp.Status >= 400 {
		text := resp.text()
		if r := []rune(text); len(r) > 300 {
			text = string(r[:300])
		}
		s.d.Log.WarnContext(ctx, fmt.Sprintf("Sandbox inventory manager returned %d: %s", resp.Status, text))
		return api.SandboxList{}, unavailable
	}
	list, err := parseInventory(resp.Body)
	if err != nil {
		s.d.Log.ErrorContext(ctx, "sandbox inventory manager returned an invalid response", "error", err)
		return api.SandboxList{}, httpErr(http.StatusBadGateway, inventoryInvalid)
	}
	for _, it := range list.Items {
		if it.WorkspaceID != workspaceID {
			s.d.Log.ErrorContext(ctx, "sandbox inventory contained an item from another workspace")
			return api.SandboxList{}, httpErr(http.StatusBadGateway, inventoryInvalid)
		}
	}
	return list, nil
}

// Inventory is api.Inventory.
func (s *Service) Inventory() api.Inventory { return s }

func strictObject(raw json.RawMessage, fields ...string) (map[string]json.RawMessage, error) {
	var m map[string]json.RawMessage
	if err := json.Unmarshal(raw, &m); err != nil || m == nil {
		return nil, errors.New("object expected")
	}
	for k := range m {
		if !containsString(fields, k) {
			return nil, fmt.Errorf("%s: extra inputs are not permitted", k)
		}
	}
	for _, k := range fields {
		if _, ok := m[k]; !ok {
			return nil, fmt.Errorf("%s: field required", k)
		}
	}
	return m, nil
}

func strictString(raw json.RawMessage) (string, error) {
	var v string
	if !bytes.HasPrefix(bytes.TrimSpace(raw), []byte(`"`)) {
		return "", errors.New("input should be a valid string")
	}
	err := json.Unmarshal(raw, &v)
	return v, err
}

// utcDatetime parses a pydantic datetime and renders it as utc_isoformat.
func utcDatetime(raw json.RawMessage) (string, error) {
	str, err := strictString(raw)
	if err != nil {
		return "", err
	}
	for _, layout := range []string{time.RFC3339Nano, "2006-01-02T15:04:05.999999", "2006-01-02 15:04:05.999999Z07:00", "2006-01-02 15:04:05.999999"} {
		if t, err := time.Parse(layout, str); err == nil {
			return pyISO(t, true), nil
		}
	}
	return "", errors.New("input should be a valid datetime")
}

func parseInventory(raw []byte) (api.SandboxList, error) {
	top, err := strictObject(raw, "items", "total")
	if err != nil {
		return api.SandboxList{}, err
	}
	var out api.SandboxList
	var total json.Number
	dec := json.NewDecoder(bytes.NewReader(top["total"]))
	dec.UseNumber()
	if err := dec.Decode(&total); err != nil {
		return api.SandboxList{}, errors.New("total: input should be a valid integer")
	}
	n, isInt := pyInt(total)
	if !isInt {
		return api.SandboxList{}, errors.New("total: input should be a valid integer")
	}
	out.Total = int(n)
	var items []json.RawMessage
	if err := json.Unmarshal(top["items"], &items); err != nil || items == nil {
		return api.SandboxList{}, errors.New("items: input should be a valid list")
	}
	out.Items = make([]api.SandboxSummary, 0, len(items))
	for _, rawItem := range items {
		it, err := strictObject(rawItem, "id", "provider", "workspace_id", "task_id", "state", "created_at", "expires_at", "resources", "isolation")
		if err != nil {
			return api.SandboxList{}, err
		}
		var sum api.SandboxSummary
		for k, dst := range map[string]*string{"id": &sum.ID, "provider": &sum.Provider, "workspace_id": &sum.WorkspaceID, "task_id": &sum.TaskID, "state": &sum.State, "isolation": &sum.Isolation} {
			if *dst, err = strictString(it[k]); err != nil {
				return api.SandboxList{}, fmt.Errorf("%s: %w", k, err)
			}
		}
		if sum.CreatedAt, err = utcDatetime(it["created_at"]); err != nil {
			return api.SandboxList{}, fmt.Errorf("created_at: %w", err)
		}
		if string(bytes.TrimSpace(it["expires_at"])) != "null" {
			exp, err := utcDatetime(it["expires_at"])
			if err != nil {
				return api.SandboxList{}, fmt.Errorf("expires_at: %w", err)
			}
			sum.ExpiresAt = &exp
		}
		res, err := strictObject(it["resources"], "cpu", "memory")
		if err != nil {
			return api.SandboxList{}, fmt.Errorf("resources: %w", err)
		}
		if sum.CPU, err = strictString(res["cpu"]); err != nil {
			return api.SandboxList{}, err
		}
		if sum.Memory, err = strictString(res["memory"]); err != nil {
			return api.SandboxList{}, err
		}
		out.Items = append(out.Items, sum)
	}
	return out, nil
}
