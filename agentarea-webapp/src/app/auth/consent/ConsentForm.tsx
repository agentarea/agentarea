"use client";

import { useActionState, useState } from "react";
import { useTranslations } from "next-intl";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { WorkspaceIcon } from "@/components/WorkspaceIcon";
import type { Workspace } from "@/lib/workspaces";
import { decideConsent, type ConsentState } from "./actions";

export function ConsentForm({
  challenge,
  access,
  workspaces,
  canAllow,
}: {
  challenge: string;
  access: "mcp" | "api";
  workspaces: Pick<Workspace, "id" | "slug" | "name" | "logo_url">[];
  canAllow: boolean;
}) {
  const t = useTranslations("AuthConsent");
  const [state, formAction, pending] = useActionState<ConsentState, FormData>(
    decideConsent,
    null
  );
  const [picked, setPicked] = useState<string[]>(
    workspaces.length > 0 ? [workspaces[0].slug] : []
  );
  const picksWorkspaces = access === "mcp";
  const nonePicked = picksWorkspaces && picked.length === 0;

  return (
    <form action={formAction} className="flex flex-col gap-2">
      <input type="hidden" name="challenge" value={challenge} />
      {picksWorkspaces && (
        <div className="border-border/60 bg-muted/30 mb-3 rounded-lg border p-4">
          <p className="text-foreground mb-3 text-xs font-medium uppercase tracking-wider">
            {t("workspaceHeading")}
          </p>
          {workspaces.length === 0 ? (
            <p className="text-muted-foreground text-sm">
              {t("workspaceNone")}
            </p>
          ) : (
            <ul className="space-y-2.5">
              {workspaces.map((workspace) => {
                const id = `consent-workspace-${workspace.slug}`;
                return (
                  <li
                    key={workspace.slug}
                    className="flex items-center gap-2.5"
                  >
                    <Checkbox
                      id={id}
                      checked={picked.includes(workspace.slug)}
                      onCheckedChange={(on) =>
                        setPicked((current) =>
                          on === true
                            ? [...current, workspace.slug]
                            : current.filter((slug) => slug !== workspace.slug)
                        )
                      }
                    />
                    <label
                      htmlFor={id}
                      className="text-foreground flex min-w-0 items-center gap-2 text-sm"
                    >
                      <WorkspaceIcon workspace={workspace} size={20} />
                      <span className="truncate">{workspace.name}</span>
                    </label>
                  </li>
                );
              })}
            </ul>
          )}
          {picked.map((slug) => (
            <input key={slug} type="hidden" name="workspaces" value={slug} />
          ))}
          <p className="text-muted-foreground mt-3 text-xs leading-relaxed">
            {t("workspaceHint")}
          </p>
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
        disabled={pending || !canAllow || nonePicked}
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
