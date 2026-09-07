"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import Link from "next/link";
import {
  ArrowDownLeft,
  ArrowUpRight,
  ExternalLink,
  Globe,
  HelpCircle,
  LockKeyhole,
  RefreshCw,
  ShieldCheck,
  X,
} from "lucide-react";
import type { EffectivePolicy } from "@/api/client/types.gen";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import { EntityIcon, type EntityKind } from "@/lib/entity-icons";
import type { NetworkNodeData, TopologyResponse } from "../types";
import {
  getAgentConnections,
  getNetworkScope,
} from "../utils/networkConnections";

interface Props {
  node: NetworkNodeData;
  topology: TopologyResponse;
  onSelect: (node: NetworkNodeData) => void;
  onClose: () => void;
  onFocus: (agentId: string) => void;
  loadPolicy?: (agentId: string) => Promise<EffectivePolicy>;
}
const kinds: Record<NetworkNodeData["type"], EntityKind> = {
  agent: "agent",
  mcp_instance: "mcp",
  openapi_connection: "client",
  skill: "skill",
  trigger: "trigger",
};

export default function NetworkConnectionPanel({
  node,
  topology,
  onSelect,
  onClose,
  onFocus,
  loadPolicy,
}: Props) {
  const t = useTranslations("NetworkPage.accessDetails");
  const common = useTranslations("NetworkPage.orgChart");
  const [attempt, setAttempt] = useState(0);
  const [policy, setPolicy] = useState<EffectivePolicy | null>(null);
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");
  useEffect(() => {
    if (node.type !== "agent") return;
    let cancelled = false;
    setState("loading");
    setPolicy(null);
    if (!loadPolicy) {
      setState("error");
      return;
    }
    void loadPolicy(node.id)
      .then((result) => {
        if (!cancelled) {
          setPolicy(result);
          setState("ready");
        }
      })
      .catch(() => {
        if (!cancelled) setState("error");
      });
    return () => {
      cancelled = true;
    };
  }, [node.id, node.type, loadPolicy, attempt]);
  const connections = getAgentConnections(topology, node.id);
  const scope = getNetworkScope(node);
  const ScopeIcon =
    scope === "egress" ? Globe : scope === "private" ? LockKeyhole : HelpCircle;
  const allowed = policy?.tools?.allowed ?? [];
  const denied = policy?.tools?.denied ?? [];
  const approvals = policy?.approval?.escalation_rules ?? [];

  return (
    <aside
      aria-label={t("panel")}
      className="z-10 flex max-h-[45%] w-full shrink-0 flex-col overflow-hidden border-t border-border bg-background md:h-full md:max-h-none md:w-80 md:border-l md:border-t-0 xl:w-96"
    >
      <header className="flex shrink-0 items-start gap-3 border-b border-border px-4 py-4">
        <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-primary/10 text-primary">
          <EntityIcon kind={kinds[node.type]} />
        </span>
        <div className="min-w-0 flex-1">
          <p className="break-words text-sm font-semibold">{node.label}</p>
          <p className="mt-1 text-xs text-muted-foreground">
            {common(`types.${node.type}`)}
          </p>
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label={t("close")}
          className="rounded p-1 text-muted-foreground hover:bg-muted focus-visible:ring-2 focus-visible:ring-primary"
        >
          <X className="h-4 w-4" />
        </button>
      </header>
      <div className="flex-1 space-y-5 overflow-auto p-4">
        {node.type === "agent" && (
          <button
            type="button"
            onClick={() => onFocus(node.id)}
            className="flex w-full items-center justify-between rounded-md border border-border px-3 py-2 text-xs font-medium hover:bg-muted focus-visible:ring-2 focus-visible:ring-primary"
          >
            {t("showPath")}
            <ArrowUpRight className="h-3.5 w-3.5" />
          </button>
        )}
        {node.type !== "agent" && node.type !== "trigger" && (
          <div className="flex items-center gap-2 rounded-md bg-muted/50 p-3 text-xs">
            <ScopeIcon className="h-4 w-4 shrink-0 text-muted-foreground" />
            <div>
              <p className="font-medium">{t(`scope.${scope}`)}</p>
              <p className="mt-1 text-muted-foreground">
                {t(`scopeDescription.${scope}`)}
              </p>
            </div>
          </div>
        )}

        {node.type === "agent" && (
          <section className="space-y-3">
            <div className="flex items-center justify-between gap-2">
              <p className="flex items-center gap-2 text-xs font-semibold">
                <ShieldCheck className="h-3.5 w-3.5" />
                {t("policyTitle")}
              </p>
              <button
                type="button"
                aria-label={t("refresh")}
                onClick={() => setAttempt((value) => value + 1)}
                disabled={state === "loading"}
                className="rounded p-1 text-muted-foreground hover:bg-muted focus-visible:ring-2 focus-visible:ring-primary disabled:opacity-50"
              >
                <RefreshCw className="h-3.5 w-3.5" />
              </button>
            </div>
            <p className="text-[11px] leading-4 text-muted-foreground">
              {t("policyScope")}
            </p>
            {state === "loading" && (
              <div
                className="flex items-center gap-2 py-2 text-xs text-muted-foreground"
                role="status"
              >
                <LoadingSpinner />
                {t("loading")}
              </div>
            )}
            {state === "error" && (
              <div className="rounded-md border border-border p-3 text-xs">
                <p>{t("unavailable")}</p>
                <button
                  type="button"
                  onClick={() => setAttempt((value) => value + 1)}
                  className="mt-2 rounded text-primary underline underline-offset-4 focus-visible:ring-2 focus-visible:ring-primary"
                >
                  {t("retry")}
                </button>
              </div>
            )}
            {state === "ready" && policy && (
              <>
                <RuleList
                  title={t("denied")}
                  items={denied}
                  empty={t("noDenyRules")}
                  tone="text-red-600 dark:text-red-400"
                />
                <RuleList
                  title={t("allowlist")}
                  items={allowed}
                  empty={t("noAllowlist")}
                  tone="text-foreground"
                />
                <RuleList
                  title={t("approval")}
                  items={
                    policy.approval?.requires_human_approval
                      ? [t("allCalls")]
                      : approvals
                  }
                  empty={t("noApproval")}
                  tone="text-amber-700 dark:text-amber-400"
                />
                <p className="text-[11px] leading-4 text-muted-foreground">
                  {t("precedence")}
                </p>
                <p className="text-[11px] text-muted-foreground">
                  {t("sources", {
                    count: policy.source_policy_ids?.length ?? 0,
                  })}
                </p>
              </>
            )}
            <p className="text-[11px] leading-4 text-muted-foreground">
              {t("previewLimit")}
            </p>
            <Link
              href="/policies"
              className="inline-flex items-center gap-1.5 text-xs font-medium text-primary hover:underline"
            >
              {t("openPolicies")}
              <ExternalLink className="h-3 w-3" />
            </Link>
          </section>
        )}
        <section className="space-y-3">
          <div>
            <p className="text-xs font-semibold">{t("connections")}</p>
            <p className="mt-1 text-[11px] leading-4 text-muted-foreground">
              {t("configuredOnly")}
            </p>
          </div>
          {[
            {
              key: "incoming" as const,
              items: connections.incoming,
              Icon: ArrowDownLeft,
            },
            {
              key: "outgoing" as const,
              items: connections.outgoing,
              Icon: ArrowUpRight,
            },
          ].map(({ key, items, Icon }) => (
            <div key={key}>
              <p className="mb-1.5 flex items-center gap-1.5 text-[11px] font-medium text-muted-foreground">
                <Icon className="h-3.5 w-3.5" />
                {t(key)}
                <span className="ml-auto tabular-nums">{items.length}</span>
              </p>
              {items.length === 0 ? (
                <p className="text-[11px] text-muted-foreground">
                  {t("noConnections")}
                </p>
              ) : (
                <div className="space-y-1">
                  {items.map(({ edge, node: other }) => (
                    <button
                      type="button"
                      key={edge.id}
                      onClick={() => onSelect(other)}
                      className="flex w-full items-center gap-2 rounded-md border border-border px-2.5 py-2 text-left hover:bg-muted focus-visible:ring-2 focus-visible:ring-primary"
                    >
                      <EntityIcon
                        kind={kinds[other.type]}
                        className="h-3.5 w-3.5 shrink-0 text-muted-foreground"
                      />
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-xs font-medium">
                          {other.label}
                        </span>
                        <span className="mt-0.5 block text-[10px] text-muted-foreground">
                          {common.has(`relations.${edge.relation}`)
                            ? common(`relations.${edge.relation}`)
                            : edge.relation}
                        </span>
                      </span>
                      {other.type !== "agent" && other.type !== "trigger" && (
                        <span className="text-[10px] text-muted-foreground">
                          {t(`scope.${getNetworkScope(other)}`)}
                        </span>
                      )}
                    </button>
                  ))}
                </div>
              )}
            </div>
          ))}
        </section>
      </div>
    </aside>
  );
}

function RuleList({
  title,
  items,
  empty,
  tone,
}: {
  title: string;
  items: string[];
  empty: string;
  tone: string;
}) {
  return (
    <div>
      <p className={`text-[11px] font-semibold ${tone}`}>{title}</p>
      {items.length ? (
        <ul className="mt-1.5 flex flex-wrap gap-1">
          {items.map((item) => (
            <li
              key={item}
              className={`max-w-full break-all rounded border border-border bg-muted/30 px-1.5 py-1 font-mono text-[10px] ${tone}`}
            >
              {item}
            </li>
          ))}
        </ul>
      ) : (
        <p className="mt-1 text-[11px] leading-4 text-muted-foreground">
          {empty}
        </p>
      )}
    </div>
  );
}
