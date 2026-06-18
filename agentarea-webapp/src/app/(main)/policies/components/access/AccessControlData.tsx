import {
  getAccessControlGraph,
  listAccessControlRelationships,
  listSkillCollections,
} from "@/lib/api";
import { getAuthContext } from "@/lib/getAuthContext";
import type {
  AccessControlGraph,
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

export default async function AccessControlData() {
  let graph: AccessControlGraph = EMPTY_GRAPH;
  let relationships: AccessControlRelationshipsResponse = { relationships: [], count: 0 };
  let collections: SkillCollection[] = [];
  let currentUserId: string | null = null;

  try {
    const [graphRes, relationshipsRes, collectionsRes, authContext] = await Promise.all([
      getAccessControlGraph(),
      listAccessControlRelationships(),
      listSkillCollections(),
      getAuthContext(),
    ]);
    currentUserId = authContext.userId;

    if (graphRes.error) {
      console.error("Failed to fetch access-control graph:", graphRes.error);
    } else if (graphRes.data) {
      graph = graphRes.data as AccessControlGraph;
    }

    if (relationshipsRes.error) {
      console.error("Failed to fetch access-control relationships:", relationshipsRes.error);
    } else if (relationshipsRes.data) {
      relationships = relationshipsRes.data as AccessControlRelationshipsResponse;
    }

    if (collectionsRes.error) {
      console.error(
        "Failed to fetch skill collections:",
        collectionsRes.error
      );
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
