package operator

import "github.com/google/uuid"

// The namespaces every declared id derives from (handler.py). A platform model instance id is
// what agents store and billing's rate cards name, so a re-created row must come back under it;
// a workspace resource derives from the resource itself so a reconcile lands on the rows it wrote.
// Frozen: changing either, or a name format below, orphans every row the operator has written.
const (
	platformNamespace  = "8f3d4b2a-6c1e-5a7f-9d0b-2e4a6c8f1d3b"
	workspaceNamespace = "3c9e2f71-4b8a-5d06-a1e7-9f2c6b0d4e85"
)

func platformID(name string) uuid.UUID {
	return uuid.NewSHA1(uuid.MustParse(platformNamespace), []byte(name))
}

func workspaceScopedID(name string) uuid.UUID {
	return uuid.NewSHA1(uuid.MustParse(workspaceNamespace), []byte(name))
}

func PlatformConfigID(providerKey string) uuid.UUID {
	return platformID(("provider_config:" + providerKey))
}

func PlatformInstanceID(providerKey, modelName string) uuid.UUID {
	return platformID(("model_instance:" + providerKey + ":" + modelName))
}

func PlatformMCPServerID(name string) uuid.UUID {
	return platformID(("mcp_server:" + name))
}

func PlatformMCPInstanceID(name string) uuid.UUID {
	return platformID(("mcp_instance:" + name))
}

func PlatformOpenAPIConnectionID(name string) uuid.UUID {
	return platformID(("openapi_connection:" + name))
}

func PlatformEgressExitID(name string) uuid.UUID {
	return platformID(("egress_exit:" + name))
}

func WorkspaceConfigID(workspaceID, namespace, resource, providerKey string) uuid.UUID {
	return workspaceScopedID(("provider_config:" + workspaceID + ":" + namespace + "/" + resource + ":" + providerKey))
}

func WorkspaceInstanceID(configID uuid.UUID, modelName string) uuid.UUID {
	return workspaceScopedID(("model_instance:" + configID.String() + ":" + modelName))
}
