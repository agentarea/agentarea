"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { MCPInstanceConfigForm } from "@/components/MCPInstanceConfigForm";
import {
  checkMCPServerInstanceConfiguration,
} from "@/lib/browser-api";
import type { MCPServer } from "../../types";
import { createMCPServerInstance } from "../../actions";
import { MCP_CONSTANTS } from "../../utils";

export default function CreateMCPInstanceClient({
  server,
}: {
  server: MCPServer;
}) {
  const router = useRouter();
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
    setInstanceName(`${server.name} Instance`);
    setInstanceDescription(`Instance of ${server.name}`);
    const initialEnvVars: Record<string, string> = {};
    server.env_schema?.forEach((envVar) => {
      initialEnvVars[envVar.name] = envVar.default || "";
    });
    setEnvVars(initialEnvVars);
    setValidationResult(null);
  }, [server]);

  const createInstance = useCallback(
    async (skipValidation = false) => {
      if (!server) return;
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
        toast.success(`Successfully created ${instanceName}`);

        if (created?.id) {
          router.push(`/mcp-servers/${created.id}`);
        } else {
          router.push("/mcp-servers");
        }
        router.refresh();
      } catch (error) {
        const errorMessage =
          error instanceof Error ? error.message : "Failed to create MCP instance";
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
      validationResult,
    ]
  );

  return (
    <div className="mx-auto w-full max-w-xl">
      <MCPInstanceConfigForm
        formId="mcp-instance-form"
        className="overflow-auto h-full"
        hideSubmitButton
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
              toast.error("Failed to validate configuration");
            } else {
              const validationData = checkResult.data as any;
              setValidationResult(validationData);
              if (validationData?.valid) toast.success("Configuration is valid!");
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
        showContainerSummary
        containerImage={server.docker_image_url}
        containerPort={MCP_CONSTANTS.DEFAULT_CONTAINER_PORT}
      />
    </div>
  );
}
