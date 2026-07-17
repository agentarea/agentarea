import {
  getAccessControlGraph,
  listAccessControlRelationships,
  listSkillCollections,
} from "@/lib/api";
import { getAuthContext } from "@/lib/getAuthContext";
import type {
  AccessControlEdge,
  AccessControlGraph,
  AccessControlRelation,
  AccessControlRelationshipsResponse,
  SkillCollection,
} from "@/types/access-control";
import AccessControlExplorer from "./AccessControlExplorer";

const EMPTY_GRAPH: AccessControlGraph = {
  enabled: false,
  nodes: [],
  edges: [],
  stats: {
    governed_skill_count: 0,
    rule_count: 0,
    direct_exception_count: 0,
  },
};

const ACCESS_CONTROL_RELATIONS: ReadonlySet<string> = new Set([
  "user",
  "editor",
  "owner",
  "connect",
  "member",
]);

function toAccessControlEdge(edge: {
  [key: string]: unknown;
}): AccessControlEdge | null {
  if (
    typeof edge.from === "string" &&
    typeof edge.to === "string" &&
    typeof edge.relation === "string" &&
    ACCESS_CONTROL_RELATIONS.has(edge.relation)
  ) {
    return {
      from: edge.from,
      to: edge.to,
      relation: edge.relation as AccessControlRelation,
    };
  }
  return null;
}

function toAccessControlGraph(data: {
  enabled: boolean;
  nodes: Array<
    Omit<AccessControlGraph["nodes"][number], "count"> & {
      count?: number | null;
    }
  >;
  edges: Array<{ [key: string]: unknown }>;
  stats: AccessControlGraph["stats"];
}): AccessControlGraph {
  return {
    ...data,
    nodes: data.nodes.map((node) => ({ ...node, count: node.count ?? null })),
    edges: data.edges
      .map(toAccessControlEdge)
      .filter((edge): edge is AccessControlEdge => Boolean(edge)),
  };
}

export default async function AccessControlData() {
  let graph: AccessControlGraph = EMPTY_GRAPH;
  let relationships: AccessControlRelationshipsResponse = {
    relationships: [],
    count: 0,
  };
  let collections: SkillCollection[] = [];
  let currentUserId: string | null = null;

  try {
    const [graphRes, relationshipsRes, collectionsRes, authContext] =
      await Promise.all([
        getAccessControlGraph(),
        listAccessControlRelationships(),
        listSkillCollections(),
        getAuthContext(),
      ]);
    currentUserId = authContext.userId;

    if (graphRes.error) {
      console.error("Failed to fetch access-control graph:", graphRes.error);
    } else if (graphRes.data) {
      graph = toAccessControlGraph(graphRes.data);
    }

    if (relationshipsRes.error) {
      console.error(
        "Failed to fetch access-control relationships:",
        relationshipsRes.error
      );
    } else if (relationshipsRes.data) {
      relationships =
        relationshipsRes.data as AccessControlRelationshipsResponse;
    }

    if (collectionsRes.error) {
      console.error("Failed to fetch skill collections:", collectionsRes.error);
    } else if (collectionsRes.data) {
      collections = (collectionsRes.data as SkillCollection[]) ?? [];
    }
  } catch (error) {
    console.error("Failed to load access control data:", error);
  }

  return (
    <AccessControlExplorer
      graph={graph}
      relationships={relationships}
      collections={collections}
      currentUserId={currentUserId}
    />
  );
}
