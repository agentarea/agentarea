"use server";

import type { RegistryItemResponse } from "@/api/client/types.gen";
import {
  zListRegistriesV1RegistriesGetResponse,
  zListRegistryItemsV1RegistriesRegistryIdItemsGetResponse,
} from "@/api/client/zod.gen";
import { listRegistries, listRegistryItems } from "@/lib/api";
import {
  TYPE_KEYS,
  type CatalogType,
  type RawSpec,
} from "@/app/(main)/bundles/components/catalog-data";

export type CatalogSuggestionItem = Pick<
  RegistryItemResponse,
  "id" | "name" | "spec"
>;

function errorMessage(error: unknown, fallback: string): string {
  if (!error) return fallback;
  if (typeof error === "string") return error;
  if (error instanceof Error) return error.message;
  if (typeof error === "object" && "detail" in error) {
    const detail = (error as { detail?: unknown }).detail;
    if (typeof detail === "string") return detail;
  }
  return fallback;
}

function assertCatalogType(type: CatalogType): CatalogType {
  if (!TYPE_KEYS.includes(type)) {
    throw new Error("Invalid catalog type");
  }
  return type;
}

function isSuggested(spec: RawSpec | undefined): boolean {
  const meta = (spec?.raw_spec as RawSpec | undefined)?.metadata as
    | RawSpec
    | undefined;
  return meta?.["agentarea:suggested"] === true;
}

export async function listCatalogSuggestionsAction(
  type: CatalogType,
  max: number
): Promise<CatalogSuggestionItem[]> {
  const registryType = assertCatalogType(type);
  const { data: registriesData, error: registriesError } = await listRegistries({
    registry_type: registryType,
    active_only: true,
  });
  if (registriesError || !registriesData) {
    throw new Error(errorMessage(registriesError, "Failed to load registries"));
  }

  const registries = zListRegistriesV1RegistriesGetResponse.parse(registriesData);
  const lists = await Promise.all(
    registries.map(async (registry) => {
      const { data, error } = await listRegistryItems(registry.id, {
        limit: 200,
        offset: 0,
      });
      if (error || !data) {
        throw new Error(errorMessage(error, "Failed to load catalog items"));
      }
      return zListRegistryItemsV1RegistriesRegistryIdItemsGetResponse.parse(data);
    })
  );
  const all = lists.flat();
  const suggested = all.filter((item) => isSuggested(item.spec));
  return (suggested.length ? suggested : all)
    .slice(0, max)
    .map((item) => ({ id: item.id, name: item.name, spec: item.spec }));
}
