"use client";

import { useMemo, useState } from "react";
import { Check, KeyRound, X } from "lucide-react";
import { cn } from "@/lib/utils";
import type { AccessControlRelationship } from "@/types/access-control";
import styles from "./access-control.module.css";

interface ToolGrantCardProps {
  currentUserId: string | null;
  initialRelationships: AccessControlRelationship[];
}

type GrantMode = "broad" | "exact";
type StatusKind = "info" | "allow" | "deny";

interface Status {
  kind: StatusKind;
  title: string;
  detail: string;
}

interface ToolAccessGrant {
  scope: "tool" | "arguments";
  workspace_id: string;
  user_id: string;
  tool_name: string;
  object_id: string;
  arguments_hash: string | null;
}

function formatGrant(grant: ToolAccessGrant): string {
  const scope = grant.scope === "tool" ? "whole tool" : "exact arguments";
  const hash = grant.arguments_hash ? ` · ${grant.arguments_hash.slice(0, 12)}` : "";
  return `${grant.tool_name} · ${scope}${hash} · Workspace:${grant.workspace_id} · User:${grant.user_id}`;
}

async function readErrorDetail(response: Response, fallback: string): Promise<string> {
  try {
    const payload = (await response.json()) as { detail?: unknown };
    if (typeof payload.detail === "string") {
      return payload.detail;
    }
  } catch {
    // Keep the fallback when the server returns an empty or non-JSON error body.
  }
  return fallback;
}

export default function ToolGrantCard({
  currentUserId,
  initialRelationships,
}: ToolGrantCardProps) {
  const [mode, setMode] = useState<GrantMode>("exact");
  const [userId, setUserId] = useState(currentUserId ?? "");
  const [toolName, setToolName] = useState("github.create_issue");
  const [argsText, setArgsText] = useState('{"repo":"acme/app"}');
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<Status | null>(null);

  const toolRelationships = useMemo(
    () =>
      initialRelationships.filter(
        (relationship) => relationship.namespace === "Tool" || relationship.namespace === "ToolResource"
      ),
    [initialRelationships]
  );

  function buildPayload() {
    const trimmedUserId = userId.trim();
    const trimmedToolName = toolName.trim();
    if (!trimmedUserId || !trimmedToolName) {
      throw new Error("User id and tool name are required.");
    }
    return {
      user_id: trimmedUserId,
      tool_name: trimmedToolName,
      arguments: mode === "exact" ? JSON.parse(argsText || "{}") : undefined,
    };
  }

  async function grant() {
    setBusy(true);
    setStatus(null);
    try {
      const payload = buildPayload();
      const response = await fetch("/api/proxy/v1/tool-access/grants", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!response.ok) {
        throw new Error(await readErrorDetail(response, `Grant failed (${response.status})`));
      }
      const result = (await response.json()) as { grant: ToolAccessGrant };
      setStatus({
        kind: "allow",
        title: "Grant written",
        detail: formatGrant(result.grant),
      });
    } catch (error) {
      setStatus({
        kind: "deny",
        title: "Grant failed",
        detail: error instanceof Error ? error.message : "Unknown error",
      });
    } finally {
      setBusy(false);
    }
  }

  async function check() {
    setBusy(true);
    setStatus(null);
    try {
      const payload = buildPayload();
      const response = await fetch("/api/proxy/v1/tool-access/checks", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!response.ok) {
        throw new Error(await readErrorDetail(response, `Check failed (${response.status})`));
      }
      const result = (await response.json()) as {
        allowed: boolean;
        grant: ToolAccessGrant;
      };
      setStatus({
        kind: result.allowed ? "allow" : "deny",
        title: result.allowed ? "Allowed" : "Denied",
        detail: formatGrant(result.grant),
      });
    } catch (error) {
      setStatus({
        kind: "deny",
        title: "Check failed",
        detail: error instanceof Error ? error.message : "Unknown error",
      });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className={styles.card}>
      <div className={styles.cardH}>
        <span className={styles.cardHIc}>
          <KeyRound className="h-4 w-4" />
        </span>
        <span className={styles.cardT}>Tool grants</span>
        <span className={styles.countBadge}>{toolRelationships.length}</span>
      </div>
      <div className={styles.cardB}>
        <div className={styles.modeRow}>
          <button
            type="button"
            className={cn(styles.modeBtn, mode === "exact" && styles.modeBtnOn)}
            onClick={() => setMode("exact")}
          >
            Exact args
          </button>
          <button
            type="button"
            className={cn(styles.modeBtn, mode === "broad" && styles.modeBtnOn)}
            onClick={() => setMode("broad")}
          >
            Whole tool
          </button>
        </div>

        <label className={styles.fieldLabel} htmlFor="tool-grant-user">
          User id
        </label>
        <input
          id="tool-grant-user"
          className={styles.textInput}
          value={userId}
          onChange={(event) => setUserId(event.target.value)}
          placeholder="user uuid"
        />

        <label className={styles.fieldLabel} htmlFor="tool-grant-tool">
          Tool name
        </label>
        <input
          id="tool-grant-tool"
          className={styles.textInput}
          value={toolName}
          onChange={(event) => setToolName(event.target.value)}
          placeholder="github.create_issue"
        />

        {mode === "exact" && (
          <>
            <label className={styles.fieldLabel} htmlFor="tool-grant-args">
              Arguments JSON
            </label>
            <textarea
              id="tool-grant-args"
              className={styles.textArea}
              value={argsText}
              onChange={(event) => setArgsText(event.target.value)}
              rows={4}
            />
          </>
        )}

        <div className={styles.actionRow}>
          <button
            type="button"
            className={styles.primaryAction}
            disabled={busy}
            onClick={grant}
          >
            Grant
          </button>
          <button
            type="button"
            className={styles.secondaryAction}
            disabled={busy}
            onClick={check}
          >
            Check
          </button>
        </div>

        {status && (
          <div
            className={cn(
              styles.verdict,
              status.kind === "allow" ? styles.verdictAllow : styles.verdictDeny
            )}
          >
            <span className={styles.verdictIcon}>
              {status.kind === "allow" ? (
                <Check className="h-[18px] w-[18px]" />
              ) : (
                <X className="h-[18px] w-[18px]" />
              )}
            </span>
            <div>
              <div className={styles.verdictTitle}>{status.title}</div>
              <div className={styles.verdictSub}>{status.detail}</div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
