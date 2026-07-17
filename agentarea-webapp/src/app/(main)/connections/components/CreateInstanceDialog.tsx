"use client";

import { useCallback, useEffect, useState } from "react";
import Image from "next/image";
import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import type { McpServerInstanceResponse } from "@/api/client/types.gen";
import { MCPInstanceConfigForm } from "@/components/MCPInstanceConfigForm";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { checkMCPServerInstanceConfigurationAction as checkMCPServerInstanceConfiguration } from "@/lib/server-actions";
import { createMCPServerInstance } from "../actions";
import { MCPServer } from "../types";
import { getMCPConnectionIconSrc, MCP_CONSTANTS } from "../utils";
import { VerifyingModal } from "./VerifyingModal";

interface CreateInstanceDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  mcpServer: MCPServer | null;
}

export function CreateInstanceDialog({
  open,
  onOpenChange,
  mcpServer,
}: CreateInstanceDialogProps) {
  const [instanceName, setInstanceName] = useState("");
  const [instanceDescription, setInstanceDescription] = useState("");
  const [envVars, setEnvVars] = useState<Record<string, string>>({});
  const [isCreating, setIsCreating] = useState(false);
  const [isChecking, setIsChecking] = useState(false);
  const [verifyingInstance, setVerifyingInstance] = useState<{
    id: string;
    name: string;
  } | null>(null);
  const [validationResult, setValidationResult] = useState<{
    valid: boolean;
    errors: string[];
    warnings: string[];
  } | null>(null);
  const router = useRouter();
  const t = useTranslations("MCPServersPage.createInstance");

  useEffect(() => {
    if (open && mcpServer) {
      setInstanceName(t("defaults.name", { serverName: mcpServer.name }));
      setInstanceDescription(
        t("defaults.description", { serverName: mcpServer.name })
      );
      const initialEnvVars: Record<string, string> = {};
      mcpServer.env_schema?.forEach((envVar) => {
        initialEnvVars[envVar.name as string] =
          (envVar.default as string) || "";
      });
      setEnvVars(initialEnvVars);
      setValidationResult(null);
    }
  }, [open, mcpServer, t]);

  const handleCancel = () => {
    onOpenChange(false);
    setInstanceName("");
    setInstanceDescription("");
    setEnvVars({});
    setValidationResult(null);
  };

  const resetForm = useCallback(() => {
    setInstanceName("");
    setInstanceDescription("");
    setEnvVars({});
    setValidationResult(null);
  }, []);

  const createInstance = useCallback(
    async (skipValidation = false) => {
      if (!mcpServer) {
        toast.error(t("errors.serverNotSelected"));
        return;
      }

      if (!skipValidation && !validationResult?.valid) {
        toast.error(t("errors.validationFailedForceCreate"));
        return;
      }

      setIsCreating(true);
      try {
        const instanceResult = await createMCPServerInstance({
          name: instanceName,
          description: instanceDescription,
          server_spec_id: mcpServer.id,
          json_spec: {
            image: mcpServer.docker_image_url,
            port: MCP_CONSTANTS.DEFAULT_CONTAINER_PORT,
            environment: envVars,
          },
        });

        if (instanceResult.error) {
          const errorDetail = instanceResult.error.detail;
          const errorMessage =
            typeof errorDetail === "string"
              ? errorDetail
              : Array.isArray(errorDetail) && errorDetail[0]?.msg
                ? errorDetail[0].msg
                : "Failed to create MCP instance";
          throw new Error(errorMessage);
        }

        const created = instanceResult.data as McpServerInstanceResponse | null;
        const vStatus = created?.verification?.status;
        onOpenChange(false);
        resetForm();
        if (created) {
          if (vStatus === "in_progress" || vStatus === "never_attempted") {
            setVerifyingInstance({ id: created.id, name: instanceName });
          } else {
            router.push(`/connections/${created.id}`);
          }
        }
      } catch (error) {
        const errorMessage =
          error instanceof Error ? error.message : t("errors.createFailed");
        console.error("Instance creation error:", error);
        toast.error(errorMessage);
      } finally {
        setIsCreating(false);
      }
    },
    [
      instanceName,
      instanceDescription,
      envVars,
      validationResult,
      mcpServer,
      router,
      resetForm,
      onOpenChange,
      t,
    ]
  );

  if (!mcpServer) return null;
  const specIcon = getMCPConnectionIconSrc({}, mcpServer) ?? "/mcp.svg";

  return (
    <>
      {verifyingInstance && (
        <VerifyingModal
          instanceId={verifyingInstance.id}
          instanceName={verifyingInstance.name}
          onSuccess={(id) => {
            setVerifyingInstance(null);
            router.push(`/connections/${id}`);
          }}
          onDelete={() => {
            setVerifyingInstance(null);
            router.refresh();
          }}
          onEditRetry={(id) => {
            setVerifyingInstance(null);
            router.push(`/connections/${id}`);
          }}
        />
      )}
      <Dialog open={open} onOpenChange={onOpenChange}>
        <DialogContent className="max-h-[80vh] max-w-2xl overflow-y-auto">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Image
                src={specIcon}
                alt=""
                width={20}
                height={20}
                className="h-5 w-5 shrink-0 rounded object-contain"
              />
              <span>Configure {mcpServer.name} Instance</span>
              <Badge variant="secondary" className="text-xs">
                {mcpServer.tags?.[0] || "MCP"}
              </Badge>
            </DialogTitle>
            <DialogDescription>{mcpServer.description}</DialogDescription>
          </DialogHeader>

          <div className="space-y-4">
            <MCPInstanceConfigForm
              server={mcpServer}
              instanceName={instanceName}
              instanceDescription={instanceDescription}
              envVars={envVars}
              onChangeName={setInstanceName}
              onChangeDescription={setInstanceDescription}
              onChangeEnvVar={(key, value) => {
                setEnvVars((prev) => ({ ...prev, [key]: value }));
                if (validationResult) setValidationResult(null);
              }}
              onValidate={async () => {
                setIsChecking(true);
                try {
                  const checkResult = await checkMCPServerInstanceConfiguration(
                    {
                      json_spec: {
                        image: mcpServer.docker_image_url,
                        port: MCP_CONSTANTS.DEFAULT_CONTAINER_PORT,
                        environment: envVars,
                      },
                    }
                  );
                  if (checkResult.error) {
                    toast.error(t("errors.validateFailed"));
                  } else {
                    const validationData = checkResult.data as { valid: boolean; errors: string[]; warnings: string[] } | null;
                    setValidationResult(validationData);
                    if (validationData?.valid)
                      toast.success(t("success.valid"));
                    else
                      toast.warning(
                        t("warnings.hasErrors", {
                          count: validationData?.errors?.length || 0,
                        })
                      );
                  }
                } catch (error) {
                  console.error("Validation error:", error);
                  toast.error(t("errors.validateFailed"));
                } finally {
                  setIsChecking(false);
                }
              }}
              validateDisabled={isChecking || !instanceName.trim()}
              validateLoading={isChecking}
              onForceCreate={() => createInstance(true)}
              forceCreateDisabled={isCreating || !instanceName.trim()}
              onSubmit={async (e) => {
                e?.preventDefault();
                if (!validationResult) {
                  toast.warning(t("warnings.validateFirst"));
                  return;
                }
                await createInstance(false);
              }}
              submitDisabled={
                isCreating ||
                !instanceName.trim() ||
                (validationResult ? !validationResult.valid : false)
              }
              submitLabel={
                isCreating ? t("actions.creating") : t("actions.createInstance")
              }
              extraActions={
                <Button
                  variant="outline"
                  onClick={handleCancel}
                  disabled={isCreating}
                  type="button"
                >
                  Cancel
                </Button>
              }
              showContainerSummary
              containerImage={mcpServer.docker_image_url ?? undefined}
              containerPort={MCP_CONSTANTS.DEFAULT_CONTAINER_PORT}
            />
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}
