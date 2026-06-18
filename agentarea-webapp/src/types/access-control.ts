// Access-control explorer types.
// These mirror the backend contract for the /v1/access-control/* endpoints.

export type AccessControlNodeKind = "agent" | "collection" | "mcp";

export type AccessControlRelation =
  | "user"
  | "editor"
  | "owner"
  | "connect"
  | "member";

export type AccessControlSubjectKind = "agent" | "user" | "workspace";

export interface AccessControlNode {
  id: string;
  kind: AccessControlNodeKind;
  name: string;
  subtitle: string;
  color: string;
  count: number | null;
}

export interface AccessControlEdge {
  from: string;
  to: string;
  relation: AccessControlRelation;
}

export interface AccessControlStats {
  governed_skill_count: number;
  rule_count: number;
  direct_exception_count: number;
}

export interface AccessControlGraph {
  enabled: boolean;
  nodes: AccessControlNode[];
  edges: AccessControlEdge[];
  stats: AccessControlStats;
}

export interface AccessControlRelationship {
  namespace: string;
  object: string;
  object_name: string;
  relation: string;
  subject: string;
  subject_kind: AccessControlSubjectKind;
  subject_name: string;
  fanout: number | null;
  direct: boolean;
}

export interface AccessControlRelationshipsResponse {
  relationships: AccessControlRelationship[];
  count: number;
}

export interface AccessControlResolveHop {
  id: string;
  name: string;
  kind: string;
  color: string;
}

export interface AccessControlResolvePath {
  relation: string;
  hops: AccessControlResolveHop[];
  rels: string[];
}

export interface AccessControlResolveRequest {
  subject_id: string;
  resource_kind: "skill" | "collection" | "mcp" | "agent";
  resource_id: string;
}

export interface AccessControlResolveResponse {
  allowed: boolean;
  effective_relation: string | null;
  verb: string;
  paths: AccessControlResolvePath[];
}

export interface AccessControlRelationshipWriteRequest {
  namespace: string;
  object: string;
  relation: string;
  subject_id?: string;
  subject_set?: string;
}

export interface SkillCollection {
  id: string;
  name: string;
  description: string;
  skill_count: number;
}
