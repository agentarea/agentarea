"use client";

import { useState, useTransition } from "react";
import { useTranslations } from "next-intl";
import type { CatalogKeyFieldResponse } from "@/api/client/types.gen";
import FormError from "@/components/FormError";
import { useWorkspaceRouter } from "@/hooks/useWorkspaceNavigation";
import { connectionHref } from "@/lib/catalog-connections";
import { connectCatalogApiAction } from "@/lib/server-actions";
import { ConnectKeyForm } from "./ConnectKeyForm";

/**
 * Connect a catalog API that takes keys rather than a sign-in: one form for
 * every key the vendor needs, and the connection exists once they are saved.
 */
export function CatalogKeyConnect({
  itemId,
  provider,
  fields,
  returnPath,
}: {
  itemId: string;
  provider: string;
  fields: CatalogKeyFieldResponse[];
  /** Where to land once connected, to be told so; without it, the new connection opens. */
  returnPath?: string;
}) {
  const t = useTranslations("MCPServersPage.catalogConnect");
  const router = useWorkspaceRouter();
  const [pending, startTransition] = useTransition();
  const [error, setError] = useState<string | null>(null);

  function save(values: Record<string, string>) {
    setError(null);
    startTransition(async () => {
      const result = await connectCatalogApiAction(itemId, {
        credentials: fields.map((field) => ({
          name: field.name,
          value: values[field.name] ?? "",
        })),
      });
      if (!result.data) {
        setError(result.error);
        return;
      }
      router.replace(
        returnPath ?? connectionHref({ id: result.data.id, kind: "openapi" })
      );
    });
  }

  return (
    <div className="space-y-4">
      <ConnectKeyForm
        fields={fields.map((field) => ({
          name: field.name,
          label: field.label,
          description: field.description ?? undefined,
          isSecret: true,
        }))}
        title={t("keysTitle", { provider, count: fields.length })}
        detail={t("keysDetail", { provider, count: fields.length })}
        pending={pending}
        onSave={save}
      />
      {error && <FormError>{error}</FormError>}
    </div>
  );
}
