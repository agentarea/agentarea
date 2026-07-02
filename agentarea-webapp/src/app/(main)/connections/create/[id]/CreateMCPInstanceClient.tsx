"use client";

import { useState } from "react";
import { useForm } from "react-hook-form";
import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import Image from "next/image";
import { Bot, ExternalLink, Github, Globe, Key, Lock } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge, badgeVariants } from "@/components/ui/badge";
import Divider from "@/components/ui/divider";
import { StartAgentButton } from "@/components/ui/start-agent-button";
import FormLabel from "@/components/FormLabel/FormLabel";
import { cn } from "@/lib/utils";
import { ToolsTable } from "../../components/ToolsTable";
import { MCPInstanceConfigForm } from "@/components/MCPInstanceConfigForm";
import {
  checkMCPServerInstanceConfigurationAction as checkMCPServerInstanceConfiguration,
  validateConnectionAction,
  probeInstanceAuthAction,
  oauthAuthorizeAction,
} from "@/lib/server-actions";
import type { MCPServer } from "../../types";
import { createMCPServerInstance } from "../../actions";
import { getConnectionType, MCP_CONSTANTS } from "../../utils";
import { VerifyingModal } from "../../components/VerifyingModal";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface FieldSpec {
  name: string;
  description?: string;
  isRequired?: boolean;
  isSecret?: boolean;
  default?: string;
  placeholder?: string;
  choices?: string[];
}

interface ValidationResult {
  status: string;
  tool_count?: number;
  tools?: Array<{ name: string; description: string }>;
  message?: string;
}

type ProbeState = "idle" | "needs_oauth" | "needs_both";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

// Tags that describe the connection transport, not a functional category.
const TRANSPORT_TAGS = new Set(["url", "docker", "command", "remote", "mcp"]);

function getIcon(server: MCPServer): string | null {
  const icons = (server as any).json_spec?.icons as
    | Array<{ src: string }>
    | undefined;
  return icons?.[0]?.src ?? null;
}

function getTitle(server: MCPServer): string {
  return (server as any).json_spec?.title || server.name;
}

function getRemoteHeaders(server: MCPServer): FieldSpec[] {
  return (
    (server as any).json_spec?.remotes?.[0]?.headers ||
    (server.env_schema as any[] | undefined)?.filter((e: any) => e.name) ||
    []
  );
}

function getRepoUrl(server: MCPServer): string | null {
  return (server as any).json_spec?.repository?.url ?? null;
}

function getWebsiteUrl(server: MCPServer): string | null {
  return (server as any).json_spec?.websiteUrl ?? null;
}

function getRepoSource(server: MCPServer): string | null {
  return (server as any).json_spec?.repository?.source ?? null;
}

function getVersion(server: MCPServer): string | null {
  return (server as any).version || (server as any).json_spec?.version || null;
}

function getCategories(server: MCPServer): string[] {
  const tags = (server as any).tags as string[] | undefined;
  if (!Array.isArray(tags)) return [];
  return tags
    .filter((t) => typeof t === "string" && t && !TRANSPORT_TAGS.has(t.toLowerCase()))
    .slice(0, 4);
}

function getToolCount(server: MCPServer): number {
  const tools = (server as any).json_spec?.available_tools;
  return Array.isArray(tools) ? tools.length : 0;
}

// --- small identity building blocks (reuse our Badge) -----------------------

function StatusBadge({ verified }: { verified: boolean }) {
  return (
    <Badge variant="outline">
      <span
        className={cn(
          "h-[7px] w-[7px] rounded-full",
          verified ? "bg-green-500" : "bg-amber-500"
        )}
      />
      {verified ? "Verified" : "Needs verification"}
    </Badge>
  );
}

function LinkPill({
  href,
  icon: Icon,
  children,
}: {
  href: string;
  icon: typeof Github;
  children: React.ReactNode;
}) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className={cn(
        badgeVariants({ variant: "outline" }),
        "hover:text-foreground"
      )}
    >
      <Icon className="h-3.5 w-3.5" />
      {children}
    </a>
  );
}

function SpecHeader({
  server,
  verified,
}: {
  server: MCPServer;
  verified: boolean;
}) {
  const iconSrc = getIcon(server);
  const title = getTitle(server);
  const version = getVersion(server);
  const repoUrl = getRepoUrl(server);
  const websiteUrl = getWebsiteUrl(server);
  const repoSource = getRepoSource(server);
  const categories = getCategories(server);
  const toolCount = getToolCount(server);

  return (
    <div className="flex items-start gap-4">
      <div className="flex h-[60px] w-[60px] shrink-0 items-center justify-center overflow-hidden rounded-2xl border bg-muted">
        {iconSrc ? (
          <Image
            src={iconSrc}
            alt={title}
            width={32}
            height={32}
            className="h-8 w-8 rounded"
            unoptimized
          />
        ) : (
          <Globe className="h-7 w-7 text-muted-foreground" />
        )}
      </div>

      <div className="min-w-0 flex-1 pt-0.5">
        <div className="flex flex-wrap items-center gap-2">
          <h1 className="text-xl font-semibold tracking-tight">{title}</h1>
          {version && (
            <span className="font-mono text-[11px] text-muted-foreground">
              v{version.replace(/^v/, "")}
            </span>
          )}
        </div>

        {server.description && (
          <p className="mt-1.5 max-w-[54ch] text-sm text-muted-foreground">
            {server.description}
          </p>
        )}

        <div className="mt-3 flex flex-wrap items-center gap-2">
          <StatusBadge verified={verified} />
          {repoUrl && (
            <LinkPill
              href={repoUrl}
              icon={repoSource === "github" ? Github : Globe}
            >
              {repoSource === "github" ? "GitHub" : "Repository"}
            </LinkPill>
          )}
          {websiteUrl && (
            <LinkPill href={websiteUrl} icon={ExternalLink}>
              Website
            </LinkPill>
          )}
        </div>

        {(categories.length > 0 || toolCount > 0) && (
          <div className="mt-2.5 flex flex-wrap items-center gap-2">
            {categories.map((c) => (
              <Badge key={c} variant="gray">
                {c}
              </Badge>
            ))}
            {toolCount > 0 && <Badge variant="gray">{toolCount} tools</Badge>}
          </div>
        )}
      </div>
    </div>
  );
}

function EncryptionNote() {
  return (
    <div className="mt-6 flex items-center gap-2 text-xs text-muted-foreground">
      <Lock className="h-3.5 w-3.5" />
      Credentials are encrypted at rest and scoped to this workspace.
    </div>
  );
}

// ---------------------------------------------------------------------------
// URL-type connect form (react-hook-form)
// ---------------------------------------------------------------------------

interface UrlFormValues {
  instanceName: string;
  fields: Record<string, string>;
}

function UrlConnectForm({ server }: { server: MCPServer }) {
  const router = useRouter();
  const remoteHeaders = getRemoteHeaders(server);
  const hasFields = remoteHeaders.length > 0;
  const endpointUrl = server.remote_url || "";

  const defaultFieldValues: Record<string, string> = {};
  for (const h of remoteHeaders) {
    defaultFieldValues[h.name] = h.default || "";
  }

  const {
    register,
    getValues,
  } = useForm<UrlFormValues>({
    defaultValues: {
      instanceName: getTitle(server),
      fields: defaultFieldValues,
    },
  });

  const [error, setError] = useState<string | null>(null);
  const [validation, setValidation] = useState<ValidationResult | null>(null);
  const [probeState, setProbeState] = useState<ProbeState>("idle");
  const [authTab, setAuthTab] = useState<"oauth" | "manual">("manual");
  const [createdInstanceId, setCreatedInstanceId] = useState<string | null>(null);
  const [isWorking, setIsWorking] = useState(false);
  const [verifyingInstance, setVerifyingInstance] = useState<{ id: string; name: string } | null>(null);

  // Build headers dict from form field values
  const buildHeaders = (): Record<string, string> => {
    const vals = getValues("fields");
    const headers: Record<string, string> = {};
    for (const [key, val] of Object.entries(vals)) {
      if (val?.trim()) headers[key] = val.trim();
    }
    return headers;
  };

  // Validate connection (fields present)
  const handleValidate = async () => {
    setError(null);
    setValidation(null);
    setIsWorking(true);

    try {
      if (hasFields) {
        const result = await validateConnectionAction(endpointUrl, buildHeaders());

        if (result.error) {
          setError(result.error);
          return;
        }
        if (result.data?.status === "auth_error") {
          setError(result.data.message || "Authentication failed");
          return;
        }
        if (result.data?.status !== "ok") {
          setError(result.data?.message || "Connection failed");
          return;
        }

        setValidation(result.data);
        return;
      }

      // No fields — probe for auth method
      const { instanceName } = getValues();
      const instanceResult = await createMCPServerInstance({
        name: instanceName,
        description: server.description,
        server_spec_id: server.id,
        json_spec: { type: "url", endpoint_url: endpointUrl },
      });

      if (instanceResult.error) {
        const d = instanceResult.error.detail;
        throw new Error(
          typeof d === "string"
            ? d
            : Array.isArray(d) && d[0]?.msg
              ? d[0].msg
              : "Failed to create instance"
        );
      }

      const created = instanceResult.data as any;
      setCreatedInstanceId(created.id);

      const probeResult = await probeInstanceAuthAction(created.id);

      if (probeResult.data?.status === "ok") {
        router.push(`/connections/${created.id}`);
        return;
      }
      if (probeResult.data?.status === "auth_required") {
        const methods = probeResult.data.methods || [];
        if (methods.includes("oauth")) {
          setProbeState(methods.includes("credentials") ? "needs_both" : "needs_oauth");
          setAuthTab("oauth");
          return;
        }
      }

      router.push(`/connections/${created.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Connection failed");
    } finally {
      setIsWorking(false);
    }
  };

  // Create instance after successful validation
  const handleCreate = async () => {
    setIsWorking(true);
    setError(null);
    try {
      const { instanceName } = getValues();
      const headers = buildHeaders();

      const instanceResult = await createMCPServerInstance({
        name: instanceName,
        description: server.description,
        server_spec_id: server.id,
        json_spec: {
          type: "url",
          endpoint_url: endpointUrl,
          ...(Object.keys(headers).length > 0 ? { headers } : {}),
        },
      });

      if (instanceResult.error) {
        const d = instanceResult.error.detail;
        throw new Error(
          typeof d === "string"
            ? d
            : Array.isArray(d) && d[0]?.msg
              ? d[0].msg
              : "Failed to create instance"
        );
      }

      const created = instanceResult.data as any;
      const vStatus = created?.verification?.status;
      if (vStatus === "in_progress" || vStatus === "never_attempted") {
        const { instanceName } = getValues();
        setVerifyingInstance({ id: created.id, name: instanceName });
      } else {
        router.push(`/connections/${created.id}`);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create connection");
    } finally {
      setIsWorking(false);
    }
  };

  // OAuth flow
  const handleOAuth = async () => {
    if (!createdInstanceId) return;
    setIsWorking(true);
    setError(null);
    try {
      const result = await oauthAuthorizeAction(createdInstanceId);
      if (result.error || !result.data?.authorize_url) {
        setError(result.error || "OAuth discovery failed — this server may not support OAuth");
        return;
      }
      window.location.href = result.data.authorize_url;
    } catch {
      setError("Failed to start OAuth flow");
    } finally {
      setIsWorking(false);
    }
  };

  const verified = validation?.status === "ok";

  return (
    <>
      {verifyingInstance && (
        <VerifyingModal
          instanceId={verifyingInstance.id}
          instanceName={verifyingInstance.name}
          onSuccess={(id) => router.push(`/connections/${id}`)}
          onDelete={() => router.push("/connections")}
          onEditRetry={(id) => {
            setVerifyingInstance(null);
            router.push(`/connections/${id}`);
          }}
        />
      )}
      <div className="mx-auto w-full max-w-[600px] px-2 py-10">
        <SpecHeader server={server} verified={verified} />

        <Divider className="my-6" />

        {/* Instance name */}
        <div className="flex flex-col gap-2">
          <FormLabel htmlFor="instance-name" icon={Bot} required>
            Name
          </FormLabel>
          <Input
            id="instance-name"
            autoComplete="off"
            {...register("instanceName", { required: true })}
          />
          <p className="text-xs text-muted-foreground">
            Shown across agents, tasks and audit logs. Must be unique in this
            workspace.
          </p>
        </div>

        {/* Error */}
        {error && (
          <div className="mt-6 rounded-lg border border-destructive/20 bg-destructive/5 p-3 text-sm text-destructive">
            {error}
          </div>
        )}

        {/* Spec fields */}
        {hasFields && probeState === "idle" && (
          <div className="mt-6 space-y-4">
            {remoteHeaders.map((field) => (
              <div key={field.name} className="flex flex-col gap-2">
                <FormLabel
                  htmlFor={`field-${field.name}`}
                  icon={field.isSecret ? Key : undefined}
                  required={field.isRequired !== false}
                >
                  {field.name}
                </FormLabel>
                {field.description && (
                  <p className="text-xs text-muted-foreground">
                    {field.description}
                  </p>
                )}
                {field.choices && field.choices.length > 0 ? (
                  <select
                    id={`field-${field.name}`}
                    className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm"
                    {...register(`fields.${field.name}`)}
                  >
                    <option value="">Select...</option>
                    {field.choices.map((c) => (
                      <option key={c} value={c}>
                        {c}
                      </option>
                    ))}
                  </select>
                ) : (
                  <Input
                    id={`field-${field.name}`}
                    type={field.isSecret ? "password" : "text"}
                    placeholder={field.placeholder || ""}
                    {...register(`fields.${field.name}`)}
                  />
                )}
              </div>
            ))}
          </div>
        )}

        {/* Validation success — tools table + create button */}
        {validation?.status === "ok" && (
          <div className="mt-6 space-y-4">
            {validation.tools && validation.tools.length > 0 && (
              <ToolsTable
                tools={validation.tools}
                label={`${validation.tools.length} tools found`}
              />
            )}
            <StartAgentButton
              size="md"
              onClick={handleCreate}
              isLoading={isWorking}
              disabled={isWorking}
            >
              Create connection
            </StartAgentButton>
          </div>
        )}

        {/* Connect button — initial state */}
        {!validation && probeState === "idle" && (
          <div className="mt-6">
            <StartAgentButton
              size="md"
              onClick={handleValidate}
              isLoading={isWorking}
              disabled={isWorking}
            >
              {isWorking ? "Connecting…" : "Connect"}
            </StartAgentButton>
          </div>
        )}

        {/* OAuth/Manual switcher (probe detected auth) */}
        {(probeState === "needs_oauth" || probeState === "needs_both") && (
          <div className="mt-6 space-y-4">
            {probeState === "needs_both" && (
              <div className="flex w-fit rounded-lg border p-0.5">
                <button
                  type="button"
                  className={`rounded-md px-4 py-1.5 text-sm transition-colors ${authTab === "oauth" ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground"}`}
                  onClick={() => setAuthTab("oauth")}
                >
                  OAuth
                </button>
                <button
                  type="button"
                  className={`rounded-md px-4 py-1.5 text-sm transition-colors ${authTab === "manual" ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground"}`}
                  onClick={() => setAuthTab("manual")}
                >
                  Manual
                </button>
              </div>
            )}

            {(authTab === "oauth" || probeState === "needs_oauth") && (
              <div className="space-y-3">
                <p className="text-sm text-muted-foreground">
                  This server supports OAuth authorization.
                </p>
                <StartAgentButton
                  size="md"
                  onClick={handleOAuth}
                  isLoading={isWorking}
                >
                  Authorize with OAuth
                </StartAgentButton>
                {probeState === "needs_oauth" && (
                  <button
                    type="button"
                    className="block text-xs text-muted-foreground transition-colors hover:text-foreground"
                    onClick={() => {
                      setProbeState("needs_both");
                      setAuthTab("manual");
                    }}
                  >
                    Have credentials? Enter manually instead
                  </button>
                )}
              </div>
            )}

            {authTab === "manual" && probeState === "needs_both" && (
              <div className="space-y-3">
                <div className="flex flex-col gap-2">
                  <FormLabel htmlFor="manual-header" icon={Key}>
                    Authorization
                  </FormLabel>
                  <Input
                    id="manual-header"
                    placeholder="Bearer your-token"
                    {...register("fields.Authorization")}
                  />
                </div>
                <StartAgentButton
                  size="md"
                  onClick={handleCreate}
                  isLoading={isWorking}
                  disabled={isWorking}
                >
                  Connect
                </StartAgentButton>
              </div>
            )}
          </div>
        )}

        {/* Retry on error */}
        {error && (
          <Button
            variant="outline"
            className="mt-4 w-auto"
            onClick={() => {
              setError(null);
              setValidation(null);
            }}
          >
            Try Again
          </Button>
        )}

        <EncryptionNote />
      </div>
    </>
  );
}

// ---------------------------------------------------------------------------
// Docker/Command form (existing MCPInstanceConfigForm)
// ---------------------------------------------------------------------------

function DockerCommandForm({ server }: { server: MCPServer }) {
  const router = useRouter();
  const t = useTranslations("MCPServersPage.createInstance");

  const [instanceName, setInstanceName] = useState(getTitle(server));
  const [instanceDescription, setInstanceDescription] = useState(server.description);
  const [envVars, setEnvVars] = useState<Record<string, string>>(() => {
    const init: Record<string, string> = {};
    server.env_schema?.forEach((envVar) => {
      init[envVar.name as string] = (envVar.default as string) || "";
    });
    return init;
  });
  const [isCreating, setIsCreating] = useState(false);
  const [isChecking, setIsChecking] = useState(false);
  const [verifyingInstance, setVerifyingInstance] = useState<{ id: string; name: string } | null>(null);
  const [validationResult, setValidationResult] = useState<{
    valid: boolean;
    errors: string[];
    warnings: string[];
  } | null>(null);

  const createInstance = async (skipValidation = false) => {
    if (!instanceName.trim()) return;
    if (!skipValidation && !validationResult?.valid) return;

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
      const vStatus = created?.verification?.status;
      if (vStatus === "in_progress" || vStatus === "never_attempted") {
        setVerifyingInstance({ id: created.id, name: instanceName });
      } else {
        router.replace(`/connections/${created.id}`);
      }
    } catch (error) {
      console.error("Instance creation error:", error);
    } finally {
      setIsCreating(false);
    }
  };

  return (
    <>
      {verifyingInstance && (
        <VerifyingModal
          instanceId={verifyingInstance.id}
          instanceName={verifyingInstance.name}
          onSuccess={(id) => router.replace(`/connections/${id}`)}
          onDelete={() => router.replace("/connections")}
          onEditRetry={(id) => {
            setVerifyingInstance(null);
            router.replace(`/connections/${id}`);
          }}
        />
      )}
      <div className="mx-auto w-full max-w-[600px] px-2 py-10">
        <SpecHeader server={server} verified={false} />
        <Divider className="my-6" />
        <MCPInstanceConfigForm
          formId="mcp-instance-form"
          className="h-full overflow-auto"
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
              if (!checkResult.error) {
                setValidationResult(checkResult.data as any);
              }
            } catch (error) {
              console.error("Validation error:", error);
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
            if (!validationResult) return;
            await createInstance(false);
          }}
          submitDisabled={
            isCreating ||
            !instanceName.trim() ||
            (validationResult ? !validationResult.valid : false)
          }
          submitLabel={isCreating ? t("actions.creating") : t("actions.createInstance")}
          showContainerSummary
          containerImage={server.docker_image_url ?? undefined}
          containerPort={MCP_CONSTANTS.DEFAULT_CONTAINER_PORT}
        />
      </div>
    </>
  );
}

// ---------------------------------------------------------------------------
// Main export
// ---------------------------------------------------------------------------

export default function CreateMCPInstanceClient({
  server,
}: {
  server: MCPServer;
}) {
  const connType = getConnectionType(server);

  if (connType === "url") {
    return <UrlConnectForm server={server} />;
  }

  return <DockerCommandForm server={server} />;
}
