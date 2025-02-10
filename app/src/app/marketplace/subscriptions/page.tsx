"use client";

import React from "react";
import { Card } from "@/components/ui/card";
import {
  Bot,
  Star,
  Users,
  BarChart2,
  Settings,
  ExternalLink,
  AlertTriangle,
  CheckCircle2
} from "lucide-react";

interface Subscription {
  id: string;
  name: string;
  description: string;
  creator: string;
  status: "active" | "suspended" | "expired";
  usageStats: {
    runsThisMonth: number;
    totalRuns: number;
    activeUsers: number;
  };
  plan: {
    name: string;
    price: number;
    billingCycle: string;
  };
  nextBilling: string;
}

const subscriptions: Subscription[] = [
  {
    id: "sub-1",
    name: "E-commerce Assistant Pro",
    description: "Advanced AI assistant for handling customer inquiries and product recommendations",
    creator: "AgentMesh",
    status: "active",
    usageStats: {
      runsThisMonth: 1234,
      totalRuns: 45678,
      activeUsers: 25
    },
    plan: {
      name: "Business",
      price: 49.99,
      billingCycle: "monthly"
    },
    nextBilling: "March 15, 2024"
  },
  {
    id: "sub-2",
    name: "Data Analysis Suite",
    description: "Comprehensive data analysis and visualization toolkit",
    creator: "DataWizards Inc",
    status: "suspended",
    usageStats: {
      runsThisMonth: 567,
      totalRuns: 12345,
      activeUsers: 10
    },
    plan: {
      name: "Enterprise",
      price: 79.99,
      billingCycle: "monthly"
    },
    nextBilling: "March 20, 2024"
  }
];

const statusColors = {
  active: "bg-green-100 text-green-700",
  suspended: "bg-yellow-100 text-yellow-700",
  expired: "bg-red-100 text-red-700"
};

const statusIcons = {
  active: <CheckCircle2 className="h-4 w-4 text-green-500" />,
  suspended: <AlertTriangle className="h-4 w-4 text-yellow-500" />,
  expired: <AlertTriangle className="h-4 w-4 text-red-500" />
};

export default function SubscriptionsPage() {
  return (
    <div className="p-8">
      <div className="flex justify-between items-center mb-8">
        <div>
          <h1 className="text-4xl font-bold">Subscriptions</h1>
          <p className="text-lg text-muted-foreground mt-2">
            Manage your marketplace subscriptions
          </p>
        </div>
      </div>

      <div className="space-y-6">
        {subscriptions.map((subscription) => (
          <Card key={subscription.id} className="p-6">
            <div className="flex items-start justify-between">
              <div className="flex items-start gap-4">
                <div className="h-12 w-12 bg-primary/10 rounded-lg flex items-center justify-center">
                  <Bot className="h-6 w-6 text-primary" />
                </div>
                <div>
                  <div className="flex items-center gap-3">
                    <h3 className="font-semibold text-lg">{subscription.name}</h3>
                    <span className={`text-sm px-2 py-1 rounded-full flex items-center gap-1 ${statusColors[subscription.status]}`}>
                      {statusIcons[subscription.status]}
                      {subscription.status.charAt(0).toUpperCase() + subscription.status.slice(1)}
                    </span>
                  </div>
                  <p className="text-sm text-muted-foreground mt-1">by {subscription.creator}</p>
                  <p className="text-sm text-muted-foreground mt-1">{subscription.description}</p>
                  
                  <div className="flex gap-6 mt-4">
                    <div>
                      <p className="text-sm font-medium">Plan</p>
                      <p className="text-sm text-muted-foreground">
                        {subscription.plan.name} (${subscription.plan.price}/{subscription.plan.billingCycle})
                      </p>
                    </div>
                    <div>
                      <p className="text-sm font-medium">Next Billing</p>
                      <p className="text-sm text-muted-foreground">{subscription.nextBilling}</p>
                    </div>
                    <div>
                      <p className="text-sm font-medium">Runs This Month</p>
                      <p className="text-sm text-muted-foreground">{subscription.usageStats.runsThisMonth}</p>
                    </div>
                    <div>
                      <p className="text-sm font-medium">Active Users</p>
                      <p className="text-sm text-muted-foreground">{subscription.usageStats.activeUsers}</p>
                    </div>
                  </div>
                </div>
              </div>
              <div className="flex items-center gap-2">
                <button className="p-2 hover:bg-secondary rounded-lg" title="View Agent">
                  <ExternalLink className="h-5 w-5" />
                </button>
                <button className="p-2 hover:bg-secondary rounded-lg" title="Subscription Settings">
                  <Settings className="h-5 w-5" />
                </button>
              </div>
            </div>
          </Card>
        ))}
      </div>
    </div>
  );
} 