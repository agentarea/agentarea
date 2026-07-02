"use client";

import { useEffect, useRef, useState } from "react";
import { AlertTriangle, Loader2, XCircle } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { getMCPServerInstance, deleteMCPServerInstance } from "@/lib/api";

const POLL_INTERVAL_MS = 2000;
const TIMEOUT_MS = 90_000;

interface VerifyingModalProps {
  instanceId: string;
  instanceName: string;
  onSuccess: (instanceId: string) => void;
  onDelete: () => void;
  onEditRetry: (instanceId: string) => void;
}

export function VerifyingModal({
  instanceId,
  instanceName,
  onSuccess,
  onDelete,
  onEditRetry,
}: VerifyingModalProps) {
  const [phase, setPhase] = useState<"verifying" | "timeout" | "failed">("verifying");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [errorCode, setErrorCode] = useState<string | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);
  const startedAt = useRef(Date.now());
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    let cancelled = false;

    const poll = async () => {
      if (cancelled) return;
      const elapsed = Date.now() - startedAt.current;
      if (elapsed >= TIMEOUT_MS) {
        setPhase("timeout");
        return;
      }

      try {
        const { data } = await getMCPServerInstance(instanceId);
        if (!data || cancelled) return;

        const verification = (data as any).verification as {
          status: string;
          error?: { message: string; code?: string | null } | null;
        } | null | undefined;

        if (verification?.status === "succeeded") {
          clearInterval(timerRef.current!);
          onSuccess(instanceId);
        } else if (verification?.status === "failed") {
          clearInterval(timerRef.current!);
          setErrorMessage(verification.error?.message ?? "Verification failed");
          setErrorCode(verification.error?.code ?? null);
          setPhase("failed");
        }
      } catch {
        // network hiccup — keep polling
      }
    };

    timerRef.current = setInterval(poll, POLL_INTERVAL_MS);
    poll();

    return () => {
      cancelled = true;
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, [instanceId, onSuccess]);

  const handleDelete = async () => {
    setIsDeleting(true);
    try {
      await deleteMCPServerInstance(instanceId);
      onDelete();
    } catch {
      setIsDeleting(false);
    }
  };

  return (
    <Dialog open>
      <DialogContent className="max-w-md" onInteractOutside={(e) => e.preventDefault()}>
        <DialogHeader>
          <DialogTitle>
            {phase === "verifying" && `Verifying ${instanceName}`}
            {phase === "timeout" && "Still working…"}
            {phase === "failed" && "Verification failed"}
          </DialogTitle>
          <DialogDescription>
            {phase === "verifying" && "This can take up to 90s on first pull."}
            {phase === "timeout" && "Taking longer than expected. You can close this and check back later."}
            {phase === "failed" && "The server could not be reached or configured."}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          {phase === "verifying" && (
            <div aria-live="polite" className="flex items-center gap-3 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin shrink-0" />
              <span>Connecting to {instanceName}…</span>
            </div>
          )}

          {phase === "timeout" && (
            <div aria-live="polite" className="flex items-center gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800 dark:border-amber-900/50 dark:bg-amber-950/30 dark:text-amber-300">
              <AlertTriangle className="h-4 w-4 shrink-0" />
              <span>Verification is still running in the background.</span>
            </div>
          )}

          {phase === "failed" && (
            <div role="alert" className="space-y-2 rounded-lg border border-destructive/30 bg-destructive/5 px-3 py-2">
              <div className="flex items-center gap-2 text-sm font-medium text-destructive">
                <XCircle className="h-4 w-4 shrink-0" />
                <span>{errorMessage}</span>
              </div>
              {errorCode && (
                <p className="font-mono text-xs text-destructive/60">Code: {errorCode}</p>
              )}
            </div>
          )}

          <div className="flex gap-2 justify-end pt-1">
            {phase === "timeout" && (
              <Button variant="outline" onClick={onDelete}>
                Close
              </Button>
            )}
            {phase === "failed" && (
              <>
                <Button
                  variant="outline"
                  onClick={() => onEditRetry(instanceId)}
                >
                  Edit &amp; Retry
                </Button>
                <Button
                  variant="destructive"
                  onClick={handleDelete}
                  isLoading={isDeleting}
                  disabled={isDeleting}
                >
                  Delete
                </Button>
              </>
            )}
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
