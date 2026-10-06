"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";

import { CustomOAuthAppFields } from "@/components/CustomOAuthAppFields";
import { Button } from "@/components/ui/button";
import { StatusIndicator } from "@/components/ui/status-indicator";
import { CopyableText } from "@/components/ui/copyable-text";
import { apiErrorMessage } from "@/lib/api-errors";
import type { CustomOAuthAppCredentials } from "@/lib/oauth-app";
import { isSafeRedirectUrl } from "@/lib/safe-redirect";
import {
  listWorkspaceSecretsAction,
  mcpOAuthPreflightAction,
  oauthAuthorizeAction,
} from "@/lib/server-actions";

import {
  catalogConnectionPreflightAction,
  connectCatalogConnectionAction,
} from "../bundles/components/actions";
import {
  buildAuthorizeRequest,
  buildCatalogConnectRequest,
  canAuthorize,
  catalogPreflightToMCP,
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
/**
 * What is being authorized: an existing connection, a catalog spec whose
 * connection is created only once the user commits to Connect, or a catalog
 * HTTP API template the API materializes on Connect.
 */
export type OAuthConnectTarget =
  | { kind: "instance"; instanceId: string }
  | { kind: "spec"; serverId: string; ensureInstance: () => Promise<string> }
  | { kind: "catalog"; itemId: string };

export function OAuthConnectPanel({
  target,
  isUrlType,
  onStateChange,
  onConnectStart,
  compact,
  bare,
  returnPath,
  title,
  actionLabel,
  onAuthorizeError,
  preflight: givenPreflight,
}: {
  target: OAuthConnectTarget;
  isUrlType: boolean;
  /** Lets the page describe the connection ("reachable, not authorized"). */
  onStateChange?: (state: OAuthConnectState) => void;
  /** A new attempt supersedes the page's report of the previous one. */
  onConnectStart?: () => void;
  compact?: boolean;
  /** Inside a surface that already frames it: no box of its own, full-width action. */
  bare?: boolean;
  /** Page on this origin the provider sends the user back to; default: origin. */
  returnPath?: string;
  /** Heading of the sign-in step before it is authorized; default: generic. */
  title?: string;
  /** The action before it is authorized; default: "Connect with OAuth". */
  actionLabel?: string;
  /** Authorization could not start; `code` is the API's problem code. */
  onAuthorizeError?: (code: string | null) => void;
  /** The page already asked the API; the panel then does not ask again. */
  preflight?: MCPOAuthPreflight;
}) {
  const t = useTranslations("MCPServersPage.instanceDetail.oauth");
  const [fetchedPreflight, setPreflight] = useState<MCPOAuthPreflight | null>(
    null
  );
  const preflight = givenPreflight ?? fetchedPreflight;
  const hasGivenPreflight = givenPreflight !== undefined;
  const [preflightError, setPreflightError] = useState<string | null>(null);
  const [credentials, setCredentials] =
    useState<CustomOAuthAppCredentials | null>(null);
  const [isConnecting, setIsConnecting] = useState(false);
  const [connectError, setConnectError] = useState<string | null>(null);
  const targetKind = target.kind;
  const targetKey =
    target.kind === "instance"
      ? target.instanceId
      : target.kind === "catalog"
        ? target.itemId
        : target.serverId;

  useEffect(() => {
    if (!isUrlType || hasGivenPreflight) return;
    let active = true;
    if (targetKind === "catalog") {
      catalogConnectionPreflightAction(targetKey).then((result) => {
        if (!active) return;
        if (result.error || !result.data) {
          setPreflightError(apiErrorMessage(result, t("preflightFailed")));
          return;
        }
        setPreflight(catalogPreflightToMCP(result.data));
      });
      return () => {
        active = false;
      };
    }
    mcpOAuthPreflightAction(
      targetKind === "instance"
        ? { instance_id: targetKey }
        : { server_id: targetKey }
    ).then(({ data, error }) => {
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
  }, [targetKind, targetKey, isUrlType, hasGivenPreflight, t]);

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
    if (!canAuthorize({ state, credentials })) return;

    setIsConnecting(true);
    setConnectError(null);
    onConnectStart?.();
    const returnTo = `${window.location.origin}${returnPath ?? ""}`;
    try {
      let authorizeUrl: string;
      if (target.kind === "catalog") {
        const request = buildCatalogConnectRequest({
          state,
          credentials,
          returnTo,
        });
        if (!request) return;
        const result = await connectCatalogConnectionAction(
          target.itemId,
          request
        );
        if (result.error || !result.data) {
          setConnectError(apiErrorMessage(result, t("startFailed")));
          return;
        }
        authorizeUrl = result.data.authorize_url;
      } else {
        const instanceId =
          target.kind === "instance"
            ? target.instanceId
            : await target.ensureInstance();
        const request = buildAuthorizeRequest({
          instanceId,
          state,
          credentials,
          returnTo,
        });
        if (!request) return;
        const { data, error, code } = await oauthAuthorizeAction(request);
        if (error || !data?.authorize_url) {
          setConnectError(error || t("startFailed"));
          onAuthorizeError?.(code);
          return;
        }
        authorizeUrl = data.authorize_url;
      }
      if (!isSafeRedirectUrl(authorizeUrl)) {
        setConnectError(t("startFailed"));
        return;
      }
      window.location.href = authorizeUrl;
    } catch (error) {
      setConnectError(error instanceof Error ? error.message : t("startFailed"));
    } finally {
      setIsConnecting(false);
    }
  }, [
    credentials,
    state,
    t,
    target,
    onConnectStart,
    onAuthorizeError,
    returnPath,
  ]);

  if (state.kind === "hidden") return null;

  if (state.kind === "loading") {
    return (
      <Row bare={bare}>
        <StatusIndicator
          kind="running"
          size="sm"
          className="mt-0.5 shrink-0"
          iconClassName="h-4 w-4"
          aria-label={t("checkingTitle")}
          title={t("checkingTitle")}
        />
        <div className="min-w-0">
          <p className="text-sm font-medium">{t("checkingTitle")}</p>
          <p className="text-xs text-muted-foreground">{t("checkingDetail")}</p>
        </div>
      </Row>
    );
  }

  if (state.kind === "unsupported") {
    return (
      <Row bare={bare}>
        <StatusIndicator
          kind="attention"
          size="sm"
          className="mt-0.5 shrink-0"
          aria-label={state.reason}
          title={state.reason}
        />
        <div className="min-w-0">
          <p className="text-sm font-medium">{t("unsupportedTitle")}</p>
          <p className="text-xs text-muted-foreground">{state.reason}</p>
        </div>
      </Row>
    );
  }

  const connectLabel = state.connected
    ? t("reconnect")
    : (actionLabel ?? t("connect"));
  const canConnect = canAuthorize({ state, credentials });
  const buttonSize = bare ? "lg" : compact ? "xs" : "sm";

  if (state.kind === "ready") {
    const button = (
      <Button
        size={buttonSize}
        variant={state.connected ? "outline" : "default"}
        className={bare ? "w-full" : undefined}
        onClick={handleConnect}
        isLoading={isConnecting}
        disabled={isConnecting}
      >
        {connectLabel}
      </Button>
    );
    return (
      <div className={bare ? "space-y-4" : "space-y-2"}>
        <Row bare={bare}>
          {state.connected ? (
            <StatusIndicator
              kind="active"
              size="sm"
              className="mt-0.5 shrink-0"
              iconClassName="h-4 w-4"
              aria-label={t("authorizedTitle")}
              title={t("authorizedTitle")}
            />
          ) : (
            <StatusIndicator
              kind="draft"
              size="sm"
              className="mt-0.5 shrink-0"
              iconClassName="h-4 w-4"
              aria-label={title ?? t("readyTitle")}
              title={title ?? t("readyTitle")}
            />
          )}
          <div className="min-w-0 flex-1">
            <p className="text-sm font-medium">
              {state.connected
                ? t("authorizedTitle")
                : (title ?? t("readyTitle"))}
            </p>
            <p className="text-xs text-muted-foreground">
              {state.connected ? t("authorizedDetail") : t("readyDetail")}
            </p>
          </div>
          {!bare && button}
        </Row>
        {bare && button}
        {connectError && <ErrorLine message={connectError} />}
      </div>
    );
  }

  return (
    <div
      className={
        bare
          ? "space-y-3"
          : "space-y-3 rounded-lg border border-border/60 bg-muted/30 px-3 py-3"
      }
    >
      <div className="flex items-start gap-2">
        <StatusIndicator
          kind="attention"
          size="sm"
          className="mt-0.5 shrink-0"
          aria-label={state.reason}
          title={state.reason}
        />
        <div className="min-w-0">
          <p className="text-sm font-medium">
            {state.connected
              ? t("needsAppTitleConnected")
              : t("needsAppTitle")}
          </p>
          <p className="text-xs text-muted-foreground">{state.reason}</p>
        </div>
      </div>
      {state.redirectUri && (
        <div className="space-y-1">
          <p className="text-xs font-medium">{t("redirectUriLabel")}</p>
          <CopyableText text={state.redirectUri} />
        </div>
      )}
      <CustomOAuthAppFields
        loadSecrets={listWorkspaceSecretsAction}
        onChange={setCredentials}
        disabled={isConnecting}
      />
      <div
        className={
          bare ? "flex flex-col gap-2" : "flex items-center gap-2"
        }
      >
        <Button
          size={buttonSize}
          className={bare ? "w-full" : undefined}
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

function Row({
  bare,
  children,
}: {
  bare?: boolean;
  children: React.ReactNode;
}) {
  return (
    <div
      className={
        bare
          ? "flex items-start gap-2"
          : "flex items-start gap-2 rounded-lg border border-border/60 bg-muted/30 px-3 py-2.5"
      }
    >
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
