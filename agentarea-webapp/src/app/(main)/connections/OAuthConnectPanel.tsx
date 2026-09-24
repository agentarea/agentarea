"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { AlertTriangle, BadgeCheck, ExternalLink, Loader2 } from "lucide-react";

import { CustomOAuthAppFields } from "@/components/CustomOAuthAppFields";
import { Button } from "@/components/ui/button";
import type { CustomOAuthAppCredentials } from "@/lib/oauth-app";
import { isSafeRedirectUrl } from "@/lib/safe-redirect";
import {
  listWorkspaceSecretsAction,
  mcpOAuthPreflightAction,
  oauthAuthorizeAction,
} from "@/lib/server-actions";

import {
  buildAuthorizeRequest,
  deriveOAuthConnectState,
  type MCPOAuthPreflight,
  type OAuthConnectState,
} from "./oauth-connect-state";

/**
 * The single place a remote MCP connection is authorized from.
 *
 * It asks the API what is possible before rendering anything: a provider
 * without dynamic client registration gets a client ID/secret form, a provider
 * with no OAuth at all gets an explanation, and only a provider that can
 * actually complete the flow gets a bare Connect button.
 */
export function OAuthConnectPanel({
  instanceId,
  isUrlType,
  onStateChange,
  compact,
}: {
  instanceId: string;
  isUrlType: boolean;
  /** Lets the page describe the connection ("reachable, not authorized"). */
  onStateChange?: (state: OAuthConnectState) => void;
  compact?: boolean;
}) {
  const t = useTranslations("MCPServersPage.instanceDetail.oauth");
  const [preflight, setPreflight] = useState<MCPOAuthPreflight | null>(null);
  const [preflightError, setPreflightError] = useState<string | null>(null);
  const [credentials, setCredentials] =
    useState<CustomOAuthAppCredentials | null>(null);
  const [isConnecting, setIsConnecting] = useState(false);
  const [connectError, setConnectError] = useState<string | null>(null);

  useEffect(() => {
    if (!isUrlType) return;
    let active = true;
    mcpOAuthPreflightAction(instanceId).then(({ data, error }) => {
      if (!active) return;
      if (error || !data) {
        setPreflightError(error || t("preflightFailed"));
        return;
      }
      setPreflight(data as MCPOAuthPreflight);
    });
    return () => {
      active = false;
    };
  }, [instanceId, isUrlType, t]);

  const state = deriveOAuthConnectState({
    isUrlType,
    preflight,
    error: preflightError,
  });

  const onStateChangeRef = useRef(onStateChange);
  onStateChangeRef.current = onStateChange;
  useEffect(() => {
    onStateChangeRef.current?.(
      deriveOAuthConnectState({ isUrlType, preflight, error: preflightError })
    );
  }, [isUrlType, preflight, preflightError]);

  const handleConnect = useCallback(async () => {
    const request = buildAuthorizeRequest({
      instanceId,
      state,
      credentials,
      returnTo: window.location.origin,
    });
    if (!request) return;

    setIsConnecting(true);
    setConnectError(null);
    try {
      const { data, error } = await oauthAuthorizeAction(request);
      if (
        error ||
        !data?.authorize_url ||
        !isSafeRedirectUrl(data.authorize_url)
      ) {
        setConnectError(error || t("startFailed"));
        return;
      }
      window.location.href = data.authorize_url;
    } catch (error) {
      setConnectError(error instanceof Error ? error.message : t("startFailed"));
    } finally {
      setIsConnecting(false);
    }
  }, [credentials, instanceId, state, t]);

  if (state.kind === "hidden") return null;

  if (state.kind === "loading") {
    return (
      <Row>
        <Loader2 className="mt-0.5 h-4 w-4 shrink-0 animate-spin text-muted-foreground" />
        <div className="min-w-0">
          <p className="text-sm font-medium">{t("checkingTitle")}</p>
          <p className="text-xs text-muted-foreground">{t("checkingDetail")}</p>
        </div>
      </Row>
    );
  }

  if (state.kind === "unsupported") {
    return (
      <Row>
        <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
        <div className="min-w-0">
          <p className="text-sm font-medium">{t("unsupportedTitle")}</p>
          <p className="text-xs text-muted-foreground">{state.reason}</p>
        </div>
      </Row>
    );
  }

  const connectLabel = state.connected ? t("reconnect") : t("connect");
  const canConnect = Boolean(
    buildAuthorizeRequest({ instanceId, state, credentials })
  );

  if (state.kind === "ready") {
    return (
      <div className="space-y-2">
        <Row>
          {state.connected ? (
            <BadgeCheck className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
          ) : (
            <ExternalLink className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
          )}
          <div className="min-w-0 flex-1">
            <p className="text-sm font-medium">
              {state.connected ? t("authorizedTitle") : t("readyTitle")}
            </p>
            <p className="text-xs text-muted-foreground">
              {state.connected ? t("authorizedDetail") : t("readyDetail")}
            </p>
          </div>
          <Button
            size={compact ? "xs" : "sm"}
            variant={state.connected ? "outline" : "default"}
            onClick={handleConnect}
            isLoading={isConnecting}
            disabled={isConnecting}
          >
            {connectLabel}
          </Button>
        </Row>
        {connectError && <ErrorLine message={connectError} />}
      </div>
    );
  }

  return (
    <div className="space-y-3 rounded-lg border border-border/60 bg-muted/30 px-3 py-3">
      <div className="flex items-start gap-2">
        <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
        <div className="min-w-0">
          <p className="text-sm font-medium">
            {state.connected
              ? t("needsAppTitleConnected")
              : t("needsAppTitle")}
          </p>
          <p className="text-xs text-muted-foreground">{state.reason}</p>
        </div>
      </div>
      <CustomOAuthAppFields
        loadSecrets={listWorkspaceSecretsAction}
        onChange={setCredentials}
        disabled={isConnecting}
      />
      <div className="flex items-center gap-2">
        <Button
          size={compact ? "xs" : "sm"}
          onClick={handleConnect}
          isLoading={isConnecting}
          disabled={isConnecting || !canConnect}
        >
          {connectLabel}
        </Button>
        {!canConnect && (
          <span className="text-xs text-muted-foreground">
            {t("needsAppHint")}
          </span>
        )}
      </div>
      {connectError && <ErrorLine message={connectError} />}
    </div>
  );
}

function Row({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex items-start gap-2 rounded-lg border border-border/60 bg-muted/30 px-3 py-2.5">
      {children}
    </div>
  );
}

function ErrorLine({ message }: { message: string }) {
  return (
    <p role="alert" className="text-xs text-destructive">
      {message}
    </p>
  );
}
