"use client";

import { useTranslations } from "next-intl";
import { Download, Loader2, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { AuditActorOption } from "./actions";

/** The resource types the audit trail records, in the order a reviewer scans them. */
export const AUDIT_RESOURCE_TYPES = [
  "task",
  "agent",
  "skill",
  "trigger",
  "mcp_server",
  "mcp_instance",
  "client",
  "governance_policy",
  "secret",
  "api_key",
  "member",
  "invitation",
  "access_grant",
] as const;

/** Every action the platform records, grouped by what it is about. */
export const AUDIT_ACTION_GROUPS: Record<string, readonly string[]> = {
  toolCalls: [
    "tool.call.allowed",
    "tool.call.denied",
    "tool.call.approval_required",
    "approval.approved",
    "approval.denied",
  ],
  access: [
    "secret.create",
    "secret.update",
    "secret.rotate",
    "secret.delete",
    "api_key.create",
    "api_key.revoke",
    "member.invite",
    "member.invitation_revoke",
    "member.remove",
    "access.grant",
    "access.revoke",
    "governance_policy.create",
    "governance_policy.update",
    "governance_policy.set_enabled",
    "governance_policy.delete",
  ],
  config: [
    "agent.create",
    "agent.update",
    "agent.delete",
    "skill.create",
    "skill.update",
    "skill.delete",
    "trigger.create",
    "trigger.update",
    "trigger.delete",
    "trigger.signing_secret_rotate",
    "mcp_server.create",
    "mcp_server.update",
    "mcp_server.delete",
    "mcp_instance.create",
    "mcp_instance.update",
    "mcp_instance.delete",
    "task.create",
  ],
};

export const ALL = "all";

export interface AuditFilterState {
  resourceType: string;
  action: string;
  actorId: string;
  since: string;
  until: string;
}

export const EMPTY_FILTERS: AuditFilterState = {
  resourceType: ALL,
  action: ALL,
  actorId: ALL,
  since: "",
  until: "",
};

export function isFiltered(filters: AuditFilterState): boolean {
  return (
    filters.resourceType !== ALL ||
    filters.action !== ALL ||
    filters.actorId !== ALL ||
    filters.since !== "" ||
    filters.until !== ""
  );
}

export function AuditLogFilters({
  value,
  onChange,
  actorOptions,
  onExport,
  exporting,
}: {
  value: AuditFilterState;
  onChange: (next: AuditFilterState) => void;
  actorOptions: AuditActorOption[];
  onExport: () => void;
  exporting: boolean;
}) {
  const t = useTranslations("AuditLogPage");
  const set = (patch: Partial<AuditFilterState>) =>
    onChange({ ...value, ...patch });
  const people = actorOptions.filter((option) => option.kind === "user");
  const agents = actorOptions.filter((option) => option.kind === "agent");

  return (
    <div className="mb-4 flex flex-wrap items-end gap-2">
      <Select
        value={value.resourceType}
        onValueChange={(resourceType) => set({ resourceType })}
      >
        <SelectTrigger
          className="h-9 w-full sm:w-[180px]"
          aria-label={t("filters.resourceType")}
        >
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={ALL}>{t("filters.allResources")}</SelectItem>
          {AUDIT_RESOURCE_TYPES.map((type) => (
            <SelectItem key={type} value={type}>
              {t(`resourceTypes.${type}`)}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>

      <Select value={value.action} onValueChange={(action) => set({ action })}>
        <SelectTrigger
          className="h-9 w-full sm:w-[220px]"
          aria-label={t("filters.action")}
        >
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={ALL}>{t("filters.allActions")}</SelectItem>
          {Object.entries(AUDIT_ACTION_GROUPS).map(([group, actions]) => (
            <SelectGroup key={group}>
              <SelectLabel>{t(`actionGroups.${group}`)}</SelectLabel>
              {actions.map((action) => (
                <SelectItem key={action} value={action}>
                  <span className="font-mono text-xs">{action}</span>
                </SelectItem>
              ))}
            </SelectGroup>
          ))}
        </SelectContent>
      </Select>

      <Select value={value.actorId} onValueChange={(actorId) => set({ actorId })}>
        <SelectTrigger
          className="h-9 w-full sm:w-[200px]"
          aria-label={t("filters.actor")}
        >
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={ALL}>{t("filters.anyone")}</SelectItem>
          {people.length > 0 && (
            <SelectGroup>
              <SelectLabel>{t("filters.people")}</SelectLabel>
              {people.map((option) => (
                <SelectItem key={option.value} value={option.value}>
                  {option.label}
                </SelectItem>
              ))}
            </SelectGroup>
          )}
          {agents.length > 0 && (
            <SelectGroup>
              <SelectLabel>{t("filters.agents")}</SelectLabel>
              {agents.map((option) => (
                <SelectItem key={option.value} value={option.value}>
                  {option.label}
                </SelectItem>
              ))}
            </SelectGroup>
          )}
        </SelectContent>
      </Select>

      <Input
        type="date"
        className="h-9 w-full sm:w-[150px]"
        aria-label={t("filters.since")}
        title={t("filters.since")}
        value={value.since}
        max={value.until || undefined}
        onChange={(e) => set({ since: e.target.value })}
      />
      <Input
        type="date"
        className="h-9 w-full sm:w-[150px]"
        aria-label={t("filters.until")}
        title={t("filters.until")}
        value={value.until}
        min={value.since || undefined}
        onChange={(e) => set({ until: e.target.value })}
      />

      {isFiltered(value) && (
        <Button
          variant="ghost"
          size="sm"
          className="h-9"
          onClick={() => onChange(EMPTY_FILTERS)}
        >
          <X className="mr-1 h-4 w-4" aria-hidden />
          {t("filters.reset")}
        </Button>
      )}

      <Button
        variant="outline"
        size="sm"
        className="h-9 sm:ml-auto"
        onClick={onExport}
        disabled={exporting}
      >
        {exporting ? (
          <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden />
        ) : (
          <Download className="mr-2 h-4 w-4" aria-hidden />
        )}
        {exporting ? t("export.working") : t("export.button")}
      </Button>
    </div>
  );
}
