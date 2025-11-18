"use client";

import { useEffect, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
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
import { checkMCPServerInstanceConfiguration } from "@/lib/browser-api";
import { createMCPServerInstance } from "../actions";
import { MCPServer } from "../types";
import { MCP_CONSTANTS } from "../utils";

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
  const [validationResult, setValidationResult] = useState<{
    valid: boolean;
    errors: string[];
    warnings: string[];
  } | null>(null);
  const router = useRouter();

  useEffect(() => {
    if (open && mcpServer) {
      setInstanceName(`${mcpServer.name} Instance`);
      setInstanceDescription(`Instance of ${mcpServer.name}`);
      const initialEnvVars: Record<string, string> = {};
      mcpServer.env_schema?.forEach((envVar) => {
        initialEnvVars[envVar.name] = envVar.default || "";
      });
      setEnvVars(initialEnvVars);
      setValidationResult(null);
    }
  }, [open, mcpServer]);

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
        toast.error("MCP server is not selected");
        return;
      }

      if (!skipValidation && !validationResult?.valid) {
        toast.error(
          'Configuration validation failed. Use "Force Create" to proceed.'
        );
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

        toast.success(`Successfully created ${instanceName}`);
        onOpenChange(false);
        router.refresh();
        resetForm();
      } catch (error) {
        const errorMessage =
          error instanceof Error
            ? error.message
            : "Failed to create MCP instance";
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
    ]
  );

  if (!mcpServer) return null;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[80vh] max-w-2xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <span>Configure {mcpServer.name} Instance</span>
            <Badge variant="secondary" className="text-xs">
              {mcpServer.tags?.[0] || "MCP"}
            </Badge>
          </DialogTitle>
          <DialogDescription>{mcpServer.description}</DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <MCPInstanceConfigForm
            server={mcpServer as any}
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
                const checkResult = await checkMCPServerInstanceConfiguration({
                  json_spec: {
                    image: mcpServer.docker_image_url,
                    port: MCP_CONSTANTS.DEFAULT_CONTAINER_PORT,
                    environment: envVars,
                  },
                });
                if (checkResult.error) {
                  toast.error("Failed to validate configuration");
                } else {
                  const validationData = checkResult.data as any;
                  setValidationResult(validationData);
                  if (validationData?.valid)
                    toast.success("Configuration is valid!");
                  else
                    toast.warning(
                      `Configuration has ${validationData?.errors?.length || 0} error(s)`
                    );
                }
              } catch (error) {
                console.error("Validation error:", error);
                toast.error("Failed to validate configuration");
              } finally {
                setIsChecking(false);
              }
            }}
            validateDisabled={isChecking || !instanceName.trim()}
            onForceCreate={() => createInstance(true)}
            forceCreateDisabled={isCreating || !instanceName.trim()}
            onSubmit={async (e) => {
              e?.preventDefault();
              if (!validationResult) {
                toast.warning("Please validate the configuration first");
                return;
              }
              await createInstance(false);
            }}
            submitDisabled={
              isCreating ||
              !instanceName.trim() ||
              (validationResult ? !validationResult.valid : false)
            }
            submitLabel={isCreating ? "Creating..." : "Create Instance"}
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
            containerImage={mcpServer.docker_image_url}
            containerPort={MCP_CONSTANTS.DEFAULT_CONTAINER_PORT}
          />
        </div>
      </DialogContent>
    </Dialog>
  );
}
