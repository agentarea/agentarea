"use client";

import { useCallback, useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { ExternalLink, Globe } from "lucide-react";
import { Button } from "@/components/ui/button";
import { MCPInstanceConfigForm } from "@/components/MCPInstanceConfigForm";
import {
  checkMCPServerInstanceConfigurationAction as checkMCPServerInstanceConfiguration,
} from "@/lib/server-actions";
import type { MCPServer } from "../../types";
import { createMCPServerInstance } from "../../actions";
import { getConnectionType, MCP_CONSTANTS } from "../../utils";

export default function CreateMCPInstanceClient({
  server,
}: {
  server: MCPServer;
}) {
  const router = useRouter();
  const t = useTranslations("MCPServersPage.createInstance");
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

  useEffect(() => {
    setInstanceName(t("defaults.name", { serverName: server.name }));
    setInstanceDescription(t("defaults.description", { serverName: server.name }));
    const initialEnvVars: Record<string, string> = {};
    server.env_schema?.forEach((envVar) => {
      initialEnvVars[envVar.name as string] = (envVar.default as string) || "";
    });
    setEnvVars(initialEnvVars);
    setValidationResult(null);
  }, [server, t]);

  const createInstance = useCallback(
    async (skipValidation = false) => {
      if (!server) return;
      if (!instanceName.trim()) {
        toast.warning(t("errors.nameRequired"));
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
          server_spec_id: server.id,
          json_spec: {
            image: server.docker_image_url,
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

        const created = instanceResult.data as any;
        toast.success(t("success.created", { instanceName }));

        router.replace("/mcp-servers");
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
      envVars,
      instanceDescription,
      instanceName,
      router,
      server,
      t,
      validationResult,
    ]
  );

  useEffect(() => {
    const form = document.getElementById("mcp-instance-form");
    if (!form) return;
    const handler = () => {
      createInstance(true);
    };
    form.addEventListener("mcp-force-create", handler as EventListener);
    return () => {
      form.removeEventListener("mcp-force-create", handler as EventListener);
    };
  }, [createInstance]);

  // Remote URL type — show simplified connect flow instead of Docker form
  const connType = getConnectionType(server);
  if (connType === "url") {
    const handleConnectOAuth = async () => {
      setIsCreating(true);
      try {
        // Create the instance first as URL type
        const instanceResult = await createMCPServerInstance({
          name: instanceName,
          description: instanceDescription,
          server_spec_id: server.id,
          json_spec: {
            type: "url",
            endpoint_url: server.remote_url || "",
          },
        });

        if (instanceResult.error) {
          const errorDetail = instanceResult.error.detail;
          const errorMessage =
            typeof errorDetail === "string"
              ? errorDetail
              : Array.isArray(errorDetail) && errorDetail[0]?.msg
                ? errorDetail[0].msg
                : t("errors.createFailed");
          throw new Error(errorMessage);
        }

        const created = instanceResult.data as any;
        toast.success(t("success.created", { instanceName }));

        // Start OAuth flow for the new instance
        const apiBase = (window as any).__ENV__?.CLIENT_API_URL || "http://localhost:8000";
        window.location.href = `${apiBase}/v1/mcp-oauth/authorize?instance_id=${created.id}`;
      } catch (error) {
        const errorMessage =
          error instanceof Error ? error.message : t("errors.createFailed");
        toast.error(errorMessage);
        setIsCreating(false);
      }
    };

    return (
      <div className="mx-auto w-full max-w-md space-y-6 py-8">
        <div className="flex flex-col items-center gap-4 text-center">
          <div className="rounded-full bg-muted p-4">
            <Globe className="h-8 w-8 text-muted-foreground" />
          </div>
          <div>
            <h3 className="text-lg font-semibold">{server.name}</h3>
            <p className="mt-1 text-sm text-muted-foreground">
              {server.description}
            </p>
          </div>
        </div>

        <div className="rounded-lg border bg-muted/50 p-4 text-sm text-muted-foreground">
          <p>{t("remoteConnect.description")}</p>
        </div>

        <Button
          className="w-full"
          size="lg"
          onClick={handleConnectOAuth}
          isLoading={isCreating}
          disabled={isCreating}
        >
          <ExternalLink className="mr-2 h-4 w-4" />
          {isCreating ? t("remoteConnect.connecting") : t("remoteConnect.connect")}
        </Button>
      </div>
    );
  }

  return (
    <div className="mx-auto w-full max-w-xl">
      <MCPInstanceConfigForm
        formId="mcp-instance-form"
        className="overflow-auto h-full"
        hideSubmitButton
        hideForceCreateButton
        server={server as any}
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
                image: server.docker_image_url,
                port: MCP_CONSTANTS.DEFAULT_CONTAINER_PORT,
                environment: envVars,
              },
            });
            if (checkResult.error) {
              toast.error(t("errors.validateFailed"));
            } else {
              const validationData = checkResult.data as any;
              setValidationResult(validationData);
              if (validationData?.valid) toast.success(t("success.valid"));
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
        showContainerSummary
        containerImage={server.docker_image_url}
        containerPort={MCP_CONSTANTS.DEFAULT_CONTAINER_PORT}
      />
    </div>
  );
}
