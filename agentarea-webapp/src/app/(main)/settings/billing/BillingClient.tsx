"use client";

import { useTranslations } from "next-intl";
import {
  Bot,
  Check,
  Cloud,
  Cpu,
  CreditCard,
  Crown,
  ExternalLink,
  Gauge,
  Globe2,
  LayoutDashboard,
  ListChecks,
  Plug,
  ServerCog,
  ShieldCheck,
  Sparkles,
  TableProperties,
  Users,
} from "lucide-react";
import EmptyState from "@/components/EmptyState";
import { Button } from "@/components/ui/button";
import { StatusIndicator } from "@/components/ui/status-indicator";
import { getBillingStatusPresentation } from "@/lib/status";
import { cn } from "@/lib/utils";
import type {
  BillingPlanKey,
  BillingSubscription,
  BillingUsageItem,
  CloudSetupEstimate,
} from "./actions";

type UsageIcon = React.ComponentType<{ className?: string }>;
type BillingExperience = "oss" | "cloud";

const USAGE_META: Record<string, { labelKey: string; icon: UsageIcon }> = {
  workspaces: { labelKey: "usage.workspaces", icon: LayoutDashboard },
  agents: { labelKey: "usage.agents", icon: Bot },
  mcp_connections: { labelKey: "usage.mcpConnections", icon: Plug },
  task_runs: { labelKey: "usage.taskRuns", icon: ListChecks },
};

const PLAN_ORDER: BillingPlanKey[] = ["payg", "enterprise"];
const CLOUD_BENEFITS = [
  "paymentMethods",
  "paymentHistory",
  "publicAgents",
  "guardrails",
] as const;
const CLOUD_BILLING_FEATURES = [
  "paymentMethods",
  "paymentHistory",
  "publicAgents",
  "guardrails",
  "managedInfra",
] as const;
const CLOUD_URL = "https://app.agentarea.ai/";
const SALES_EMAIL = "sales@agentarea.ai";

function humanizeKey(key: string): string {
  return key.replace(/[_-]+/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

interface Props {
  subscription: BillingSubscription | null;
  usage: BillingUsageItem[];
  available: boolean;
  error: string | null;
  billingExperience: BillingExperience;
  cloudEstimate: CloudSetupEstimate | null;
}

export default function BillingClient({
  subscription,
  usage,
  available,
  error,
  billingExperience,
  cloudEstimate,
}: Props) {
  const t = useTranslations("BillingPage");

  if (!available && !error) {
    return billingExperience === "cloud" ? (
      <CloudBillingPreview estimate={cloudEstimate} />
    ) : (
      <CloudMigrationPanel />
    );
  }

  return (
    <div className="mx-auto max-w-4xl">
      <div className="space-y-4">
        <CurrentPlanSection
          subscription={subscription}
          available={available}
          error={error}
        />

        <section id="plans" className="border-0 p-0">
          <div className="px-4 pt-3">
            <h2 className="text-sm font-medium text-zinc-700 dark:text-zinc-200">
              {t("availablePlans.title")}
            </h2>
            <p className="mt-0.5 text-xs text-zinc-500 dark:text-zinc-400">
              {t("availablePlans.subtitle")}
            </p>
          </div>
          <div className="grid grid-cols-1 gap-3 p-4 md:grid-cols-2">
            {PLAN_ORDER.map((planKey) => (
              <PlanCard
                key={planKey}
                planKey={planKey}
                current={subscription?.plan === planKey}
                highlighted={planKey === "payg"}
              />
            ))}
          </div>
        </section>

        <UsageSection usage={usage} available={available} error={error} />
      </div>
    </div>
  );
}

function CloudBillingPreview({
  estimate,
}: {
  estimate: CloudSetupEstimate | null;
}) {
  const t = useTranslations("BillingPage");

  return (
    <div className="mx-auto max-w-4xl space-y-4">
      <section className="relative overflow-hidden rounded-md border border-zinc-200/70 bg-white p-5 shadow-[0_2px_8px_-4px_rgba(0,0,0,0.05)] dark:border-zinc-800 dark:bg-zinc-900">
        <HatchBackground />
        <div className="relative z-10 flex flex-col gap-5 lg:flex-row lg:items-start lg:justify-between">
          <div className="max-w-2xl space-y-3">
            <div className="inline-flex items-center gap-2 rounded-full border border-zinc-200 bg-zinc-50 px-2.5 py-1 text-xs text-zinc-600 dark:border-zinc-800 dark:bg-zinc-950 dark:text-zinc-300">
              <Cloud className="h-3.5 w-3.5 text-primary" />
              {t("cloudBilling.badge")}
            </div>
            <div>
              <h2 className="text-xl font-semibold text-zinc-900 dark:text-zinc-100">
                {t("cloudBilling.title")}
              </h2>
              <p className="mt-2 text-sm leading-6 text-zinc-600 dark:text-zinc-300">
                {t("cloudBilling.description")}
              </p>
            </div>
          </div>
          <div className="flex shrink-0 flex-col gap-2 sm:flex-row lg:flex-col">
            <Button onClick={() => window.open(CLOUD_URL, "_blank")}>
              <Cloud className="h-4 w-4" />
              {t("cloudBilling.openCloud")}
              <ExternalLink className="h-3.5 w-3.5" />
            </Button>
            <Button
              variant="outline"
              onClick={() =>
                window.open(
                  `mailto:${SALES_EMAIL}?subject=Migrate to Agentarea Cloud`,
                  "_blank"
                )
              }
            >
              <Users className="h-4 w-4" />
              {t("cloudBilling.contactSales")}
            </Button>
          </div>
        </div>
      </section>

      <CloudCostEstimate estimate={estimate} />

      <section className="grid grid-cols-1 gap-3 md:grid-cols-2">
        {CLOUD_BILLING_FEATURES.map((key) => (
          <CloudBillingFeatureCard key={key} itemKey={key} />
        ))}
      </section>
    </div>
  );
}

function CloudCostEstimate({
  estimate,
}: {
  estimate: CloudSetupEstimate | null;
}) {
  const t = useTranslations("BillingPage");
  const infraEstimate = estimate?.infra_estimate_mtd_usd;

  return (
    <section className="rounded-md border border-zinc-200/70 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0 flex-1">
          <div className="mb-3 flex items-center gap-2">
            <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-primary/5 text-primary dark:bg-primary/10">
              <ServerCog className="h-4 w-4" />
            </div>
            <div>
              <h3 className="text-sm font-medium text-zinc-800 dark:text-zinc-100">
                {t("cloudBilling.estimate.title")}
              </h3>
              <p className="text-xs text-zinc-500 dark:text-zinc-400">
                {t("cloudBilling.estimate.subtitle")}
              </p>
            </div>
          </div>

          <div className="rounded-md border border-dashed border-zinc-200 p-3 dark:border-zinc-800">
            <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <p className="text-xs text-zinc-500 dark:text-zinc-400">
                  {t("cloudBilling.estimate.infraLabel")}
                </p>
                <p className="mt-1 text-2xl font-semibold text-zinc-900 dark:text-zinc-100">
                  {infraEstimate === null || infraEstimate === undefined
                    ? t("cloudBilling.estimate.telemetryPending")
                    : formatUsd(infraEstimate)}
                </p>
              </div>
              <div className="flex items-center gap-2 text-xs text-zinc-500 dark:text-zinc-400">
                <Cpu className="h-4 w-4 text-primary" />
                {t("cloudBilling.estimate.basedOnResources")}
              </div>
            </div>
            <div className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-2">
              <InlineMetric
                label={t("cloudBilling.estimate.cpu")}
                value={formatHours(estimate?.cpu_core_hours_mtd)}
              />
              <InlineMetric
                label={t("cloudBilling.estimate.memory")}
                value={formatHours(estimate?.memory_gb_hours_mtd)}
              />
            </div>
          </div>
        </div>

        <div className="grid min-w-0 grid-cols-1 gap-2 sm:grid-cols-3 lg:w-72 lg:grid-cols-1">
          <EstimateMetric
            label={t("cloudBilling.estimate.agents")}
            value={formatCount(estimate?.agent_count)}
          />
          <EstimateMetric
            label={t("cloudBilling.estimate.connections")}
            value={formatCount(estimate?.connection_count)}
          />
          <EstimateMetric
            label={t("cloudBilling.estimate.taskRuns")}
            value={formatCount(estimate?.task_runs_mtd)}
          />
        </div>
      </div>

      <div className="mt-3 rounded-md bg-zinc-50 p-3 text-xs leading-5 text-zinc-600 dark:bg-zinc-950 dark:text-zinc-300">
        <span className="font-medium text-zinc-800 dark:text-zinc-100">
          {t("cloudBilling.agentUsage.label")}
        </span>{" "}
        {t("cloudBilling.agentUsage.description", {
          spend: formatUsd(estimate?.agent_spend_mtd_usd),
          projected: formatUsd(estimate?.agent_projected_eom_usd),
        })}
      </div>
    </section>
  );
}

function CloudBillingFeatureCard({
  itemKey,
}: {
  itemKey: (typeof CLOUD_BILLING_FEATURES)[number];
}) {
  const t = useTranslations("BillingPage");
  const icons: Record<(typeof CLOUD_BILLING_FEATURES)[number], UsageIcon> = {
    paymentMethods: CreditCard,
    paymentHistory: TableProperties,
    publicAgents: Globe2,
    guardrails: ShieldCheck,
    managedInfra: ServerCog,
  };
  const Icon = icons[itemKey];

  return (
    <div className="rounded-md border border-zinc-200/70 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900">
      <div className="mb-3 flex h-8 w-8 items-center justify-center rounded-full bg-primary/5 text-primary dark:bg-primary/10">
        <Icon className="h-4 w-4" />
      </div>
      <h3 className="text-sm font-medium text-zinc-800 dark:text-zinc-100">
        {t(`cloudBilling.features.${itemKey}.title`)}
      </h3>
      <p className="mt-1 text-xs leading-5 text-zinc-500 dark:text-zinc-400">
        {t(`cloudBilling.features.${itemKey}.description`)}
      </p>
    </div>
  );
}

function EstimateMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-zinc-200/70 bg-white p-3 dark:border-zinc-800 dark:bg-zinc-950">
      <p className="text-xs text-zinc-500 dark:text-zinc-400">{label}</p>
      <p className="mt-1 text-lg font-semibold text-zinc-900 dark:text-zinc-100">
        {value}
      </p>
    </div>
  );
}

function InlineMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-3 rounded-md bg-zinc-50 px-3 py-2 text-xs dark:bg-zinc-950">
      <span className="text-zinc-500 dark:text-zinc-400">{label}</span>
      <span className="font-medium text-zinc-800 dark:text-zinc-100">
        {value}
      </span>
    </div>
  );
}

function formatUsd(value: number | null | undefined): string {
  if (value === null || value === undefined) {
    return "-";
  }

  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: value >= 100 ? 0 : 2,
  }).format(value);
}

function formatCount(value: number | null | undefined): string {
  return value === null || value === undefined ? "-" : value.toLocaleString();
}

function formatHours(value: number | null | undefined): string {
  return value === null || value === undefined ? "-" : value.toLocaleString();
}

function CloudMigrationPanel() {
  const t = useTranslations("BillingPage");

  return (
    <div className="mx-auto max-w-4xl space-y-4">
      <section className="relative overflow-hidden rounded-md border border-zinc-200/70 bg-white p-5 shadow-[0_2px_8px_-4px_rgba(0,0,0,0.05)] dark:border-zinc-800 dark:bg-zinc-900">
        <HatchBackground />
        <div className="relative z-10 flex flex-col gap-5 lg:flex-row lg:items-start lg:justify-between">
          <div className="max-w-2xl space-y-3">
            <div className="inline-flex items-center gap-2 rounded-full border border-zinc-200 bg-zinc-50 px-2.5 py-1 text-xs text-zinc-600 dark:border-zinc-800 dark:bg-zinc-950 dark:text-zinc-300">
              <Cloud className="h-3.5 w-3.5 text-primary" />
              {t("cloudMigration.badge")}
            </div>
            <div>
              <h2 className="text-xl font-semibold text-zinc-900 dark:text-zinc-100">
                {t("cloudMigration.title")}
              </h2>
              <p className="mt-2 text-sm leading-6 text-zinc-600 dark:text-zinc-300">
                {t("cloudMigration.description")}
              </p>
            </div>
          </div>
          <div className="flex shrink-0 flex-col gap-2 sm:flex-row lg:flex-col">
            <Button onClick={() => window.open(CLOUD_URL, "_blank")}>
              <Cloud className="h-4 w-4" />
              {t("cloudMigration.openCloud")}
              <ExternalLink className="h-3.5 w-3.5" />
            </Button>
            <Button
              variant="outline"
              onClick={() =>
                window.open(
                  `mailto:${SALES_EMAIL}?subject=Migrate to Agentarea Cloud`,
                  "_blank"
                )
              }
            >
              <Users className="h-4 w-4" />
              {t("cloudMigration.contactSales")}
            </Button>
          </div>
        </div>
      </section>

      <section className="grid grid-cols-1 gap-3 md:grid-cols-2">
        {CLOUD_BENEFITS.map((key) => (
          <CloudBenefitCard key={key} itemKey={key} />
        ))}
      </section>
    </div>
  );
}

function CloudBenefitCard({
  itemKey,
}: {
  itemKey: (typeof CLOUD_BENEFITS)[number];
}) {
  const t = useTranslations("BillingPage");
  const icons: Record<(typeof CLOUD_BENEFITS)[number], UsageIcon> = {
    paymentMethods: CreditCard,
    paymentHistory: TableProperties,
    publicAgents: Globe2,
    guardrails: ShieldCheck,
  };
  const Icon = icons[itemKey];

  return (
    <div className="rounded-md border border-zinc-200/70 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900">
      <div className="mb-3 flex h-8 w-8 items-center justify-center rounded-full bg-primary/5 text-primary dark:bg-primary/10">
        <Icon className="h-4 w-4" />
      </div>
      <h3 className="text-sm font-medium text-zinc-800 dark:text-zinc-100">
        {t(`cloudMigration.benefits.${itemKey}.title`)}
      </h3>
      <p className="mt-1 text-xs leading-5 text-zinc-500 dark:text-zinc-400">
        {t(`cloudMigration.benefits.${itemKey}.description`)}
      </p>
    </div>
  );
}

function CurrentPlanSection({
  subscription,
  available,
  error,
}: {
  subscription: BillingSubscription | null;
  available: boolean;
  error: string | null;
}) {
  const t = useTranslations("BillingPage");

  return (
    <section id="current-plan" className="border-0 p-0">
      <div className="px-4 pt-3">
        <h2 className="text-sm font-medium text-zinc-700 dark:text-zinc-200">
          {t("currentPlan.title")}
        </h2>
        <p className="mt-0.5 text-xs text-zinc-500 dark:text-zinc-400">
          {t("currentPlan.subtitle")}
        </p>
      </div>
      <div className="p-4">
        {subscription ? (
          <Card>
            <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-primary/5 text-primary dark:bg-primary/10 z-10">
              <CreditCard className="h-4 w-4" />
            </div>
            <div className="flex-1 min-w-0 z-10">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm font-medium text-zinc-700 dark:text-zinc-200">
                    {t(`plans.${subscription.plan}.name`)}
                  </p>
                  <p className="text-xs text-zinc-500 dark:text-zinc-400">
                    {t(`plans.${subscription.plan}.description`)}
                  </p>
                </div>
                <SubscriptionStatus status={subscription.status} />
              </div>
            </div>
          </Card>
        ) : (
          <BillingEmptyState available={available} error={error} />
        )}
      </div>
    </section>
  );
}

function UsageSection({
  usage,
  available,
  error,
}: {
  usage: BillingUsageItem[];
  available: boolean;
  error: string | null;
}) {
  const t = useTranslations("BillingPage");

  return (
    <section id="usage" className="border-0 p-0">
      <div className="px-4 pt-3">
        <h2 className="text-sm font-medium text-zinc-700 dark:text-zinc-200">
          {t("usage.title")}
        </h2>
        <p className="mt-0.5 text-xs text-zinc-500 dark:text-zinc-400">
          {t("usage.subtitle")}
        </p>
      </div>
      <div className="p-4">
        {usage.length > 0 ? (
          <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
            {usage.map((item) => (
              <UsageCard key={item.key} item={item} />
            ))}
          </div>
        ) : (
          <BillingEmptyState available={available} error={error} />
        )}
      </div>
    </section>
  );
}

function SubscriptionStatus({ status }: { status: string }) {
  const t = useTranslations("BillingPage");
  const presentation = getBillingStatusPresentation(status);
  const label = t.has(`currentPlan.statuses.${status}`)
    ? t(`currentPlan.statuses.${status}`)
    : presentation.label || humanizeKey(status);

  return (
    <StatusIndicator
      size="sm"
      tone={presentation.tone}
      pulse={presentation.pulse}
      className="whitespace-nowrap"
    >
      {label}
    </StatusIndicator>
  );
}

function BillingEmptyState({
  available,
  error,
}: {
  available: boolean;
  error: string | null;
}) {
  const t = useTranslations("BillingPage");

  if (error) {
    return (
      <EmptyState
        title={t("loadError.title")}
        description={t("loadError.description")}
        iconsType="payments"
      />
    );
  }

  return (
    <EmptyState
      title={available ? t("empty.title") : t("unavailable.title")}
      description={
        available ? t("empty.description") : t("unavailable.description")
      }
      iconsType="payments"
    />
  );
}

function Card({ children }: { children: React.ReactNode }) {
  return (
    <div
      className={cn(
        "group relative flex items-start gap-3 w-full p-4",
        "bg-white dark:bg-zinc-900",
        "border border-zinc-200/60 dark:border-zinc-800",
        "rounded-md transition-all duration-300 ease-out",
        "shadow-[0_2px_8px_-4px_rgba(0,0,0,0.05)]",
        "relative overflow-hidden"
      )}
    >
      <HatchBackground />
      {children}
    </div>
  );
}

function HatchBackground() {
  return (
    <div
      className="absolute inset-0 opacity-[0.015] dark:opacity-[0.03] pointer-events-none"
      style={{
        backgroundImage: `repeating-linear-gradient(
          -45deg,
          currentColor,
          currentColor 1px,
          transparent 1px,
          transparent 10px
        )`,
      }}
    />
  );
}

function PlanCard({
  planKey,
  current,
  highlighted,
}: {
  planKey: BillingPlanKey;
  current: boolean;
  highlighted: boolean;
}) {
  const t = useTranslations("BillingPage");

  const featuresMap: Record<BillingPlanKey, string[]> = {
    free: [
      "plans.free.features.workspace",
      "plans.free.features.agents",
      "plans.free.features.mcpConnections",
      "plans.free.features.support",
      "plans.free.features.taskRuns",
    ],
    payg: [
      "plans.payg.features.noMonthlyFee",
      "plans.payg.features.usageBased",
      "plans.payg.features.agents",
      "plans.payg.features.mcpConnections",
      "plans.payg.features.collaboration",
      "plans.payg.features.support",
    ],
    enterprise: [
      "plans.enterprise.features.everything",
      "plans.enterprise.features.sso",
      "plans.enterprise.features.sla",
      "plans.enterprise.features.infrastructure",
      "plans.enterprise.features.taskRuns",
      "plans.enterprise.features.compliance",
      "plans.enterprise.features.deployment",
      "plans.enterprise.features.support",
    ],
  };

  const features = featuresMap[planKey] || [];

  return (
    <div
      className={cn(
        "group relative flex flex-col w-full",
        "bg-white dark:bg-zinc-900",
        "border rounded-md transition-all duration-300 ease-out",
        "shadow-[0_2px_8px_-4px_rgba(0,0,0,0.05)]",
        "relative overflow-hidden",
        highlighted
          ? "border-primary/50"
          : "border-zinc-200/60 dark:border-zinc-800"
      )}
    >
      <HatchBackground />
      {highlighted && (
        <div className="absolute top-0 right-0 bg-primary text-primary-foreground text-[10px] font-normal px-2.5 py-1 rounded-bl-md z-20">
          {t("availablePlans.recommended")}
        </div>
      )}
      <div className="p-4 z-10">
        <div className="flex items-center gap-2 mb-2">
          {highlighted && <Crown className="h-3.5 w-3.5 text-primary" />}
          <h3 className="text-xs font-thin uppercase tracking-wider text-zinc-700 dark:text-zinc-200">
            {t(`plans.${planKey}.name`)}
          </h3>
        </div>
        <div className="flex items-baseline gap-1 mb-1">
          <span className="text-2xl font-bold text-zinc-900 dark:text-zinc-100">
            {t(`plans.${planKey}.price`)}
          </span>
          {t(`plans.${planKey}.period`) && (
            <span className="text-xs text-zinc-500 dark:text-zinc-400">
              / {t(`plans.${planKey}.period`)}
            </span>
          )}
        </div>
        <p className="text-xs text-zinc-500 dark:text-zinc-400 mb-3">
          {t(`plans.${planKey}.description`)}
        </p>
        <ul className="space-y-1.5 mb-4">
          {features.map((featureKey) => (
            <li
              key={featureKey}
              className="flex items-center gap-2 text-xs text-zinc-600 dark:text-zinc-300"
            >
              <Check className="h-3 w-3 text-primary shrink-0" />
              {t(featureKey)}
            </li>
          ))}
        </ul>
        {current ? (
          <Button variant="outline" size="sm" className="w-full" disabled>
            {t("availablePlans.currentPlan")}
          </Button>
        ) : planKey === "enterprise" ? (
          <Button
            variant="outline"
            size="sm"
            className="w-full"
            onClick={() => window.open("mailto:sales@agentarea.ai", "_blank")}
          >
            {t("availablePlans.contactSales")}
          </Button>
        ) : (
          <Button
            size="sm"
            className="w-full"
            onClick={() =>
              window.open("https://agentarea.ai/pricing", "_blank")
            }
          >
            <Sparkles className="h-3 w-3 mr-1.5" />
            {t("availablePlans.setUpBilling")}
          </Button>
        )}
      </div>
    </div>
  );
}

function UsageCard({ item }: { item: BillingUsageItem }) {
  const t = useTranslations("BillingPage");
  const meta = USAGE_META[item.key];
  const Icon = meta?.icon ?? Gauge;
  const label = meta ? t(meta.labelKey) : humanizeKey(item.key);

  const isUnlimited = item.limit === null;
  const percentage =
    !isUnlimited && (item.limit ?? 0) > 0
      ? Math.min((item.used / (item.limit ?? 0)) * 100, 100)
      : 0;
  const isNearLimit = !isUnlimited && percentage >= 80;

  return (
    <div
      className={cn(
        "group relative flex items-start gap-3 w-full p-4",
        "bg-white dark:bg-zinc-900",
        "border border-zinc-200/60 dark:border-zinc-800",
        "rounded-md transition-all duration-300 ease-out",
        "shadow-[0_2px_8px_-4px_rgba(0,0,0,0.05)]",
        "relative overflow-hidden"
      )}
    >
      <HatchBackground />
      <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-primary/5 text-primary dark:bg-primary/10 z-10">
        <Icon className="h-4 w-4" />
      </div>
      <div className="flex-1 min-w-0 z-10">
        <div className="flex items-center justify-between mb-2">
          <span className="text-sm font-medium text-zinc-700 dark:text-zinc-200">
            {label}
          </span>
          <span className="text-xs text-zinc-500 dark:text-zinc-400">
            {item.used.toLocaleString()} /{" "}
            {isUnlimited ? t("usage.unlimited") : (item.limit ?? 0).toLocaleString()}
          </span>
        </div>
        <div className="h-1.5 rounded-full bg-zinc-100 dark:bg-zinc-800 overflow-hidden">
          <div
            className={cn(
              "h-full rounded-full transition-all",
              isNearLimit ? "bg-orange-500" : "bg-primary"
            )}
            style={{ width: `${percentage}%` }}
          />
        </div>
      </div>
    </div>
  );
}
