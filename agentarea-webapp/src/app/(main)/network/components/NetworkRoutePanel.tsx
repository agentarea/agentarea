"use client";

import { useTranslations } from "next-intl";
import {
  ArrowDown,
  ArrowUpRight,
  Check,
  Globe,
  HelpCircle,
  LockKeyhole,
  Route,
  X,
} from "lucide-react";
import type { NetworkPersonAgentAccess } from "@/api/client/types.gen";
import { EntityIcon, type EntityKind } from "@/lib/entity-icons";
import type { NetworkNodeData } from "../types";
import { getNetworkScope } from "../utils/networkConnections";

export interface NetworkRoutePanelProps {
  source: { label: string; type: NetworkNodeData["type"] | "person" };
  target: NetworkNodeData;
  relation: string;
  decision?: NetworkPersonAgentAccess;
  onClose: () => void;
  onSelect: (node: NetworkNodeData) => void;
}

const kinds: Record<NetworkRoutePanelProps["source"]["type"], EntityKind> = {
  agent: "agent",
  person: "person",
  mcp_instance: "mcp",
  openapi_connection: "client",
  skill: "skill",
  trigger: "trigger",
};

export default function NetworkRoutePanel({
  source,
  target,
  relation,
  decision,
  onClose,
  onSelect,
}: NetworkRoutePanelProps) {
  const t = useTranslations("NetworkPage.routeDetails");
  const peopleText = useTranslations("NetworkPage.people");
  const accessText = useTranslations("NetworkPage.accessDetails");
  const personAccess = relation === "person_access";
  const resource = target.type !== "agent" && target.type !== "trigger";
  const scope = getNetworkScope(target);
  const ScopeIcon =
    scope === "private" ? LockKeyhole : scope === "egress" ? Globe : HelpCircle;
  const DecisionIcon = !decision
    ? HelpCircle
    : decision.allowed
      ? Check
      : LockKeyhole;

  return (
    <aside
      aria-label={t("title")}
      className="z-10 flex max-h-[45%] w-full shrink-0 flex-col overflow-hidden border-t border-border bg-background md:h-full md:max-h-none md:w-80 md:border-l md:border-t-0 xl:w-96"
    >
      <header className="flex shrink-0 items-center gap-3 border-b border-border p-4">
        <Route className="h-4 w-4 shrink-0 text-primary" />
        <h2 className="min-w-0 flex-1 text-sm font-semibold">{t("title")}</h2>
        <button
          type="button"
          aria-label={t("close")}
          onClick={onClose}
          className="rounded p-1 text-muted-foreground hover:bg-muted focus-visible:ring-2 focus-visible:ring-primary"
        >
          <X className="h-4 w-4" />
        </button>
      </header>
      <div className="flex-1 space-y-5 overflow-auto p-4">
        <div>
          <dl className="rounded-md border border-border p-3">
            <dt className="text-[11px] text-muted-foreground">{t("source")}</dt>
            <dd className="mt-1.5 flex items-start gap-2 text-xs font-medium">
              <EntityIcon
                kind={kinds[source.type]}
                className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground"
              />
              <span className="min-w-0 break-words">{source.label}</span>
            </dd>
          </dl>
          <ArrowDown
            aria-hidden="true"
            className="my-2 ml-3 h-4 w-4 text-muted-foreground"
          />
          <dl className="rounded-md border border-border p-3">
            <dt className="text-[11px] text-muted-foreground">{t("target")}</dt>
            <dd className="mt-1.5 flex items-start gap-2 text-xs font-medium">
              <EntityIcon
                kind={kinds[target.type]}
                className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground"
              />
              <span className="min-w-0 break-words">{target.label}</span>
            </dd>
          </dl>
        </div>

        <section className="space-y-2">
          <h3 className="text-xs font-semibold">{t("why")}</h3>
          <p className="text-xs leading-5 text-muted-foreground">
            {t.has(`explanation.${relation}`)
              ? t(`explanation.${relation}`)
              : t("unknownRelation")}
          </p>
          {personAccess && (
            <div className="rounded-md border border-border p-3">
              <p className="flex items-center gap-2 text-xs font-medium">
                <DecisionIcon
                  className={
                    decision?.allowed
                      ? "h-3.5 w-3.5 text-emerald-600 dark:text-emerald-400"
                      : "h-3.5 w-3.5 text-muted-foreground"
                  }
                />
                {decision
                  ? t(decision.allowed ? "allowed" : "denied")
                  : peopleText("unknown")}
              </p>
              {decision && (
                <p className="mt-2 text-[11px] leading-4 text-muted-foreground">
                  {peopleText(
                    decision.reason === "workspace scope"
                      ? "membershipReason"
                      : decision.reason === "public grant"
                        ? "publicReason"
                        : "decisionReason"
                  )}
                </p>
              )}
            </div>
          )}
        </section>

        {resource && (
          <div className="flex items-start gap-2 rounded-md bg-muted/50 p-3 text-xs">
            <ScopeIcon className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
            <div>
              <p className="font-medium">{t(`scope.${scope}`)}</p>
              <p className="mt-1 leading-4 text-muted-foreground">
                {accessText(`scopeDescription.${scope}`)}
              </p>
            </div>
          </div>
        )}

        <div className="space-y-2 text-[11px] leading-4 text-muted-foreground">
          <p>{t(personAccess ? "requestAccess" : "configured")}</p>
          <p>
            {personAccess
              ? peopleText("admissionHint")
              : accessText("configuredOnly")}
          </p>
          {personAccess && <p>{peopleText("scopeHint")}</p>}
        </div>
      </div>
      <footer className="shrink-0 border-t border-border p-4">
        <button
          type="button"
          onClick={() => onSelect(target)}
          className="inline-flex items-center gap-1.5 rounded text-xs font-medium text-primary hover:underline focus-visible:ring-2 focus-visible:ring-primary"
        >
          {t("openTarget")}
          <ArrowUpRight className="h-3.5 w-3.5" />
        </button>
      </footer>
    </aside>
  );
}
