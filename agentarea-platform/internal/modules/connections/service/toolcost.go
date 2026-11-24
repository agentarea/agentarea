package service

import (
	"context"
	"errors"
	"fmt"

	"github.com/google/uuid"

	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/db"
	"github.com/agentarea/agentarea/agentarea-platform/internal/kernel/scope"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections/domain"
	"github.com/agentarea/agentarea/agentarea-platform/internal/modules/connections/openapispec"
	runsapi "github.com/agentarea/agentarea/agentarea-platform/internal/modules/runs/api"
)

const (
	metaPayers    = "agentarea:payers"
	openAPIPayers = "x-agentarea-payers"
)

var _ runsapi.ToolCosts = (*Service)(nil)

func costError(err error) error {
	var inv *domain.Invalid
	if errors.As(err, &inv) {
		return &runsapi.CostDeclarationError{Msg: inv.Msg}
	}
	var spec *openapispec.Error
	if errors.As(err, &spec) {
		return &runsapi.CostDeclarationError{Msg: spec.Msg}
	}
	return err
}

// ToolCost is mcp_tool_connection and openapi_tool_connection read when the call is made.
func (s *Service) ToolCost(ctx context.Context, ws scope.Workspace, b runsapi.ToolBinding) (*runsapi.ToolCost, error) {
	switch {
	case b.Source == "mcp" && b.MCP != nil:
		return s.mcpToolCost(ctx, ws, b.MCP.InstanceID, b.MCP.RawName)
	case b.Source == "openapi" && b.OpenAPI != nil:
		return s.openAPIToolCost(ctx, ws, b.OpenAPI.ConnectionID, b.OpenAPI.OperationID)
	}
	return nil, nil
}

func (s *Service) mcpToolCost(ctx context.Context, ws scope.Workspace, instanceID, tool string) (*runsapi.ToolCost, error) {
	id, err := uuid.Parse(instanceID)
	if err != nil {
		return nil, nil
	}
	var inst domain.Instance
	var found bool
	if err := s.readWS(ctx, ws, func(sess db.Session) error {
		inst, found, err = s.d.Instances.Get(ctx, sess, id)
		return err
	}); err != nil || !found {
		return nil, err
	}
	if s.d.Specs == nil {
		return nil, &domain.Unavailable{Msg: "MCP server specs are not available"}
	}
	spec, found, err := s.d.Specs.CatalogJSONSpec(ctx, ws, inst.ServerSpecID)
	if err != nil {
		return nil, err
	}
	if !found {
		spec = nil
	}
	declaration, err := mcpDeclarationOf(spec, tool)
	if err != nil {
		return nil, costError(err)
	}
	connector := manualConnector(inst.ID)
	var payers any
	if spec != nil {
		if name, _ := spec["name"].(string); name != "" {
			connector = name
		}
		metadata, _ := spec["metadata"].(map[string]any)
		payers = metadata[metaPayers]
	}
	return toolCost(connector, inst.PlatformManaged(), payers, declaration, inst.Cost, spec != nil)
}

func (s *Service) openAPIToolCost(ctx context.Context, ws scope.Workspace, connectionID, operation string) (*runsapi.ToolCost, error) {
	id, err := uuid.Parse(connectionID)
	if err != nil {
		return nil, nil
	}
	var conn domain.Connection
	var found bool
	if err := s.readWS(ctx, ws, func(sess db.Session) error {
		conn, found, err = s.d.OpenAPIWrites.Full(ctx, sess, id)
		return err
	}); err != nil || !found {
		return nil, err
	}
	catalog, err := s.openAPICatalogSpec(ctx, ws, conn)
	if err != nil {
		return nil, err
	}
	spec := catalog
	if spec == nil && conn.SpecContent != nil {
		spec = conn.SpecContent
	}
	var declaration map[string]any
	var payers any
	if doc, ok := spec.(map[string]any); ok {
		payers = doc[openAPIPayers]
		configured := map[string]bool{}
		for _, p := range conn.CustomQuery {
			configured[p.Name] = true
		}
		ops, err := openapispec.ParseOperations(doc, configured)
		if err != nil {
			return nil, costError(invalid(err))
		}
		for _, op := range ops {
			if op.Name == operation {
				if declaration, err = declarationObject(op.Cost); err != nil {
					return nil, err
				}
				break
			}
		}
	}
	connector, err := s.openAPIConnector(ctx, ws, conn)
	if err != nil {
		return nil, err
	}
	return toolCost(connector, conn.PlatformManaged(), payers, declaration, conn.Cost, catalog != nil)
}

// openAPIConnector is catalog_connector: the catalog id of the item the connection was made
// from, else the manual connector.
func (s *Service) openAPIConnector(ctx context.Context, ws scope.Workspace, conn domain.Connection) (string, error) {
	if conn.RegistryItemID == nil || s.d.CatalogItems == nil {
		return manualConnector(conn.ID), nil
	}
	id, err := uuid.Parse(*conn.RegistryItemID)
	if err != nil {
		return manualConnector(conn.ID), nil
	}
	item, err := s.d.CatalogItems.CatalogAPIItem(ctx, ws, id)
	var nf *domain.NotFound
	var inv *domain.Invalid
	if errors.As(err, &nf) || errors.As(err, &inv) {
		return manualConnector(conn.ID), nil
	}
	if err != nil {
		return "", err
	}
	if item.ExternalID == "" {
		return manualConnector(conn.ID), nil
	}
	return item.ExternalID, nil
}

func manualConnector(id string) string { return "connection:" + id }

// toolCost is tool_connection: a platform-managed connection runs on the platform's key, any
// other on the workspace's; the connector must allow that payer. A member's own cost wins on a
// connection the workspace pays for; only a catalog entry may declare a settled cost.
func toolCost(connector string, platformManaged bool, payers any, declaration, override map[string]any, fromCatalog bool) (*runsapi.ToolCost, error) {
	payer := "workspace"
	if platformManaged {
		payer = "platform"
	}
	if err := openapispec.CheckPayers(payers); err != nil {
		return nil, &runsapi.CostDeclarationError{Msg: err.Error()}
	}
	if !allowsPayer(payers, payer) {
		return nil, &runsapi.CostDeclarationError{Msg: fmt.Sprintf("%s does not allow calls paid by the %s", connector, payer)}
	}
	cost := &runsapi.ToolCost{Payer: payer, Connector: connector}
	if override == nil {
		source, err := openapispec.CostSource(nilIfEmpty(declaration))
		if err != nil {
			return nil, &runsapi.CostDeclarationError{Msg: err.Error()}
		}
		if source == "settled" && !fromCatalog {
			return nil, &runsapi.CostDeclarationError{Msg: "only a catalog entry may declare a settled cost: its URL receives the connection's credential"}
		}
		cost.Declaration = declaration
		if declaration == nil {
			cost.Declaration = map[string]any{"source": "unknown"}
		}
		return cost, nil
	}
	if platformManaged {
		return nil, &runsapi.CostDeclarationError{Msg: "the cost of a connection the platform pays for is not set on it"}
	}
	if err := openapispec.CheckConnectionCost(override); err != nil {
		return nil, &runsapi.CostDeclarationError{Msg: err.Error()}
	}
	cost.Declaration = override
	return cost, nil
}

func allowsPayer(payers any, payer string) bool {
	if payers == nil {
		return payer == "workspace"
	}
	list, _ := payers.([]any)
	for _, v := range list {
		if v == payer {
			return true
		}
	}
	return false
}

func nilIfEmpty(m map[string]any) any {
	if m == nil {
		return nil
	}
	return m
}
