"use client";

import { useTranslations } from "next-intl";
import Link from "next/link";
import { Check, HelpCircle, LockKeyhole, X } from "lucide-react";
import type { NetworkPeopleAccessResponse } from "@/api/client/types.gen";
import { EntityIcon } from "@/lib/entity-icons";
import type { NetworkNodeData, TopologyResponse } from "../types";
import type { PeopleStatus } from "./NetworkPeopleNode";

interface Props {
  data: NetworkPeopleAccessResponse | null;
  status: PeopleStatus;
  selectedId: string | null;
  topology: TopologyResponse;
  onSelect: (id: string) => void;
  onAgentSelect: (agent: NetworkNodeData) => void;
  onClose: () => void;
  onRetry: () => void;
}
export default function NetworkPeoplePanel({
  data,
  status,
  selectedId,
  topology,
  onSelect,
  onAgentSelect,
  onClose,
  onRetry,
}: Props) {
  const t = useTranslations("NetworkPage.people");
  const person = data?.people.find((person) => person.user_id === selectedId);
  const decisions = new Map(
    data?.access
      .filter((item) => item.user_id === selectedId)
      .map((item) => [item.agent_id, item])
  );
  return (
    <aside
      aria-label={t("panel")}
      className="z-10 flex max-h-[45%] w-full shrink-0 flex-col overflow-hidden border-t border-border bg-background md:h-full md:max-h-none md:w-80 md:border-l md:border-t-0 xl:w-96"
    >
      <header className="flex items-center gap-2 border-b border-border p-4">
        <EntityIcon kind="person" className="h-4 w-4 text-primary" />
        <p className="flex-1 text-sm font-semibold">{t("panel")}</p>
        <button
          type="button"
          aria-label={t("close")}
          onClick={onClose}
          className="rounded p-1 text-muted-foreground hover:bg-muted focus-visible:ring-2 focus-visible:ring-primary"
        >
          <X className="h-4 w-4" />
        </button>
      </header>
      <div className="flex-1 space-y-4 overflow-auto p-4">
        {status === "loading" && (
          <p className="text-xs text-muted-foreground" role="status">
            {t("loading")}
          </p>
        )}
        {status === "error" && (
          <div role="alert">
            <p className="text-xs leading-5 text-muted-foreground">
              {t("unavailable")}
            </p>
            <button
              type="button"
              onClick={onRetry}
              className="mt-2 rounded text-xs text-primary underline focus-visible:ring-2 focus-visible:ring-primary"
            >
              {t("retry")}
            </button>
          </div>
        )}
        {status === "ready" && data && (
          <>
            {data.directory_status === "disabled" && (
              <p className="text-xs leading-5 text-muted-foreground">
                {t("directoryDisabled")}
              </p>
            )}
            {data.directory_status !== "disabled" && !data.complete && (
              <p className="text-xs leading-5 text-muted-foreground">
                {t("partial")}
              </p>
            )}
            <label className="block text-xs font-medium">
              {t("selectPerson")}
              <select
                aria-label={t("selectPerson")}
                value={person?.user_id ?? ""}
                disabled={data.people.length === 0}
                onChange={(event) => onSelect(event.target.value)}
                className="mt-2 h-9 w-full rounded-md border border-border bg-background px-2 text-xs focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
              >
                <option value="" disabled>
                  {t("choose")}
                </option>
                {data.people.map((person) => (
                  <option key={person.user_id} value={person.user_id}>
                    {person.display_name ||
                      person.email ||
                      t("unnamed", { id: person.user_id.slice(0, 8) })}
                  </option>
                ))}
              </select>
            </label>
            {data.people.length === 0 && (
              <p className="text-xs text-muted-foreground">
                {t(
                  data.directory_status === "disabled"
                    ? "unknownRoster"
                    : "empty"
                )}
              </p>
            )}
            {person ? (
              <>
                <p className="break-all text-[11px] text-muted-foreground">
                  {person.user_id}
                </p>
                <p className="text-xs leading-5 text-muted-foreground">
                  {t("admissionHint")}
                </p>
                <p className="text-[11px] leading-4 text-muted-foreground">
                  {t("scopeHint")}
                </p>
                <section className="space-y-2">
                  <h3 className="text-xs font-semibold">{t("agents")}</h3>
                  {topology.nodes
                    .filter((node) => node.type === "agent")
                    .map((agent) => {
                      const decision = decisions.get(agent.id);
                      const state = decision
                        ? decision.allowed
                          ? "allowed"
                          : "denied"
                        : "unknown";
                      const Icon =
                        state === "allowed"
                          ? Check
                          : state === "denied"
                            ? LockKeyhole
                            : HelpCircle;
                      return (
                        <button
                          key={agent.id}
                          type="button"
                          onClick={() => onAgentSelect(agent)}
                          className="flex w-full items-start gap-2 rounded-md border border-border p-2.5 text-left hover:bg-muted focus-visible:ring-2 focus-visible:ring-primary"
                        >
                          <EntityIcon
                            kind="agent"
                            className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground"
                          />
                          <span className="min-w-0 flex-1">
                            <span className="block truncate text-xs font-medium">
                              {agent.label}
                            </span>
                            <span className="mt-1 flex items-center gap-1 text-[11px] text-muted-foreground">
                              <Icon
                                className={
                                  state === "allowed"
                                    ? "h-3 w-3 text-emerald-600 dark:text-emerald-400"
                                    : "h-3 w-3"
                                }
                              />
                              {t(state)}
                            </span>
                            {decision && (
                              <span className="mt-1 block text-[10px] text-muted-foreground">
                                {decision.reason === "workspace scope"
                                  ? t("membershipReason")
                                  : decision.reason === "public grant"
                                    ? t("publicReason")
                                    : t("decisionReason")}
                              </span>
                            )}
                          </span>
                        </button>
                      );
                    })}
                </section>
              </>
            ) : (
              <p className="text-xs leading-5 text-muted-foreground">
                {t("chooseHint")}
              </p>
            )}
          </>
        )}
      </div>
      <footer className="border-t border-border px-4 py-3">
        <Link
          href="/members"
          className="rounded text-xs font-medium text-primary hover:underline focus-visible:ring-2 focus-visible:ring-primary"
        >
          {t("openMembers")}
        </Link>
      </footer>
    </aside>
  );
}
