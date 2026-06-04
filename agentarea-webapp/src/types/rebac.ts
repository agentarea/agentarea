// ReBAC access explorer types.
// These mirror the backend contract for the /v1/rebac/* endpoints.

export type RebacNodeKind = "agent" | "collection" | "mcp";

export type RebacRelation =
  | "user"
  | "editor"
  | "owner"
  | "connect"
  | "member";

export type RebacSubjectKind = "agent" | "user" | "workspace";

export interface RebacNode {
  id: string;
  kind: RebacNodeKind;
  name: string;
  subtitle: string;
  color: string;
  count: number | null;
}

export interface RebacEdge {
  from: string;
  to: string;
  relation: RebacRelation;
}

export interface RebacStats {
  governed_skill_count: number;
  rule_count: number;
  direct_exception_count: number;
}

export interface RebacGraph {
  enabled: boolean;
  nodes: RebacNode[];
  edges: RebacEdge[];
  stats: RebacStats;
}

export interface RebacTuple {
  namespace: string;
  object: string;
  object_name: string;
  relation: string;
  subject: string;
  subject_kind: RebacSubjectKind;
  subject_name: string;
  fanout: number | null;
  direct: boolean;
}

export interface RebacTuplesResponse {
  tuples: RebacTuple[];
  count: number;
}

export interface RebacResolveHop {
  id: string;
  name: string;
  kind: string;
  color: string;
}

export interface RebacResolvePath {
  relation: string;
  hops: RebacResolveHop[];
  rels: string[];
}

export interface RebacResolveRequest {
  subject_id: string;
  resource_kind: "skill" | "mcp" | "agent";
  resource_id: string;
}

export interface RebacResolveResponse {
  allowed: boolean;
  effective_relation: string | null;
  verb: string;
  paths: RebacResolvePath[];
}

export interface RebacCreateTupleRequest {
  namespace: string;
  object: string;
  relation: string;
  subject_id?: string;
  subject_set?: string;
}

export interface RebacDeleteTupleRequest {
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
