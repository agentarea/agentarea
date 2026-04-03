"use client";

import { Check, CreditCard, Crown, Sparkles, Zap } from "lucide-react";
import ContentBlock from "@/components/ContentBlock";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

const plans = [
  {
    name: "Free",
    price: "$0",
    period: "forever",
    description: "For individuals getting started",
    features: [
      "1 workspace",
      "Up to 3 agents",
      "5 MCP connections",
      "Community support",
      "1,000 task runs / month",
    ],
    current: true,
  },
  {
    name: "Pro",
    price: "$49",
    period: "per month",
    description: "For teams building agent organizations",
    features: [
      "Unlimited workspaces",
      "Unlimited agents",
      "Unlimited MCP connections",
      "Priority support",
      "50,000 task runs / month",
      "Team collaboration",
      "Advanced analytics",
      "Priority execution",
    ],
    highlighted: true,
  },
  {
    name: "Enterprise",
    price: "Custom",
    period: "",
    description: "For organizations with advanced needs",
    features: [
      "Everything in Pro",
      "SSO / SAML",
      "Custom SLA",
      "Dedicated infrastructure",
      "Unlimited task runs",
      "Audit logs & compliance",
      "On-premise deployment",
      "Dedicated support engineer",
    ],
  },
];

export default function BillingClient() {
  return (
    <ContentBlock
      header={{
        breadcrumb: [
          { label: "Settings", href: "/settings" },
          { label: "Billing" },
        ],
        description: "Manage your subscription and billing",
      }}
    >
      <div className="mx-auto max-w-4xl">
        <div className="space-y-4">
          <section id="current-plan" className="border-0 p-0">
            <div className="px-4 pt-3">
              <h2 className="text-sm font-medium text-zinc-700 dark:text-zinc-200">
                Current Plan
              </h2>
              <p className="mt-0.5 text-xs text-zinc-500 dark:text-zinc-400">
                Your active subscription
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
                        Free Plan
                      </p>
                      <p className="text-xs text-zinc-500 dark:text-zinc-400">
                        1 workspace, 3 agents, 1,000 task runs / month
                      </p>
                    </div>
                    <div className="flex items-center gap-1.5 text-xs text-green-600 dark:text-green-400">
                      <div className="h-1.5 w-1.5 rounded-full bg-green-500" />
                      Active
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </section>

          <section id="plans" className="border-0 p-0">
            <div className="px-4 pt-3">
              <h2 className="text-sm font-medium text-zinc-700 dark:text-zinc-200">
                Available Plans
              </h2>
              <p className="mt-0.5 text-xs text-zinc-500 dark:text-zinc-400">
                Choose the plan that fits your needs
              </p>
            </div>
            <div className="grid grid-cols-1 gap-3 p-4 md:grid-cols-3">
              {plans.map((plan) => (
                <div
                  key={plan.name}
                  className={cn(
                    "group relative flex flex-col w-full",
                    "bg-white dark:bg-zinc-900",
                    "border rounded-md transition-all duration-300 ease-out",
                    "shadow-[0_2px_8px_-4px_rgba(0,0,0,0.05)]",
                    "relative overflow-hidden",
                    plan.highlighted
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
                  {plan.highlighted && (
                    <div className="absolute top-0 right-0 bg-primary text-primary-foreground text-[10px] font-bold px-2.5 py-1 rounded-bl-md z-20">
                      RECOMMENDED
                    </div>
                  )}
                  <div className="p-4 z-10">
                    <div className="flex items-center gap-2 mb-2">
                      {plan.highlighted && (
                        <Crown className="h-3.5 w-3.5 text-primary" />
                      )}
                      <h3 className="text-sm font-medium text-zinc-700 dark:text-zinc-200">
                        {plan.name}
                      </h3>
                    </div>
                    <div className="flex items-baseline gap-1 mb-1">
                      <span className="text-2xl font-bold text-zinc-900 dark:text-zinc-100">
                        {plan.price}
                      </span>
                      {plan.period && (
                        <span className="text-xs text-zinc-500 dark:text-zinc-400">
                          / {plan.period}
                        </span>
                      )}
                    </div>
                    <p className="text-xs text-zinc-500 dark:text-zinc-400 mb-3">
                      {plan.description}
                    </p>
                    <ul className="space-y-1.5 mb-4">
                      {plan.features.map((feature) => (
                        <li
                          key={feature}
                          className="flex items-center gap-2 text-xs text-zinc-600 dark:text-zinc-300"
                        >
                          <Check className="h-3 w-3 text-primary shrink-0" />
                          {feature}
                        </li>
                      ))}
                    </ul>
                    {plan.current ? (
                      <Button
                        variant="outline"
                        size="sm"
                        className="w-full"
                        disabled
                      >
                        Current Plan
                      </Button>
                    ) : plan.name === "Enterprise" ? (
                      <Button
                        variant="outline"
                        size="sm"
                        className="w-full"
                        onClick={() =>
                          window.open("mailto:sales@agentarea.ai", "_blank")
                        }
                      >
                        Contact Sales
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
                        Upgrade to {plan.name}
                      </Button>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </section>

          <section id="usage" className="border-0 p-0">
            <div className="px-4 pt-3">
              <h2 className="text-sm font-medium text-zinc-700 dark:text-zinc-200">
                Usage
              </h2>
              <p className="mt-0.5 text-xs text-zinc-500 dark:text-zinc-400">
                Current billing period
              </p>
            </div>
            <div className="grid grid-cols-1 gap-3 p-4 sm:grid-cols-2">
              <UsageCard label="Workspaces" used={1} limit={1} />
              <UsageCard label="Agents" used={0} limit={3} />
              <UsageCard label="MCP Connections" used={0} limit={5} />
              <UsageCard label="Task Runs" used={0} limit={1000} />
            </div>
          </section>
        </div>
      </div>
    </ContentBlock>
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
