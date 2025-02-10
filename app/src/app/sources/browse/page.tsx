"use client";

import React from "react";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  Database,
  Search,
  Filter,
  ArrowUpDown,
  CheckCircle2,
  XCircle,
  RefreshCw,
  Settings,
  Plus,
  Globe,
  FileText,
  Mail,
  MessageSquare
} from "lucide-react";

interface DataSource {
  id: string;
  name: string;
  type: string;
  status: "connected" | "disconnected" | "error";
  lastSync: string;
  description: string;
  icon: React.ReactNode;
  dataPoints: string;
}

const dataSources: DataSource[] = [
  {
    id: "source-1",
    name: "Shopify Store",
    type: "E-commerce",
    status: "connected",
    lastSync: "5 minutes ago",
    description: "Main e-commerce store data including products, orders, and customers",
    icon: <Globe className="h-6 w-6" />,
    dataPoints: "15K products, 50K orders"
  },
  {
    id: "source-2",
    name: "Customer Support Inbox",
    type: "Email",
    status: "connected",
    lastSync: "2 minutes ago",
    description: "Support email inbox for ticket processing and routing",
    icon: <Mail className="h-6 w-6" />,
    dataPoints: "1K emails/day"
  },
  {
    id: "source-3",
    name: "Analytics Database",
    type: "Database",
    status: "error",
    lastSync: "1 hour ago",
    description: "Main analytics database containing user behavior and metrics",
    icon: <Database className="h-6 w-6" />,
    dataPoints: "500GB data"
  },
  {
    id: "source-4",
    name: "Slack Workspace",
    type: "Communication",
    status: "connected",
    lastSync: "1 minute ago",
    description: "Team communication and notifications channel",
    icon: <MessageSquare className="h-6 w-6" />,
    dataPoints: "10 channels"
  },
  {
    id: "source-5",
    name: "Document Storage",
    type: "Storage",
    status: "disconnected",
    lastSync: "1 day ago",
    description: "Cloud storage for document processing and analysis",
    icon: <FileText className="h-6 w-6" />,
    dataPoints: "10K documents"
  }
];

const statusColors = {
  connected: "text-green-500",
  disconnected: "text-yellow-500",
  error: "text-red-500"
};

export default function SourcesBrowsePage() {
  return (
    <div className="p-8">
      <div className="flex justify-between items-center mb-8">
        <div>
          <h1 className="text-4xl font-bold">Data Sources</h1>
          <p className="text-lg text-muted-foreground mt-2">
            Manage your connected data sources and integrations
          </p>
        </div>
        <div className="flex gap-4">
          <button className="px-4 py-2 border rounded-lg flex items-center gap-2 hover:bg-secondary">
            <RefreshCw className="h-4 w-4" />
            Refresh All
          </button>
          <button className="bg-primary text-primary-foreground hover:bg-primary/90 px-4 py-2 rounded-lg flex items-center gap-2">
            <Plus className="h-5 w-5" />
            Add New Source
          </button>
        </div>
      </div>

      <div className="flex gap-4 mb-6">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 text-muted-foreground h-4 w-4" />
          <Input
            placeholder="Search sources..."
            className="pl-10"
          />
        </div>
        <button className="px-4 py-2 border rounded-lg flex items-center gap-2 hover:bg-secondary">
          <Filter className="h-4 w-4" />
          Filter
        </button>
        <button className="px-4 py-2 border rounded-lg flex items-center gap-2 hover:bg-secondary">
          <ArrowUpDown className="h-4 w-4" />
          Sort
        </button>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        {dataSources.map((source) => (
          <Card key={source.id} className="p-6">
            <div className="flex items-start justify-between mb-4">
              <div className="flex items-center gap-3">
                <div className="h-12 w-12 bg-primary/10 rounded-lg flex items-center justify-center">
                  {source.icon}
                </div>
                <div>
                  <h3 className="font-semibold">{source.name}</h3>
                  <span className="text-sm text-muted-foreground">{source.type}</span>
                </div>
              </div>
              <div className="flex items-center gap-2">
                {source.status === "connected" ? (
                  <CheckCircle2 className={statusColors.connected} />
                ) : source.status === "disconnected" ? (
                  <XCircle className={statusColors.disconnected} />
                ) : (
                  <XCircle className={statusColors.error} />
                )}
              </div>
            </div>
            <p className="text-sm text-muted-foreground mb-4">{source.description}</p>
            <div className="flex justify-between items-center text-sm">
              <div>
                <p className="font-medium">Last Sync</p>
                <p className="text-muted-foreground">{source.lastSync}</p>
              </div>
              <div className="text-right">
                <p className="font-medium">Data Points</p>
                <p className="text-muted-foreground">{source.dataPoints}</p>
              </div>
            </div>
            <div className="mt-4 pt-4 border-t flex justify-end gap-2">
              <button className="p-2 hover:bg-secondary rounded-lg" title="Refresh">
                <RefreshCw className="h-4 w-4" />
              </button>
              <button className="p-2 hover:bg-secondary rounded-lg" title="Settings">
                <Settings className="h-4 w-4" />
              </button>
            </div>
          </Card>
        ))}
      </div>
    </div>
  );
} 