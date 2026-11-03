import "server-only";
import { cache } from "react";
import type { EgressExitResponse } from "@/api/client";
import { listEgressExits } from "./api";
import type { ApiResultLike } from "./api-errors";

/**
 * The workspace's egress exits as the UI knows them. `none`: this deployment
 * has no egress exits (without the enterprise edition every /egress-exits route
 * answers 404), so nothing about them is shown anywhere. `error`: any other
 * failure, which the surface that needs the list reports.
 */
export type EgressExitsState =
  | { status: "none" }
  | { status: "error"; failure: ApiResultLike }
  | { status: "ready"; exits: EgressExitResponse[] };

/** The root layout (settings nav) and the page both ask; one request per render. */
export const getEgressExits = cache(async (): Promise<EgressExitsState> => {
  const result = await listEgressExits();
  if (result.status === 404) return { status: "none" };
  if (result.error || !result.data) {
    console.error("Failed to load egress exits", result.status, result.error);
    return {
      status: "error",
      failure: { error: result.error, status: result.status },
    };
  }
  return { status: "ready", exits: result.data };
});
