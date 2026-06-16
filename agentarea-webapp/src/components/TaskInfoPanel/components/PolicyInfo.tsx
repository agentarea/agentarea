import { useTranslations } from "next-intl";
import {
  Coins,
  Hash,
  ShieldCheck,
  UserCheck,
  Wrench,
} from "lucide-react";
import type { EffectivePolicy, Money } from "@/types/policies";
import Section from "./Section";

interface PolicyInfoProps {
  policy?: EffectivePolicy | null;
}

function money(v: Money | null | undefined): string | null {
  if (v == null) return null;
  const n = Number(v);
  return Number.isNaN(n) ? null : `$${n.toFixed(2)}`;
}

function Row({
  icon: Icon,
  label,
  value,
}: {
  icon: typeof Wrench;
  label: string;
  value: React.ReactNode;
}) {
  return (
    <div className="flex items-start justify-between gap-2 py-1">
      <div className="flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
        <Icon className="h-3 w-3 shrink-0 text-primary" />
        {label}
      </div>
      <div className="min-w-0 text-right text-[12px] text-foreground">
        {value}
      </div>
    </div>
  );
}

function Chips({ items }: { items: string[] }) {
  return (
    <div className="flex flex-wrap justify-end gap-1">
      {items.map((it) => (
        <span
          key={it}
          className="inline-flex items-center rounded-md bg-muted/60 px-1.5 py-0.5 font-mono text-[10px]"
        >
          {it}
        </span>
      ))}
    </div>
  );
}

/** Governance policy snapshot resolved for the task (budget gauge is separate). */
export default function PolicyInfo({ policy }: PolicyInfoProps) {
  const t = useTranslations("TaskInfoPanel");

  if (!policy) return null;

  const monthlyCap = money(policy.budget?.monthly_spend_cap_usd);
  const serviceBudget = money(policy.budget?.service_budget_usd);

  const allowed = policy.tools?.allowed;
  const denied = policy.tools?.denied ?? [];
  const hasTools = allowed != null || denied.length > 0;

  const maxTokens = policy.tokens?.max_tokens;
  const perCall = policy.tokens?.max_tokens_per_call;
  const hasTokens = maxTokens != null || perCall != null;

  const requiresApproval = policy.approval?.requires_human_approval;
  const approvers = policy.approval?.approvers ?? [];

  const promptInjection = policy.content_safety?.prompt_injection_detection_enabled;
  const outputSanitizer = policy.content_safety?.output_sanitizer_enabled;
  const hasContentSafety = promptInjection != null || outputSanitizer != null;

  const hasAny =
    monthlyCap != null ||
    serviceBudget != null ||
    hasTools ||
    hasTokens ||
    requiresApproval != null ||
    hasContentSafety;

  if (!hasAny) {
    return (
      <Section title={t("policy")} contentClassName="text-xs">
        <div className="py-1 text-[12px] text-muted-foreground">
          {t("policyNone")}
        </div>
      </Section>
    );
  }

  return (
    <Section title={t("policy")} contentClassName="text-xs divide-y divide-border/50">
      {hasTools && (
        <Row
          icon={Wrench}
          label={t("policyTools")}
          value={
            <div className="space-y-1">
              {allowed == null ? (
                <span className="text-muted-foreground">{t("policyAllTools")}</span>
              ) : allowed.length > 0 ? (
                <div className="flex items-center justify-end gap-1.5">
                  <span className="text-[10px] text-green-600 dark:text-green-500">
                    {t("policyAllowed")}
                  </span>
                  <Chips items={allowed} />
                </div>
              ) : null}
              {denied.length > 0 && (
                <div className="flex items-center justify-end gap-1.5">
                  <span className="text-[10px] text-destructive">
                    {t("policyDenied")}
                  </span>
                  <Chips items={denied} />
                </div>
              )}
            </div>
          }
        />
      )}

      {requiresApproval != null && (
        <Row
          icon={UserCheck}
          label={t("policyApproval")}
          value={
            <span className={requiresApproval ? "text-foreground" : "text-muted-foreground"}>
              {requiresApproval ? t("policyRequired") : t("policyNotRequired")}
              {requiresApproval && approvers.length > 0 && (
                <span className="text-muted-foreground">
                  {" "}· {approvers.length}
                </span>
              )}
            </span>
          }
        />
      )}

      {hasTokens && (
        <Row
          icon={Hash}
          label={t("policyTokens")}
          value={
            <span>
              {maxTokens != null && maxTokens.toLocaleString()}
              {perCall != null && (
                <span className="text-muted-foreground">
                  {maxTokens != null ? " · " : ""}
                  {perCall.toLocaleString()} {t("policyPerCall")}
                </span>
              )}
            </span>
          }
        />
      )}

      {monthlyCap != null && (
        <Row icon={Coins} label={t("policyMonthlyCap")} value={monthlyCap} />
      )}

      {serviceBudget != null && (
        <Row icon={Coins} label={t("policyServiceBudget")} value={serviceBudget} />
      )}

      {hasContentSafety && (
        <Row
          icon={ShieldCheck}
          label={t("policyContentSafety")}
          value={
            <div className="space-y-0.5 text-[11px]">
              {promptInjection != null && (
                <div>
                  {t("policyPromptInjection")}:{" "}
                  <span className={promptInjection ? "text-green-600 dark:text-green-500" : "text-muted-foreground"}>
                    {promptInjection ? t("policyOn") : t("policyOff")}
                  </span>
                </div>
              )}
              {outputSanitizer != null && (
                <div>
                  {t("policyOutputSanitizer")}:{" "}
                  <span className={outputSanitizer ? "text-green-600 dark:text-green-500" : "text-muted-foreground"}>
                    {outputSanitizer ? t("policyOn") : t("policyOff")}
                  </span>
                </div>
              )}
            </div>
          }
        />
      )}
    </Section>
  );
}
