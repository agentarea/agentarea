"use client";

import { useTranslations } from "next-intl";
import DeleteButton from "@/components/DeleteButton/DeleteButton";
import { deleteInstance } from "./actions";

/**
 * Authorizing lives in the page's authorization panel, not here: the header had
 * no way to know whether OAuth could complete, so it offered Connect for every
 * URL-type connection and dropped the resulting error on the floor.
 */
export default function MCPInstanceHeaderControls({
  instanceId,
  instanceName,
}: {
  instanceId: string;
  instanceName: string;
}) {
  const t = useTranslations("MCPServersPage.instanceDetail");

  return (
    <div className="flex flex-wrap items-center gap-2 py-1 sm:flex-nowrap">
      <DeleteButton
        size="xs"
        itemId={instanceId}
        itemName={instanceName}
        onDelete={deleteInstance}
        redirectPath="/connections"
        title={t("confirm.deleteTitle")}
        description={t("confirm.deleteDescription", { instanceName })}
        successMessage={t("success.deleted", { instanceName })}
        errorMessages={{
          failedToDelete: t("errors.deleteFailed"),
          unexpectedError: t("errors.deleteFailed"),
        }}
      />
    </div>
  );
}
