import { getTranslations } from "next-intl/server";
import RetryEmptyState from "@/components/EmptyState/RetryEmptyState";
import {
  getAccessControlGraph,
  listAccessControlRelationships,
  listSkillCollections,
} from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-errors";
import type {
  AccessControlEdge,
  AccessControlGraph,
  AccessControlRelation,
  AccessControlRelationshipsResponse,
  SkillCollection,
} from "@/types/access-control";
import AccessControlExplorer from "./AccessControlExplorer";

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

function LoadError({
  title,
  description,
}: {
  title: string;
  description: string;
}) {
  return (
    <RetryEmptyState
      title={title}
      description={description}
      iconsType="audit"
    />
  );
}

export default async function AccessControlData() {
  const t = await getTranslations("PoliciesPage.accessControl");
  let results;
  try {
    results = await Promise.all([
      getAccessControlGraph(),
      listAccessControlRelationships(),
      listSkillCollections(),
    ]);
  } catch (error) {
    console.error("Failed to load access control data:", error);
    return (
      <LoadError
        title={t("loadFailedTitle")}
        description={apiErrorMessage({ error }, t("loadFailed"))}
      />
    );
  }
  const [graphRes, relationshipsRes, collectionsRes] = results;

  if (graphRes.error) {
    console.error("Failed to fetch access-control graph:", graphRes.error);
    return (
      <LoadError
        title={t("loadFailedTitle")}
        description={apiErrorMessage(graphRes, t("graphLoadFailed"))}
      />
    );
  }
  if (relationshipsRes.error) {
    console.error(
      "Failed to fetch access-control relationships:",
      relationshipsRes.error
    );
    return (
      <LoadError
        title={t("loadFailedTitle")}
        description={apiErrorMessage(relationshipsRes, t("rulesLoadFailed"))}
      />
    );
  }
  if (collectionsRes.error) {
    console.error("Failed to fetch skill collections:", collectionsRes.error);
    return (
      <LoadError
        title={t("loadFailedTitle")}
        description={apiErrorMessage(
          collectionsRes,
          t("collectionsLoadFailed")
        )}
      />
    );
  }
  if (!graphRes.data || !relationshipsRes.data || !collectionsRes.data) {
    throw new Error(t("noData"));
  }

  return (
    <AccessControlExplorer
      graph={toAccessControlGraph(graphRes.data)}
      relationships={
        relationshipsRes.data as AccessControlRelationshipsResponse
      }
      collections={collectionsRes.data as SkillCollection[]}
    />
  );
}
