"use client";

import { useTranslations } from "next-intl";
import { ChevronRight } from "lucide-react";
import { CheckboxList } from "@/components/CheckboxList";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { scopeShortName } from "./oauth-connect-state";

/**
 * Which of a server's OAuth scopes a sign-in asks for. Folded to a count:
 * most people keep the default, and Gmail alone offers twenty.
 */
export function OAuthScopePicker({
  offered,
  selected,
  onChange,
  disabled,
}: {
  offered: string[];
  selected: string[];
  onChange: (scopes: string[]) => void;
  disabled?: boolean;
}) {
  const t = useTranslations("MCPServersPage.instanceDetail.oauth");

  return (
    <Collapsible>
      <CollapsibleTrigger className="group/scopes flex items-center gap-1 text-xs text-muted-foreground transition-colors hover:text-foreground">
        <ChevronRight
          aria-hidden="true"
          className="h-3.5 w-3.5 transition-transform duration-200 group-data-[state=open]/scopes:rotate-90 motion-reduce:transition-none"
        />
        {t("scopesSummary", { picked: selected.length, total: offered.length })}
      </CollapsibleTrigger>
      <CollapsibleContent className="aa-collapsible">
        <p className="mt-2 text-xs text-muted-foreground">{t("scopesHint")}</p>
        <CheckboxList
          className="mt-2"
          items={offered.map((scope) => {
            const name = scopeShortName(scope);
            return {
              value: scope,
              label: name,
              detail: name !== scope ? scope : undefined,
            };
          })}
          selected={selected}
          onChange={onChange}
          disabled={disabled}
        />
        {selected.length === 0 && (
          <p role="alert" className="mt-2 text-xs text-destructive">
            {t("scopesNone")}
          </p>
        )}
      </CollapsibleContent>
    </Collapsible>
  );
}
