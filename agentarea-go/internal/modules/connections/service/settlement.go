package service

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"time"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/netguard"
	"github.com/agentarea/agentarea/agentarea-go/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/api"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/domain"
	"github.com/agentarea/agentarea/agentarea-go/internal/modules/connections/openapispec"
)

const (
	metaCost          = "agentarea:cost"
	settleTimeout     = 20 * time.Second
	settleBodyMaxSize = 4 << 20
)

var _ api.SettledCosts = (*Service)(nil)

// settleTarget is the connection a line names: an MCP instance or an OpenAPI connection.
type settleTarget struct {
	inst *domain.Instance
	conn *domain.Connection
}

func (s *Service) settleTarget(ctx context.Context, ws scope.Workspace, connectionID string) (settleTarget, error) {
	id, err := uuid.Parse(connectionID)
	if err != nil {
		return settleTarget{}, api.ErrConnectionGone
	}
	sess, release, err := s.d.DB.Read(ctx, ws)
	if err != nil {
		return settleTarget{}, err
	}
	defer release()
	inst, ok, err := s.d.Instances.Get(ctx, sess, id)
	if err != nil {
		return settleTarget{}, err
	}
	if ok {
		if inst.Transport == domain.TransportBundle {
			return settleTarget{}, &domain.Invalid{Msg: fmt.Sprintf("MCP instance %s is a bundle: a call settles on the member that ran it", inst.ID)}
		}
		return settleTarget{inst: &inst}, nil
	}
	conn, ok, err := s.d.OpenAPIWrites.Full(ctx, sess, id)
	if err != nil {
		return settleTarget{}, err
	}
	if !ok {
		return settleTarget{}, api.ErrConnectionGone
	}
	return settleTarget{conn: &conn}, nil
}

// SettledDeclaration is the cost declaration the connection's catalog entry
// makes for tool (mcp_tool_connection, openapi_tool_connection). A member's
// own cost on the connection is never a settled one, so it is not read.
func (s *Service) SettledDeclaration(ctx context.Context, ws scope.Workspace, _, connectionID, tool string) (map[string]any, error) {
	t, err := s.settleTarget(ctx, ws, connectionID)
	if err != nil {
		return nil, err
	}
	if t.inst != nil {
		return s.mcpDeclaration(ctx, ws, *t.inst, tool)
	}
	return s.openAPIDeclaration(ctx, ws, *t.conn, tool)
}

func (s *Service) mcpDeclaration(ctx context.Context, ws scope.Workspace, inst domain.Instance, tool string) (map[string]any, error) {
	if s.d.Specs == nil {
		return nil, &domain.Unavailable{Msg: "MCP server specs are not available"}
	}
	spec, ok, err := s.d.Specs.CatalogJSONSpec(ctx, ws, inst.ServerSpecID)
	if err != nil || !ok {
		return nil, err
	}
	metadata, _ := spec["metadata"].(map[string]any)
	raw, present := metadata[metaCost]
	if !present || raw == nil {
		return nil, nil
	}
	cost, isMap := raw.(map[string]any)
	if !isMap {
		return nil, &domain.Invalid{Msg: metaCost + " must be an object of default and tools"}
	}
	var tools map[string]any
	if domain.Truthy(cost["tools"]) {
		if tools, isMap = cost["tools"].(map[string]any); !isMap {
			return nil, &domain.Invalid{Msg: metaCost + ".tools must map tool names to declarations"}
		}
	}
	declaration := tools[tool]
	if declaration == nil {
		declaration = cost["default"]
	}
	return declarationObject(declaration)
}

func (s *Service) openAPIDeclaration(ctx context.Context, ws scope.Workspace, conn domain.Connection, tool string) (map[string]any, error) {
	spec, err := s.openAPICatalogSpec(ctx, ws, conn)
	if err != nil || spec == nil {
		return nil, err
	}
	configured := map[string]bool{}
	for _, p := range conn.CustomQuery {
		configured[p.Name] = true
	}
	ops, err := openapispec.ParseOperations(spec, configured)
	if err != nil {
		return nil, invalid(err)
	}
	for _, op := range ops {
		if op.Name == tool {
			return declarationObject(op.Cost)
		}
	}
	return nil, nil
}

// openAPICatalogSpec is catalog_spec: the platform's own connection is the
// catalog's; one made from a catalog item reads the item; one made by hand
// has none (nil).
func (s *Service) openAPICatalogSpec(ctx context.Context, ws scope.Workspace, conn domain.Connection) (any, error) {
	if conn.PlatformManaged() {
		return conn.SpecContent, nil
	}
	if conn.RegistryItemID == nil {
		return nil, nil
	}
	if s.d.CatalogItems == nil {
		return nil, &domain.Unavailable{Msg: "Catalog API connections are not available"}
	}
	id, err := uuid.Parse(*conn.RegistryItemID)
	if err != nil {
		return nil, err
	}
	item, err := s.d.CatalogItems.CatalogAPIItem(ctx, ws, id)
	var nf *domain.NotFound
	if errors.As(err, &nf) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	content, _ := item.Spec["spec_content"].(map[string]any)
	if content == nil {
		return nil, nil
	}
	return content, nil
}

// declarationObject is a declaration as a plain JSON object, numbers kept as written.
func declarationObject(v any) (map[string]any, error) {
	if v == nil {
		return nil, nil
	}
	if m, ok := v.(map[string]any); ok {
		return m, nil
	}
	raw, err := json.Marshal(v)
	if err != nil {
		return nil, err
	}
	dec := json.NewDecoder(bytes.NewReader(raw))
	dec.UseNumber()
	var out map[string]any
	if err := dec.Decode(&out); err != nil {
		return nil, &domain.Invalid{Msg: fmt.Sprintf("a cost declaration must be an object, got %s", raw)}
	}
	return out, nil
}

// FetchSettlement GETs url with the connection's credential headers
// (credential_headers, resolve_headers) through netguard as a member
// destination, bounded by 20 seconds.
func (s *Service) FetchSettlement(ctx context.Context, ws scope.Workspace, userID, connectionID, url string) (int, []byte, error) {
	if s.d.Out == nil {
		return 0, nil, &domain.Unavailable{Msg: "outbound HTTP is not configured"}
	}
	t, err := s.settleTarget(ctx, ws, connectionID)
	if err != nil {
		return 0, nil, err
	}
	var headers map[string]string
	if t.inst != nil {
		headers, err = s.instanceCredentialHeaders(ctx, ws, *t.inst)
	} else {
		headers, err = s.connectionHeaders(ctx, ws, userID, *t.conn)
	}
	if err != nil {
		return 0, nil, err
	}
	ctx, cancel := context.WithTimeout(ctx, settleTimeout)
	defer cancel()
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
	if err != nil {
		return 0, nil, err
	}
	for k, v := range headers {
		req.Header.Set(k, v)
	}
	client := &http.Client{Transport: s.d.Out.Transport(netguard.Member), Timeout: settleTimeout}
	resp, err := client.Do(req)
	if err != nil {
		return 0, nil, err
	}
	defer func() { _ = resp.Body.Close() }()
	body, err := io.ReadAll(io.LimitReader(resp.Body, settleBodyMaxSize+1))
	if err != nil {
		return 0, nil, err
	}
	if len(body) > settleBodyMaxSize {
		return 0, nil, fmt.Errorf("settlement answer from %s exceeds %d bytes", req.URL.Host, settleBodyMaxSize)
	}
	return resp.StatusCode, body, nil
}

// instanceCredentialHeaders is credential_headers: the merged spec's plain
// headers, the instance's secret ones, then its auth config's for its endpoint.
func (s *Service) instanceCredentialHeaders(ctx context.Context, ws scope.Workspace, inst domain.Instance) (map[string]string, error) {
	spec, ok, err := s.serverSpec(ctx, ws, inst)
	if err != nil {
		return nil, err
	}
	if !ok {
		return nil, &domain.Invalid{Msg: fmt.Sprintf("MCP server spec %s not found", inst.ServerSpecID)}
	}
	merged := transportSpec(spec, inst)
	headers := plainHeaders(merged)
	own, err := s.secretHeaders(ctx, ws, inst)
	if err != nil {
		return nil, err
	}
	for k, v := range own {
		headers[k] = v
	}
	auth, err := s.authHeaders(ctx, ws, inst, instanceEndpoint(inst, merged), false)
	if err != nil {
		return nil, err
	}
	for k, v := range auth {
		headers[k] = v
	}
	return headers, nil
}

func instanceEndpoint(inst domain.Instance, merged map[string]any) string {
	if domain.IsContainer(inst.Transport) {
		return gatewayURL(inst.ID)
	}
	u, _ := merged["endpoint_url"].(string)
	return u
}
