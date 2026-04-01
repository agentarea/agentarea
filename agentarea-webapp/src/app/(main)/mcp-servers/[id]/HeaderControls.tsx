"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { ExternalLink, Play, Square } from "lucide-react";
import { toast } from "sonner";
import { useRouter } from "next/navigation";
import DeleteButton from "@/components/DeleteButton/DeleteButton";
import { Button } from "@/components/ui/button";
import { deleteInstance, startInstance, stopInstance } from "./actions";
import { initMCPOAuthConnectAction } from "@/lib/server-actions";

export default function MCPInstanceHeaderControls({
  instanceId,
  instanceName,
  status,
  instanceType,
  hasAuthConfig,
}: {
  instanceId: string;
  instanceName: string;
  status: string;
  instanceType?: string;
  hasAuthConfig?: boolean;
}) {
  const router = useRouter();
  const t = useTranslations("MCPServersPage.instanceDetail");
  const [isActioning, setIsActioning] = useState(false);

  const canStart = status !== "running" && status !== "starting" && status !== "connected";
  const canStop = status === "running" || status === "starting";

  const handleStart = async () => {
    setIsActioning(true);
    try {
      const { error } = await startInstance(instanceId);
      if (error)
        throw new Error(
          typeof error === "object" && "detail" in error
            ? String((error as any).detail)
            : t("errors.startFailed")
        );
      toast.success(t("success.starting", { instanceName }));
      router.refresh();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : t("errors.startFailed"));
    } finally {
      setIsActioning(false);
    }
  };

  const handleStop = async () => {
    setIsActioning(true);
    try {
      const { error } = await stopInstance(instanceId);
      if (error)
        throw new Error(
          typeof error === "object" && "detail" in error
            ? String((error as any).detail)
            : t("errors.stopFailed")
        );
      toast.success(t("success.stopped", { instanceName }));
      router.refresh();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : t("errors.stopFailed"));
    } finally {
      setIsActioning(false);
    }
  };

  const isUrlType = instanceType === "url";
  const showOAuthConnect = isUrlType && !hasAuthConfig;

  const handleOAuthConnect = async () => {
    setIsActioning(true);
    try {
      const result = await initMCPOAuthConnectAction(instanceId, window.location.origin);
      if (result.error) {
        toast.error(`OAuth connect failed: ${result.error}`);
        return;
      }
      if (result.authorize_url) {
        window.location.href = result.authorize_url;
      }
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "OAuth connect failed");
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
        >
          <ExternalLink />
          {t("actions.connectOAuth")}
        </Button>
      )}
      {canStart && (
        <Button
          size="xs"
          variant="outline"
          type="button"
          onClick={handleStart}
          isLoading={isActioning}
          disabled={isActioning}
        >
          <Play />
          {t("actions.start")}
        </Button>
      )}
      {canStop && (
        <Button
          size="xs"
          variant="outline"
          type="button"
          onClick={handleStop}
          isLoading={isActioning}
          disabled={isActioning}
        >
          <Square />
          {t("actions.stop")}
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
