"use client";

import { useCallback, useEffect, useRef, useState, useTransition } from "react";
import type { ReactNode } from "react";
import { useTranslations } from "next-intl";
import { useSearchParams } from "next/navigation";
import { useForm, useWatch } from "react-hook-form";
import type { McpTransport } from "@/api/client/types.gen";
import { verifyInstance } from "@/app/w/[workspace]/(main)/connections/[id]/actions";
import {
  CredentialEncryptionNote,
  CredentialFields,
} from "@/app/w/[workspace]/(main)/connections/components/CredentialFields";
import {
  credentialUpdateSpec,
  type CredentialFieldSpec,
} from "@/app/w/[workspace]/(main)/connections/credential-fields";
import type { MCPOAuthPreflight } from "@/app/w/[workspace]/(main)/connections/oauth-connect-state";
import { OAuthConnectPanel } from "@/app/w/[workspace]/(main)/connections/OAuthConnectPanel";
import { FocusCard, FocusHeader, FocusStep } from "@/components/FocusCard";
import FormError from "@/components/FormError";
import { Button } from "@/components/ui/button";
import Link from "@/components/WorkspaceLink";
import { useWorkspaceRouter } from "@/hooks/useWorkspaceNavigation";
import { apiErrorMessage, formatApiError } from "@/lib/api-errors";
import type { EntityIdentity } from "@/lib/entity-identity";
import { updateMCPServerInstanceAction } from "@/lib/server-actions";
import { stepAfterSignInError, type ConnectStep } from "./connect-step";

interface Props {
  instanceId: string;
  name: string;
  /** What the person signs in to: the server's display name. */
  provider: string;
  /** The workspace the connection is added to, so the person knows which one. */
  workspaceName: string;
  identity: EntityIdentity;
  transport: McpTransport;
  /** The instance spec, sent only when a key is to be saved into it. */
  jsonSpec: Record<string, unknown> | null;
  step: ConnectStep;
  /** The keys to ask for instead when the provider refuses the sign-in. */
  keyFields: CredentialFieldSpec[];
  /** How the provider authorizes, when the page asked it. */
  preflight: MCPOAuthPreflight | null;
  /** Why the page could not ask the provider how it authorizes. */
  preflightError: string | null;
  /** This page, for the OAuth provider to send the user back to. */
  returnPath: string;
}

export default function ConnectInstance({
  instanceId,
  name,
  provider,
  workspaceName,
  identity,
  transport,
  jsonSpec,
  step: givenStep,
  keyFields,
  preflight,
  preflightError,
  returnPath,
}: Props) {
  const t = useTranslations("MCPServersPage.connectLink");
  const tDetail = useTranslations("MCPServersPage.instanceDetail");
  const tCommon = useTranslations("Common");
  const router = useWorkspaceRouter();
  const searchParams = useSearchParams();
  const [pending, startTransition] = useTransition();
  const [error, setError] = useState<string | null>(null);
  const [keyAttempt, setKeyAttempt] = useState(0);
  // Held across the refresh that brings the server's own key step.
  const [signInError, setSignInError] = useState<string | null>(null);
  const step = stepAfterSignInError(givenStep, signInError, keyFields);
  const signInRefused =
    signInError === "oauth_app_required" && step.kind === "needs_key";
  // The callback's query is dropped from the URL right away, so the failure is
  // captured once and stays on the page.
  const [oauthError, setOauthError] = useState<string | null>(() =>
    searchParams.get("oauth") === "error"
      ? searchParams.get("reason") || "unknown"
      : null
  );

  const finish = useCallback(
    (save?: () => Promise<string | null>) => {
      setError(null);
      startTransition(async () => {
        const failure =
          (await save?.()) ??
          (await verifyConnection(instanceId, tDetail("errors.verifyFailed")));
        // A saved key is never offered back: the form starts empty again.
        startTransition(() => {
          if (save) setKeyAttempt((attempt) => attempt + 1);
          if (failure) setError(failure);
          else router.refresh();
        });
      });
    },
    [instanceId, router, tDetail]
  );

  // Back from the provider: drop the callback's query and check the new
  // credential right away instead of showing a verdict from before sign-in.
  const callbackHandled = useRef(false);
  useEffect(() => {
    const oauth = searchParams.get("oauth");
    if (!oauth || callbackHandled.current) return;
    callbackHandled.current = true;
    router.replace(`/connect/${instanceId}`, { scroll: false });
    if (oauth === "success") finish();
  }, [searchParams, instanceId, router, finish]);

  useEffect(() => {
    if (step.kind !== "verifying") return;
    const interval = setInterval(() => router.refresh(), 2000);
    return () => clearInterval(interval);
  }, [step.kind, router]);

  const saveKeys = (values: Record<string, string>) =>
    finish(async () => {
      const fallback = tDetail("errors.saveConfigFailed");
      if (!jsonSpec) return fallback;
      try {
        const result = await updateMCPServerInstanceAction(instanceId, {
          json_spec: credentialUpdateSpec(jsonSpec, transport, values),
        });
        return result.error ? apiErrorMessage(result, fallback) : null;
      } catch (err) {
        console.error("Failed to save MCP instance credentials", err);
        return `${fallback}: ${formatApiError(err)}`;
      }
    });

  const verifying =
    step.kind === "verifying" || (pending && step.kind !== "needs_key");

  let body: ReactNode;
  if (verifying) {
    body = (
      <FocusStep
        kind="running"
        title={t("verifyingTitle")}
        detail={t("verifyingDetail")}
      />
    );
  } else if (step.kind === "needs_sign_in") {
    body = (
      <div className="space-y-4">
        {step.reason && (
          <FocusStep
            kind="failed"
            title={t("failedTitle")}
            detail={step.reason}
          />
        )}
        <OAuthConnectPanel
          target={{ kind: "instance", instanceId }}
          isUrlType
          bare
          returnPath={returnPath}
          title={t("signInTitle", { provider })}
          actionLabel={t("signInButton", { provider })}
          preflight={preflight ?? undefined}
          onConnectStart={() => {
            setOauthError(null);
            setError(null);
          }}
          onAuthorizeError={(code) => {
            if (stepAfterSignInError(step, code, keyFields) === step) return;
            setSignInError(code);
            router.refresh();
          }}
        />
      </div>
    );
  } else if (step.kind === "needs_key") {
    body = (
      <KeyForm
        key={`${step.replace}-${keyAttempt}`}
        fields={step.fields}
        replace={step.replace}
        detail={signInRefused ? t("signInRefused", { provider }) : undefined}
        pending={pending}
        onSave={saveKeys}
      />
    );
  } else if (step.kind === "connected") {
    body = (
      <FocusStep
        kind="done"
        title={t("connectedTitle")}
        detail={t("connectedDetail", { name })}
      />
    );
  } else if (step.kind === "unverified") {
    body = (
      <FocusStep
        kind="draft"
        title={t("unverifiedTitle")}
        detail={t("unverifiedDetail")}
      >
        <Button size="lg" className="w-full" onClick={() => finish()}>
          {t("check")}
        </Button>
      </FocusStep>
    );
  } else {
    body = (
      <FocusStep
        kind="failed"
        title={t("failedTitle")}
        detail={step.message || t("failedDetail")}
      >
        <Button size="lg" className="w-full" onClick={() => finish()}>
          {tCommon("retry")}
        </Button>
        <Link
          href={`/connections/${instanceId}`}
          className="self-center text-xs text-primary transition-all duration-300 hover:text-accent dark:text-accent-foreground"
        >
          {t("openSettings")}
        </Link>
      </FocusStep>
    );
  }

  return (
    <FocusCard>
      <FocusHeader
        identity={identity}
        title={t("title", { provider })}
        subtitle={t("workspace", { workspace: workspaceName })}
      />
      <div className="space-y-4">
        {preflightError && <FormError>{preflightError}</FormError>}
        {oauthError && (
          <FormError>
            {tDetail("oauth.connectError", { reason: oauthError })}
          </FormError>
        )}
        {body}
        {error && <FormError>{error}</FormError>}
      </div>
      <CredentialEncryptionNote className="mt-auto border-t border-border pt-4" />
    </FocusCard>
  );
}

async function verifyConnection(
  instanceId: string,
  fallback: string
): Promise<string | null> {
  try {
    const result = await verifyInstance(instanceId);
    return result.error ? apiErrorMessage(result, fallback) : null;
  } catch (err) {
    console.error("Failed to verify MCP instance", err);
    return `${fallback}: ${formatApiError(err)}`;
  }
}

function KeyForm({
  fields,
  replace,
  detail,
  pending,
  onSave,
}: {
  fields: CredentialFieldSpec[];
  replace: boolean;
  /** Why a key is asked for, over the default line. */
  detail?: string;
  pending: boolean;
  onSave: (values: Record<string, string>) => void;
}) {
  const t = useTranslations("MCPServersPage.connectLink");
  // Keyed by position: a header name like "X-Api.Key" is not a form path.
  const { register, handleSubmit, control } = useForm<{ fields: string[] }>({
    defaultValues: { fields: fields.map(() => "") },
  });
  const values = useWatch({ control, name: "fields" });
  const complete = fields.every((_, index) => values?.[index]?.trim());

  return (
    <form
      onSubmit={handleSubmit((data) =>
        onSave(
          Object.fromEntries(
            fields.map((field, index) => [field.name, data.fields[index] ?? ""])
          )
        )
      )}
      className="space-y-4"
    >
      <FocusStep
        kind="attention"
        title={t(replace ? "replaceKeyTitle" : "keyTitle")}
        detail={detail ?? t(replace ? "replaceKeyDetail" : "keyDetail")}
      />
      <CredentialFields
        idPrefix="connect"
        fields={fields}
        bind={(_, index) => register(`fields.${index}`)}
      />
      <Button
        type="submit"
        size="lg"
        className="w-full"
        isLoading={pending}
        disabled={pending || !complete}
      >
        {t("saveAndConnect")}
      </Button>
    </form>
  );
}
