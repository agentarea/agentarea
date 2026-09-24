"use client";

import { useEffect, useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { useQueryState } from "nuqs";
import { resetCurrencyCache } from "@/hooks/useCurrency";
import type { WorkspaceInvitationPreview } from "@/lib/api";
import {
  INVITATION_QUERY_PARAM,
  type InvitationFailure,
} from "@/lib/invitations";
import {
  acceptInvitationAction,
  previewInvitationAction,
} from "@/lib/workspace-actions";

export type InvitationPreviewState =
  | { status: "loading" }
  | { status: "ready"; preview: WorkspaceInvitationPreview }
  | { status: "failed"; failure: InvitationFailure };

type ForToken<T> = { token: string; value: T };

export function useInvitationDialog() {
  const router = useRouter();
  const [token, setToken] = useQueryState(INVITATION_QUERY_PARAM);
  const [preview, setPreview] =
    useState<ForToken<InvitationPreviewState> | null>(null);
  const [acceptFailure, setAcceptFailure] =
    useState<ForToken<InvitationFailure> | null>(null);
  const [isAccepting, startAccepting] = useTransition();

  useEffect(() => {
    if (token === null) return;
    let cancelled = false;
    previewInvitationAction(token).then((result) => {
      if (cancelled) return;
      setPreview({
        token,
        value: result.ok
          ? { status: "ready", preview: result.data }
          : { status: "failed", failure: result.error },
      });
    });
    return () => {
      cancelled = true;
    };
  }, [token]);

  const state: InvitationPreviewState =
    token !== null && preview?.token === token
      ? preview.value
      : { status: "loading" };

  const dismiss = () => {
    void setToken(null);
  };

  const accept = () => {
    if (token === null) return;
    startAccepting(async () => {
      const result = await acceptInvitationAction(token);
      if (!result.ok) {
        setAcceptFailure({ token, value: result.error });
        return;
      }
      // Joining a workspace makes it the active one (see acceptInvitationAction
      // in workspace-actions.ts) — same currency-staleness risk as switching
      // workspaces in TeamSwitcher.
      resetCurrencyCache();
      router.replace("/dashboard");
      router.refresh();
    });
  };

  const currentAcceptFailure =
    acceptFailure && acceptFailure.token === token ? acceptFailure.value : null;

  return {
    open: token !== null,
    state,
    acceptFailure: currentAcceptFailure,
    // Only a failure with no known cause is worth retrying; the others are final.
    canAccept:
      state.status === "ready" &&
      (currentAcceptFailure === null ||
        currentAcceptFailure.problem === "unknown"),
    isAccepting,
    accept,
    dismiss,
  };
}
