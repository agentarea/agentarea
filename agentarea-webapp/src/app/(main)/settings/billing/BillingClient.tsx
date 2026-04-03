"use client";

import { useTranslations } from "next-intl";
import { Check, CreditCard, Crown, Sparkles, Zap } from "lucide-react";
import ContentBlock from "@/components/ContentBlock";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export default function BillingClient() {
  const t = useTranslations("BillingPage");
  const tSettings = useTranslations("SettingsPage");

  const plans = [
    {
      key: "free",
      current: true,
      highlighted: false,
    },
    {
      key: "pro",
      current: false,
      highlighted: true,
    },
    {
      key: "enterprise",
      current: false,
      highlighted: false,
    },
  ];

  return (
    <ContentBlock
      header={{
        breadcrumb: [
          { label: tSettings("title"), href: "/settings" },
          { label: t("title") },
        ],
        description: t("description"),
      }}
    >
      <div className="mx-auto max-w-4xl">
        <div className="space-y-4">
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
                <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-primary/5 text-primary dark:bg-primary/10 z-10">
                  <CreditCard className="h-4 w-4" />
                </div>
                <div className="flex-1 min-w-0 z-10">
                  <div className="flex items-center justify-between">
                    <div>
                      <p className="text-sm font-medium text-zinc-700 dark:text-zinc-200">
                        {t("currentPlan.freePlan")}
                      </p>
                      <p className="text-xs text-zinc-500 dark:text-zinc-400">
                        {t("currentPlan.freePlanDescription")}
                      </p>
                    </div>
                    <div className="flex items-center gap-1.5 text-xs text-green-600 dark:text-green-400">
                      <div className="h-1.5 w-1.5 rounded-full bg-green-500" />
                      {t("currentPlan.active")}
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </section>

          <section id="plans" className="border-0 p-0">
            <div className="px-4 pt-3">
              <h2 className="text-sm font-medium text-zinc-700 dark:text-zinc-200">
                {t("availablePlans.title")}
              </h2>
              <p className="mt-0.5 text-xs text-zinc-500 dark:text-zinc-400">
                {t("availablePlans.subtitle")}
              </p>
            </div>
            <div className="grid grid-cols-1 gap-3 p-4 md:grid-cols-3">
              {plans.map((plan) => (
                <PlanCard
                  key={plan.key}
                  planKey={plan.key}
                  current={plan.current}
                  highlighted={plan.highlighted}
                />
              ))}
            </div>
          </section>

          <section id="usage" className="border-0 p-0">
            <div className="px-4 pt-3">
              <h2 className="text-sm font-medium text-zinc-700 dark:text-zinc-200">
                {t("usage.title")}
              </h2>
              <p className="mt-0.5 text-xs text-zinc-500 dark:text-zinc-400">
                {t("usage.subtitle")}
              </p>
            </div>
            <div className="grid grid-cols-1 gap-3 p-4 sm:grid-cols-2">
              <UsageCard label={t("usage.workspaces")} used={1} limit={1} />
              <UsageCard label={t("usage.agents")} used={0} limit={3} />
              <UsageCard label={t("usage.mcpConnections")} used={0} limit={5} />
              <UsageCard label={t("usage.taskRuns")} used={0} limit={1000} />
            </div>
          </section>
        </div>
      </div>
    </ContentBlock>
  );
}

function PlanCard({
  planKey,
  current,
  highlighted,
}: {
  planKey: string;
  current: boolean;
  highlighted: boolean;
}) {
  const t = useTranslations("BillingPage");

  const featuresMap: Record<string, string[]> = {
    free: [
      "plans.free.features.workspace",
      "plans.free.features.agents",
      "plans.free.features.mcpConnections",
      "plans.free.features.support",
      "plans.free.features.taskRuns",
    ],
    pro: [
      "plans.pro.features.workspaces",
      "plans.pro.features.agents",
      "plans.pro.features.mcpConnections",
      "plans.pro.features.support",
      "plans.pro.features.taskRuns",
      "plans.pro.features.collaboration",
      "plans.pro.features.analytics",
      "plans.pro.features.execution",
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
      {highlighted && (
        <div className="absolute top-0 right-0 bg-primary text-primary-foreground text-[10px] font-bold px-2.5 py-1 rounded-bl-md z-20">
          {t("availablePlans.recommended")}
        </div>
      )}
      <div className="p-4 z-10">
        <div className="flex items-center gap-2 mb-2">
          {highlighted && <Crown className="h-3.5 w-3.5 text-primary" />}
          <h3 className="text-sm font-medium text-zinc-700 dark:text-zinc-200">
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
            {t("availablePlans.upgradeTo", {
              planName: t(`plans.${planKey}.name`),
            })}
          </Button>
        )}
      </div>
    </div>
  );
}

function UsageCard({
  label,
  used,
  limit,
}: {
  label: string;
  used: number;
  limit: number;
}) {
  const percentage = limit > 0 ? Math.min((used / limit) * 100, 100) : 0;
  const isNearLimit = percentage >= 80;

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
      <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-primary/5 text-primary dark:bg-primary/10 z-10">
        <Zap className="h-4 w-4" />
      </div>
      <div className="flex-1 min-w-0 z-10">
        <div className="flex items-center justify-between mb-2">
          <span className="text-sm font-medium text-zinc-700 dark:text-zinc-200">
            {label}
          </span>
          <span className="text-xs text-zinc-500 dark:text-zinc-400">
            {used} / {limit.toLocaleString()}
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
