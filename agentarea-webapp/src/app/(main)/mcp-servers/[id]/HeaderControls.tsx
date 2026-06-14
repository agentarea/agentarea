"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { ExternalLink } from "lucide-react";
import DeleteButton from "@/components/DeleteButton/DeleteButton";
import { Button } from "@/components/ui/button";
import { deleteInstance } from "./actions";
import { initMCPOAuthConnectAction } from "@/lib/server-actions";

export default function MCPInstanceHeaderControls({
  instanceId,
  instanceName,
  instanceType,
  hasAuthConfig,
}: {
  instanceId: string;
  instanceName: string;
  instanceType?: string;
  hasAuthConfig?: boolean;
}) {
  const t = useTranslations("MCPServersPage.instanceDetail");
  const [isActioning, setIsActioning] = useState(false);

  const isUrlType = instanceType === "url";
  const showOAuthConnect = isUrlType && !hasAuthConfig;

  const handleOAuthConnect = async () => {
    setIsActioning(true);
    try {
      const result = await initMCPOAuthConnectAction(instanceId, window.location.origin);
      if (result.error) {
        return;
      }
      if (result.authorize_url) {
        window.location.href = result.authorize_url;
      }
    } catch {
      // silently ignore — error is visible through page state
    } finally {
      setIsActioning(false);
    }
  };

  return (
    <div className="flex flex-wrap items-center gap-2 py-1 sm:flex-nowrap">
      {showOAuthConnect && (
        <Button
          size="xs"
          variant="outline"
          type="button"
          onClick={handleOAuthConnect}
          disabled={isActioning}
        >
          <ExternalLink />
          {t("actions.connectOAuth")}
        </Button>
      )}
      <DeleteButton
        size="xs"
        itemId={instanceId}
        itemName={instanceName}
        onDelete={deleteInstance}
        redirectPath="/mcp-servers"
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
