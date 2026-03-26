"use client";

import { Check, CreditCard, Crown, Sparkles, Zap } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import ContentBlock from "@/components/ContentBlock";

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
      <div className="p-6 space-y-8">
        {/* Current Plan */}
        <Card>
          <CardHeader className="pb-3">
            <div className="flex items-center gap-3">
              <div className="rounded-lg bg-primary/5 p-2.5">
                <CreditCard className="h-5 w-5 text-primary/70" />
              </div>
              <div>
                <CardTitle className="text-lg">Current Plan</CardTitle>
                <CardDescription>You are on the Free plan</CardDescription>
              </div>
            </div>
          </CardHeader>
          <CardContent>
            <div className="flex items-center justify-between rounded-lg border p-4">
              <div>
                <p className="font-medium">Free Plan</p>
                <p className="text-sm text-muted-foreground">1 workspace, 3 agents, 1,000 task runs / month</p>
              </div>
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <div className="h-2 w-2 rounded-full bg-green-500" />
                Active
              </div>
            </div>
          </CardContent>
        </Card>

        {/* Plans */}
        <div>
          <h3 className="text-lg font-semibold mb-4">Available Plans</h3>
          <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
            {plans.map((plan) => (
              <Card
                key={plan.name}
                className={
                  plan.highlighted
                    ? "border-primary/50 shadow-md relative overflow-hidden"
                    : "relative overflow-hidden"
                }
              >
                {plan.highlighted && (
                  <div className="absolute top-0 right-0 bg-primary text-primary-foreground text-[10px] font-bold px-3 py-1 rounded-bl-lg">
                    RECOMMENDED
                  </div>
                )}
                <CardHeader>
                  <CardTitle className="flex items-center gap-2">
                    {plan.highlighted && <Crown className="h-4 w-4 text-primary" />}
                    {plan.name}
                  </CardTitle>
                  <div className="flex items-baseline gap-1">
                    <span className="text-3xl font-bold">{plan.price}</span>
                    {plan.period && (
                      <span className="text-sm text-muted-foreground">/ {plan.period}</span>
                    )}
                  </div>
                  <CardDescription>{plan.description}</CardDescription>
                </CardHeader>
                <CardContent className="space-y-4">
                  <ul className="space-y-2">
                    {plan.features.map((feature) => (
                      <li key={feature} className="flex items-center gap-2 text-sm">
                        <Check className="h-4 w-4 text-primary shrink-0" />
                        {feature}
                      </li>
                    ))}
                  </ul>
                  {plan.current ? (
                    <Button variant="outline" className="w-full" disabled>
                      Current Plan
                    </Button>
                  ) : plan.name === "Enterprise" ? (
                    <Button
                      variant="outline"
                      className="w-full"
                      onClick={() => window.open("mailto:sales@agentarea.ai", "_blank")}
                    >
                      Contact Sales
                    </Button>
                  ) : (
                    <Button
                      className="w-full"
                      onClick={() => window.open("https://agentarea.ai/pricing", "_blank")}
                    >
                      <Sparkles className="h-4 w-4 mr-2" />
                      Upgrade to {plan.name}
                    </Button>
                  )}
                </CardContent>
              </Card>
            ))}
          </div>
        </div>

        {/* Usage */}
        <Card>
          <CardHeader className="pb-3">
            <div className="flex items-center gap-3">
              <div className="rounded-lg bg-primary/5 p-2.5">
                <Zap className="h-5 w-5 text-primary/70" />
              </div>
              <div>
                <CardTitle className="text-lg">Usage</CardTitle>
                <CardDescription>Current billing period</CardDescription>
              </div>
            </div>
          </CardHeader>
          <CardContent className="space-y-4">
            <UsageRow label="Workspaces" used={1} limit={1} />
            <UsageRow label="Agents" used={0} limit={3} />
            <UsageRow label="MCP Connections" used={0} limit={5} />
            <UsageRow label="Task Runs" used={0} limit={1000} />
          </CardContent>
        </Card>
      </div>
    </ContentBlock>
  );
}

function UsageRow({ label, used, limit }: { label: string; used: number; limit: number }) {
  const percentage = limit > 0 ? Math.min((used / limit) * 100, 100) : 0;
  const isNearLimit = percentage >= 80;

  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between text-sm">
        <span>{label}</span>
        <span className="text-muted-foreground">
          {used} / {limit.toLocaleString()}
        </span>
      </div>
      <div className="h-2 rounded-full bg-muted overflow-hidden">
        <div
          className={`h-full rounded-full transition-all ${
            isNearLimit ? "bg-orange-500" : "bg-primary"
          }`}
          style={{ width: `${percentage}%` }}
        />
      </div>
    </div>
  );
}
