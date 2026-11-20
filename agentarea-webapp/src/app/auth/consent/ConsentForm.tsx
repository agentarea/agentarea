"use client";

import { useActionState } from "react";
import { useTranslations } from "next-intl";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { decideConsent, type ConsentState } from "./actions";

export function ConsentForm({
  challenge,
  access,
  workspaces,
  canAllow,
}: {
  challenge: string;
  access: "mcp" | "api";
  workspaces: { slug: string; name: string }[];
  canAllow: boolean;
}) {
  const t = useTranslations("AuthConsent");
  const [state, formAction, pending] = useActionState<ConsentState, FormData>(
    decideConsent,
    null
  );
  const picksWorkspace = access === "mcp";
  const noWorkspace = picksWorkspace && workspaces.length === 0;

  return (
    <form action={formAction} className="flex flex-col gap-2">
      <input type="hidden" name="challenge" value={challenge} />
      {picksWorkspace && (
        <div className="mb-3">
          <p className="text-foreground mb-2 text-xs font-medium uppercase tracking-wider">
            {t("workspaceHeading")}
          </p>
          {noWorkspace ? (
            <p className="text-muted-foreground text-sm">{t("workspaceNone")}</p>
          ) : (
            <Select name="workspace" defaultValue={workspaces[0].slug}>
              <SelectTrigger className="h-11 w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {workspaces.map((workspace) => (
                  <SelectItem key={workspace.slug} value={workspace.slug}>
                    {workspace.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          )}
        </div>
      )}
      {state?.error && (
        <div className="text-destructive border-destructive/30 bg-destructive/5 mb-3 rounded-md border px-3 py-2 text-sm">
          {t(`error.${state.error}`)}
        </div>
      )}
      <Button
        type="submit"
        name="action"
        value="accept"
        disabled={pending || !canAllow || noWorkspace}
        className="h-11 w-full rounded-md bg-[#2252b3] text-sm font-medium text-white shadow-sm hover:bg-[#1a3f8a]"
      >
        {t("allow")}
      </Button>
      <Button
        type="submit"
        name="action"
        value="reject"
        variant="outline"
        disabled={pending}
        className="h-11 w-full rounded-md text-sm font-medium"
      >
        {t("deny")}
      </Button>
    </form>
  );
}
