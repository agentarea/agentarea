"use server";

import type {
  RelationshipWriteRequest,
  ResolveRequest,
  ResolveResponse,
} from "@/api/client/types.gen";
import {
  zCreateRelationshipV1AccessControlRelationshipsPostBody,
  zResolveAccessV1AccessControlResolvePostBody,
  zResolveAccessV1AccessControlResolvePostResponse,
} from "@/api/client/zod.gen";
import {
  createAccessControlRelationship,
  resolveAccessControl,
} from "@/lib/api";

function errorMessage(error: unknown, fallback: string): string {
  if (!error) return fallback;
  if (typeof error === "string") return error;
  if (error instanceof Error) return error.message;
  if (typeof error === "object" && "detail" in error) {
    const detail = (error as { detail?: unknown }).detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
      return detail.map((item) => String(item)).join(", ");
    }
  }
  return fallback;
}

export async function resolveAccessAction(
  input: ResolveRequest
): Promise<ResolveResponse> {
  const body = zResolveAccessV1AccessControlResolvePostBody.parse(input);
  const { data, error } = await resolveAccessControl(body);

  if (error || !data) {
    throw new Error(errorMessage(error, "Failed to resolve access"));
  }

  return zResolveAccessV1AccessControlResolvePostResponse.parse(data);
}

export async function createAccessRelationshipAction(
  input: RelationshipWriteRequest
): Promise<void> {
  const body = zCreateRelationshipV1AccessControlRelationshipsPostBody.parse(input);
  const { error } = await createAccessControlRelationship(body);

  if (error) {
    throw new Error(errorMessage(error, "Relationship rule failed"));
  }
}

