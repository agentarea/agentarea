"use client";

import { useTranslations } from "next-intl";
import DeleteButton from "@/components/DeleteButton/DeleteButton";
import { deleteOpenAPIConnectionAction } from "@/lib/server-actions";

export default function OpenAPIConnectionHeaderControls({
  connectionId,
  connectionName,
}: {
  connectionId: string;
  connectionName: string;
}) {
  const t = useTranslations("MCPServersPage.openapiDetail");
  const tCommon = useTranslations("Common");

  return (
    <div className="flex items-center gap-2 py-1">
      <DeleteButton
        size="xs"
        itemId={connectionId}
        itemName={connectionName}
        onDelete={deleteOpenAPIConnectionAction}
        redirectPath="/connections"
        title={t("deleteTitle")}
        description={tCommon("deleteDescription", { itemName: connectionName })}
        errorMessages={{
          failedToDelete: t("errors.deleteFailed"),
          unexpectedError: t("errors.deleteFailed"),
        }}
      />
    </div>
  );
}
