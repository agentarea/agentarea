package authz

import (
	"cmp"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log/slog"
	"net/http"
	"net/url"
	"slices"
	"strings"

	kauthz "github.com/agentarea/agentarea/agentarea-go/internal/kernel/authz"
)

// Options are the process's choices the environment does not make.
type Options struct {
	// Transport carries the calls; nil is http.DefaultTransport. The graph is
	// an internal destination: no SSRF policy applies.
	Transport http.RoundTripper
	Log       *slog.Logger
}

// Open bootstraps the store and model when configured, then returns the
// client and the configuration with the ids it settled on. With
// AGENTAREA_AUTHZ_FGA_APPLY_MODEL the model id is pinned for the process's
// lifetime (main.py: bootstrap_openfga, then OpenFGAClient).
func Open(ctx context.Context, cfg kauthz.Config, opt Options) (*Client, kauthz.Config, error) {
	log := opt.Log
	if log == nil {
		log = slog.Default()
	}
	if cfg.Backend != "openfga" {
		return nil, cfg, fmt.Errorf("AGENTAREA_AUTHZ_BACKEND=%q selects no graph backend; refusing to start rather than allow every check", cfg.Backend)
	}
	if cfg.APIToken == "" {
		log.WarnContext(ctx, "AGENTAREA_AUTHZ_FGA_API_TOKEN is not set: OpenFGA calls are unauthenticated. "+
			"Set AGENTAREA_AUTHZ_FGA_API_TOKEN and the server's OPENFGA_AUTHN_PRESHARED_KEYS to require a bearer token.")
	}
	settled, err := Bootstrap(ctx, cfg, opt.Transport)
	if err != nil {
		return nil, cfg, err
	}
	c, err := NewClient(settled.URL, settled.StoreID, settled.ModelID, settled.APIToken, settled.Timeout, opt.Transport)
	if err != nil {
		return nil, cfg, err
	}
	return c, settled, nil
}

// Bootstrap fills StoreID and ModelID when AGENTAREA_AUTHZ_FGA_BOOTSTRAP is
// on (rebac/openfga_bootstrap.py): finds or creates the store named
// StoreName, and with ApplyModel finds the packaged model (or ModelPath's,
// which must extend it) in the store or writes it.
func Bootstrap(ctx context.Context, cfg kauthz.Config, rt http.RoundTripper) (kauthz.Config, error) {
	if !cfg.Bootstrap {
		return cfg, nil
	}
	a := newAPI(cfg.URL, cfg.APIToken, cfg.Timeout, rt)
	storeID := strings.TrimSpace(cfg.StoreID)
	if storeID == "" {
		id, err := getOrCreateStore(ctx, a, cfg.StoreName)
		if err != nil {
			return cfg, err
		}
		storeID = id
	}
	cfg.StoreID = storeID
	if !cfg.ApplyModel {
		return cfg, nil
	}
	model, err := PackagedModel()
	if err != nil {
		return cfg, err
	}
	if cfg.ModelPath != "" {
		custom, err := LoadModel(cfg.ModelPath)
		if err != nil {
			return cfg, err
		}
		if err := RequireExtends(custom, model); err != nil {
			return cfg, err
		}
		model = custom
	}
	modelID, err := findModel(ctx, a, storeID, model)
	if err != nil {
		return cfg, err
	}
	if modelID == "" {
		if modelID, err = writeModel(ctx, a, storeID, model); err != nil {
			return cfg, err
		}
	}
	cfg.ModelID = modelID
	return cfg, nil
}

type store struct {
	ID        string `json:"id"`
	Name      string `json:"name"`
	CreatedAt string `json:"created_at"`
}

func getOrCreateStore(ctx context.Context, a api, name string) (string, error) {
	if id, err := findStore(ctx, a, name); err != nil || id != "" {
		return id, err
	}
	status, raw, err := a.call(ctx, http.MethodPost, "/stores", nil, map[string]string{"name": name})
	if err != nil {
		return "", &kauthz.UnavailableError{Op: "store create", Err: err}
	}
	if status != http.StatusOK && status != http.StatusCreated {
		return "", &kauthz.ResponseError{Op: "store create", Status: status, Body: string(raw)}
	}
	// A second process can race the same create: re-list and take the
	// earliest store of this name so every process converges on one id.
	id, err := findStore(ctx, a, name)
	if err != nil || id != "" {
		return id, err
	}
	var created store
	if err := json.Unmarshal(raw, &created); err != nil || created.ID == "" {
		return "", errors.New("OpenFGA store response did not include an id")
	}
	return created.ID, nil
}

// findStore is the earliest store named name (by created_at, then id).
func findStore(ctx context.Context, a api, name string) (string, error) {
	var named []store
	token := ""
	for {
		q := url.Values{"page_size": {"100"}}
		if token != "" {
			q.Set("continuation_token", token)
		}
		status, raw, err := a.call(ctx, http.MethodGet, "/stores", q, nil)
		if err != nil {
			return "", &kauthz.UnavailableError{Op: "store list", Err: err}
		}
		if status != http.StatusOK {
			return "", &kauthz.ResponseError{Op: "store list", Status: status, Body: string(raw)}
		}
		var page struct {
			Stores            []store `json:"stores"`
			ContinuationToken string  `json:"continuation_token"`
		}
		if err := json.Unmarshal(raw, &page); err != nil {
			return "", &kauthz.ResponseError{Op: "store list", Status: status, Body: "undecodable response: " + err.Error()}
		}
		for _, s := range page.Stores {
			if s.Name == name {
				named = append(named, s)
			}
		}
		if page.ContinuationToken == "" || page.ContinuationToken == token {
			break
		}
		token = page.ContinuationToken
	}
	if len(named) == 0 {
		return "", nil
	}
	first := slices.MinFunc(named, func(x, y store) int {
		return cmp.Or(cmp.Compare(x.CreatedAt, y.CreatedAt), cmp.Compare(x.ID, y.ID))
	})
	if first.ID == "" {
		return "", errors.New("OpenFGA store response did not include an id")
	}
	return first.ID, nil
}

func findModel(ctx context.Context, a api, storeID string, model map[string]any) (string, error) {
	path := "/stores/" + url.PathEscape(storeID) + "/authorization-models"
	token := ""
	for {
		q := url.Values{"page_size": {"100"}}
		if token != "" {
			q.Set("continuation_token", token)
		}
		status, raw, err := a.call(ctx, http.MethodGet, path, q, nil)
		if err != nil {
			return "", &kauthz.UnavailableError{Op: "authorization model list", Err: err}
		}
		if status != http.StatusOK {
			return "", &kauthz.ResponseError{Op: "authorization model list", Status: status, Body: string(raw)}
		}
		var page struct {
			Models            []map[string]any `json:"authorization_models"`
			ContinuationToken string           `json:"continuation_token"`
		}
		if err := json.Unmarshal(raw, &page); err != nil {
			return "", &kauthz.ResponseError{Op: "authorization model list", Status: status, Body: "undecodable response: " + err.Error()}
		}
		for _, candidate := range page.Models {
			if sameModel(map[string]any(candidate), model) {
				id, _ := candidate["id"].(string)
				if id == "" {
					id, _ = candidate["authorization_model_id"].(string)
				}
				return id, nil
			}
		}
		if page.ContinuationToken == "" || page.ContinuationToken == token {
			return "", nil
		}
		token = page.ContinuationToken
	}
}

func writeModel(ctx context.Context, a api, storeID string, model map[string]any) (string, error) {
	status, raw, err := a.call(ctx, http.MethodPost, "/stores/"+url.PathEscape(storeID)+"/authorization-models", nil, model)
	if err != nil {
		return "", &kauthz.UnavailableError{Op: "authorization model write", Err: err}
	}
	if status != http.StatusOK && status != http.StatusCreated {
		return "", &kauthz.ResponseError{Op: "authorization model write", Status: status, Body: string(raw)}
	}
	var out struct {
		AuthorizationModelID string `json:"authorization_model_id"`
		ID                   string `json:"id"`
	}
	if err := json.Unmarshal(raw, &out); err != nil {
		return "", &kauthz.ResponseError{Op: "authorization model write", Status: status, Body: "undecodable response: " + err.Error()}
	}
	if id := cmp.Or(out.AuthorizationModelID, out.ID); id != "" {
		return id, nil
	}
	return "", errors.New("authorization model write did not return a model id")
}
