"use client";

import type { ReactNode } from "react";
import { useFormatter, useTranslations } from "next-intl";
import { Clock, Loader2 } from "lucide-react";
import FormError from "@/components/FormError";
import {
  BlueprintDivider,
  BlueprintSheet,
} from "@/components/ui/blueprint-sheet";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { inviterLabel, type InvitationFailure } from "@/lib/invitations";
import { useInvitationDialog } from "./useInvitationDialog";

const emphasis = (chunks: ReactNode) => (
  <span className="font-medium text-foreground">{chunks}</span>
);

function FailureMessage({ failure }: { failure: InvitationFailure }) {
  const t = useTranslations("InvitationDialog");
  return (
    <FormError>
      {t(`problem.${failure.problem}`, { message: failure.message })}
    </FormError>
  );
}

export default function InvitationDialog() {
  const t = useTranslations("InvitationDialog");
  const format = useFormatter();
  const {
    open,
    state,
    acceptFailure,
    canAccept,
    isAccepting,
    accept,
    dismiss,
  } = useInvitationDialog();

  const preview = state.status === "ready" ? state.preview : null;
  const inviter = preview ? inviterLabel(preview) : null;

  return (
    <Dialog open={open} onOpenChange={(next) => !next && dismiss()}>
      <DialogContent className="min-w-0 max-h-[calc(100dvh-2rem)] w-[calc(100vw-2rem)] gap-0 overflow-y-auto p-0 sm:max-w-[496px] sm:rounded-[10px]">
        <DialogHeader className="space-y-1.5 px-6 pb-4 pt-5">
          <DialogTitle>
            {preview
              ? t("joinTitle", { workspace: preview.workspace_name })
              : state.status === "failed"
                ? t("unavailableTitle")
                : t("title")}
          </DialogTitle>
          <DialogDescription className={preview ? undefined : "sr-only"}>
            {preview
              ? inviter
                ? t.rich("invitedBy", {
                    inviter,
                    workspace: preview.workspace_name,
                    b: emphasis,
                  })
                : t.rich("invitedByUnknown", {
                    workspace: preview.workspace_name,
                    b: emphasis,
                  })
              : state.status === "loading"
                ? t("loading")
                : t("title")}
          </DialogDescription>
        </DialogHeader>

        <BlueprintSheet className="min-w-0" style={{ paddingBottom: 0 }}>
          <BlueprintDivider />
          <div className="relative z-[1] min-w-0 space-y-4 px-4 py-5">
            {state.status === "loading" && (
              <div className="space-y-2" aria-busy="true">
                <Skeleton className="h-4 w-3/4" />
                <Skeleton className="h-4 w-1/2" />
              </div>
            )}
            {state.status === "failed" && (
              <FailureMessage failure={state.failure} />
            )}
            {preview && (
              <p className="flex items-center gap-1.5 text-sm text-muted-foreground">
                <Clock className="h-3.5 w-3.5 shrink-0" />
                {t("expires", {
                  date: format.dateTime(new Date(preview.expires_at), {
                    dateStyle: "medium",
                  }),
                })}
              </p>
            )}
            {acceptFailure && <FailureMessage failure={acceptFailure} />}
          </div>
          <BlueprintDivider />
        </BlueprintSheet>

        <DialogFooter className="gap-2 px-6 py-4">
          {preview ? (
            <>
              <Button
                size="sm"
                variant="outline"
                onClick={dismiss}
                disabled={isAccepting}
              >
                {t("decline")}
              </Button>
              {canAccept && (
                <Button size="sm" onClick={accept} disabled={isAccepting}>
                  {isAccepting && <Loader2 className="animate-spin" />}
                  {t("accept")}
                </Button>
              )}
            </>
          ) : (
            <Button size="sm" variant="outline" onClick={dismiss}>
              {t("close")}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
