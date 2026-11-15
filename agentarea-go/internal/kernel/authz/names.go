package authz

import "strings"

// Types of the packaged model (rebac/openfga/model.fga).
const (
	TypeUser           = "User"
	TypeAgent          = "Agent"
	TypeWorkspace      = "Workspace"
	TypeRole           = "role"
	TypeRoleAssignment = "role_assignment"
	TypeProject        = "project"
	TypeResource       = "resource"
)

// Relations of the packaged model.
const (
	RelMembers        = "members"
	RelAdmin          = "admin"
	RelWorkspace      = "workspace"
	RelParent         = "parent"
	RelProject        = "project"
	RelRoleAssignment = "role_assignment"
	RelReader         = "reader"
	RelWriter         = "writer"
	RelManager        = "manager"
	// RelInvoker is who may run an agent. Nothing implies it, not managing
	// the agent nor administering its workspace.
	RelInvoker        = "invoker"
	RelSecretUser     = "secret_user"
	RelPersonal       = "personal"
	RelConnectionUser = "connection_user"

	CanRead          = "can_read"
	CanWrite         = "can_write"
	CanManage        = "can_manage"
	CanInvoke        = "can_invoke"
	CanUseSecret     = "can_use_secret"
	CanUseConnection = "can_use_connection"
)

// Wildcard subjects: every user, every agent.
const (
	EveryUser  = "User:*"
	EveryAgent = "Agent:*"
)

// ObjectRef is "type:id".
func ObjectRef(objectType, id string) string { return objectType + ":" + id }

// SplitObject splits "type:id" at the first colon; a reference without one
// is all id.
func SplitObject(ref string) (objectType, id string) {
	typ, id, ok := strings.Cut(ref, ":")
	if !ok {
		return "", ref
	}
	return typ, id
}

// UserSubject is "User:<id>"; an id already in that form is kept
// (workspaces/memberships.py _user_subject).
func UserSubject(userID string) string {
	if strings.HasPrefix(userID, TypeUser+":") {
		return userID
	}
	return ObjectRef(TypeUser, userID)
}

// AgentSubject is "Agent:<id>".
func AgentSubject(agentID string) string { return ObjectRef(TypeAgent, agentID) }

// RootProjectID is the object id of a workspace's root project: every
// workspace-level resource hangs off project:<ws>-root, and a workspace admin
// manages it through "admin from workspace".
func RootProjectID(workspaceID string) string { return workspaceID + "-root" }

// RootProject is "project:<ws>-root".
func RootProject(workspaceID string) string {
	return ObjectRef(TypeProject, RootProjectID(workspaceID))
}

// OwnerRelations are the bits a creator is granted: the model has no roll-up,
// so manager alone confers neither read nor write.
func OwnerRelations() []string { return []string{RelReader, RelWriter, RelManager} }

// AgentOwnerRelations are an agent's creator's bits: the owner's plus invoker
// (agents/domain/models.py __graph_owner_relations__).
func AgentOwnerRelations() []string { return append(OwnerRelations(), RelInvoker) }
