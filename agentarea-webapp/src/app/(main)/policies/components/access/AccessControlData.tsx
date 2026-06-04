import { getRebacGraph, listRebacTuples, listSkillCollections } from "@/lib/api";
import type {
  RebacGraph,
  RebacTuplesResponse,
  SkillCollection,
} from "@/types/rebac";
import AccessControlExplorer from "./AccessControlExplorer";

const EMPTY_GRAPH: RebacGraph = {
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
  let graph: RebacGraph = EMPTY_GRAPH;
  let tuples: RebacTuplesResponse = { tuples: [], count: 0 };
  let collections: SkillCollection[] = [];

  try {
    const [graphRes, tuplesRes, collectionsRes] = await Promise.all([
      getRebacGraph(),
      listRebacTuples(),
      listSkillCollections(),
    ]);

    if (graphRes.error) {
      console.error("Failed to fetch ReBAC graph:", graphRes.error);
    } else if (graphRes.data) {
      graph = graphRes.data as RebacGraph;
    }

    if (tuplesRes.error) {
      console.error("Failed to fetch ReBAC tuples:", tuplesRes.error);
    } else if (tuplesRes.data) {
      tuples = tuplesRes.data as RebacTuplesResponse;
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
      tuples={tuples}
      collections={collections}
    />
  );
}
