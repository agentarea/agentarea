"use client";

import { useActionState, useState } from "react";
import { useTranslations } from "next-intl";
import FormError from "@/components/FormError";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { WorkspaceIcon } from "@/components/WorkspaceIcon";
import type { Workspace } from "@/lib/workspaces";
import { decideConsent, type ConsentState } from "./actions";
import { ConsentLabel } from "./ConsentLabel";

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
    <form action={formAction}>
      <input type="hidden" name="challenge" value={challenge} />
      {picksWorkspaces && (
        <div className="mb-4 space-y-3">
          <ConsentLabel section="workspaces">
            {t("workspaceHeading")}
          </ConsentLabel>
          {workspaces.length === 0 ? (
            <p className="text-muted-foreground text-sm">
              {t("workspaceNone")}
            </p>
          ) : (
            <ul className="space-y-1.5">
              {workspaces.map((workspace) => {
                const id = `consent-workspace-${workspace.slug}`;
                const on = picked.includes(workspace.slug);
                return (
                  <li key={workspace.slug}>
                    <label
                      htmlFor={id}
                      data-checked={on}
                      className="card-item hover:bg-muted/40 data-[checked=true]:border-primary/40 data-[checked=true]:bg-primary/[0.03] dark:data-[checked=true]:border-zinc-500 flex cursor-pointer items-center gap-3 px-3 py-2.5"
                    >
                      <WorkspaceIcon workspace={workspace} size={24} />
                      <span className="text-foreground min-w-0 flex-1 truncate text-sm font-medium">
                        {workspace.name}
                      </span>
                      <Checkbox
                        id={id}
                        checked={on}
                        onCheckedChange={(value) =>
                          setPicked((current) =>
                            value === true
                              ? [...current, workspace.slug]
                              : current.filter(
                                  (slug) => slug !== workspace.slug
                                )
                          )
                        }
                      />
                    </label>
                  </li>
                );
              })}
            </ul>
          )}
          {picked.map((slug) => (
            <input key={slug} type="hidden" name="workspaces" value={slug} />
          ))}
          <p className="note">{t("workspaceHint")}</p>
        </div>
      )}
      {state?.error && (
        <FormError className="mb-3">{t(`error.${state.error}`)}</FormError>
      )}
      {/* Allow stays first in the DOM so Enter accepts, as before; it sits on the right. */}
      <div className="grid grid-cols-2 gap-2">
        <Button
          type="submit"
          name="action"
          value="accept"
          disabled={pending || !canAllow || nonePicked}
          className="order-2 h-10 w-full rounded-md bg-[#2252b3] text-sm font-medium text-white shadow-sm hover:bg-[#1a3f8a]"
        >
          {t("allow")}
        </Button>
        <Button
          type="submit"
          name="action"
          value="reject"
          variant="outline"
          disabled={pending}
          className="order-1 h-10 w-full rounded-md text-sm font-medium"
        >
          {t("deny")}
        </Button>
      </div>
    </form>
  );
}
