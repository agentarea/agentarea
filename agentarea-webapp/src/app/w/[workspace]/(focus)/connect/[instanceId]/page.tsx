import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import { notFound } from "next/navigation";
import {
  declaredCredentialFields,
  missingSecretFields,
  requiredSecretFields,
} from "@/app/w/[workspace]/(main)/connections/credential-fields";
import type { MCPOAuthPreflight } from "@/app/w/[workspace]/(main)/connections/oauth-connect-state";
import {
  getEffectiveMCPVerificationStatus,
  getMCPConnectionTitle,
} from "@/app/w/[workspace]/(main)/connections/utils";
import { getMCPServer, getMCPServerInstance } from "@/lib/api";
import { mcpIdentity } from "@/lib/entity-identity";
import { mcpOAuthPreflightAction } from "@/lib/server-actions";
import { optionalApiData, requireApiData } from "@/lib/server-resource";
import { getWorkspaces } from "@/lib/workspace-context";
import { workspacePath } from "@/lib/workspace-routes";
import {
  deriveConnectStep,
  needsOAuthPreflight,
  type VerificationError,
} from "./connect-step";
import ConnectInstance from "./ConnectInstance";

interface Props {
  params: Promise<{ workspace: string; instanceId: string }>;
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { instanceId } = await params;
  const t = await getTranslations("MCPServersPage.connectLink");
  const instance = requireApiData(
    await getMCPServerInstance(instanceId),
    "MCP instance"
  );
  return { title: t("metaTitle", { name: instance.name }) };
}

/**
 * Where a connect link lands: an agent created the connection and hands the
 * user this page to finish it — sign in or paste a key, nothing else.
 */
export default async function ConnectPage({ params }: Props) {
  const { workspace, instanceId } = await params;
  const t = await getTranslations("MCPServersPage");

  const instance = requireApiData(
    await getMCPServerInstance(instanceId),
    "MCP instance"
  );
  const jsonSpec = instance.json_spec;
  const storedSecrets = Array.isArray(jsonSpec.env_vars)
    ? jsonSpec.env_vars
    : [];
  const verification = {
    verificationStatus: getEffectiveMCPVerificationStatus(instance),
    verificationError: (instance.verification as { error?: VerificationError })
      .error,
  };
  const credentials = {
    transport: instance.transport,
    authorized: !!instance.auth_config_id,
    hasStoredSecrets: storedSecrets.length > 0,
  };

  const [serverSpecResult, preflightResult, workspaces] = await Promise.all([
    getMCPServer(instance.server_spec_id),
    needsOAuthPreflight({ ...credentials, ...verification })
      ? mcpOAuthPreflightAction({ instance_id: instance.id })
      : null,
    getWorkspaces(),
  ]);
  const serverSpec = optionalApiData(
    serverSpecResult,
    `MCP server ${instance.server_spec_id}`
  );
  const preflight = (preflightResult?.data ?? null) as MCPOAuthPreflight | null;

  const declared = declaredCredentialFields(serverSpec, instance.transport);
  const missingFields = missingSecretFields(declared, jsonSpec);
  const step = deriveConnectStep({
    ...credentials,
    ...verification,
    secretFields: requiredSecretFields(declared),
    missingFields,
    oauth: preflight,
  });
  // A provider can advertise sign-in and refuse it; the key is the way out.
  const keyFields = step.kind === "needs_sign_in" ? missingFields : [];

  const endpointUrl =
    (typeof jsonSpec.endpoint_url === "string" && jsonSpec.endpoint_url) ||
    serverSpec?.remote_url;

  const current = workspaces.find((candidate) => candidate.slug === workspace);
  if (!current) notFound();

  return (
    <ConnectInstance
      instanceId={instance.id}
      name={instance.name}
      provider={getMCPConnectionTitle(instance, serverSpec)}
      workspaceName={current.name}
      identity={mcpIdentity(instance, serverSpec, endpointUrl)}
      transport={instance.transport}
      jsonSpec={
        step.kind === "needs_key" || keyFields.length > 0 ? jsonSpec : null
      }
      step={step}
      keyFields={keyFields}
      preflight={preflight}
      preflightError={
        preflightResult?.error
          ? `${t("instanceDetail.oauth.preflightFailed")}: ${preflightResult.error}`
          : null
      }
      returnPath={workspacePath(workspace, `/connect/${instance.id}`)}
    />
  );
}
