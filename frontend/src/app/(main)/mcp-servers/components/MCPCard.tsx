"use client";

import Link from "next/link";
import {
  AlertCircle,
  Bot,
  Brain,
  CheckCircle,
  Clock,
  Database,
  FileText,
  GitBranch,
  Globe,
  MessageSquare,
  Server,
  Wrench,
  XCircle,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";

interface MCPSpec {
  id: string;
  name: string;
  description: string;
  docker_image_url: string;
  version: string;
  tags: string[];
  status: string;
  is_public: boolean;
}

interface MCPInstance {
  id: string;
  name: string;
  description?: string | null;
  status: string;
  endpoint_url?: string;
  created_at: string;
  server_spec_id?: string | null;
}

interface MCPServerCardProps {
  server: MCPSpec;
  onClick?: () => void;
}

interface MCPInstanceCardProps {
  instance: MCPInstance;
  healthStatus?: "healthy" | "unhealthy" | "starting" | "unknown";
}

// Get category icon based on tags
const getCategoryIcon = (tags: string[]) => {
  if (
    tags.some(
      (tag) =>
        tag.includes("ai") ||
        tag.includes("llm") ||
        tag.includes("search") ||
        tag.includes("memory")
    )
  )
    return Brain;
  if (
    tags.some(
      (tag) =>
        tag.includes("database") ||
        tag.includes("data") ||
        tag.includes("analytics")
    )
  )
    return Database;
  if (
    tags.some(
      (tag) =>
        tag.includes("git") ||
        tag.includes("repository") ||
        tag.includes("github")
    )
  )
    return GitBranch;
  if (
    tags.some(
      (tag) =>
        tag.includes("web") || tag.includes("browser") || tag.includes("fetch")
    )
  )
    return Globe;
  if (tags.some((tag) => tag.includes("file") || tag.includes("filesystem")))
    return FileText;
  if (
    tags.some(
      (tag) =>
        tag.includes("message") ||
        tag.includes("slack") ||
        tag.includes("gmail")
    )
  )
    return MessageSquare;
  if (
    tags.some((tag) => tag.includes("automation") || tag.includes("puppeteer"))
  )
    return Bot;
  return Wrench;
};

// Get category from tags
const getCategory = (tags: string[]) => {
  if (
    tags.some(
      (tag) =>
        tag.includes("ai") ||
        tag.includes("llm") ||
        tag.includes("search") ||
        tag.includes("memory")
    )
  )
    return "AI";
  if (
    tags.some(
      (tag) =>
        tag.includes("database") ||
        tag.includes("data") ||
        tag.includes("analytics")
    )
  )
    return "Data";
  if (
    tags.some(
      (tag) =>
        tag.includes("git") ||
        tag.includes("repository") ||
        tag.includes("github")
    )
  )
    return "Dev";
  if (
    tags.some(
      (tag) =>
        tag.includes("web") || tag.includes("browser") || tag.includes("fetch")
    )
  )
    return "Web";
  if (tags.some((tag) => tag.includes("file") || tag.includes("filesystem")))
    return "Files";
  if (
    tags.some(
      (tag) =>
        tag.includes("message") ||
        tag.includes("slack") ||
        tag.includes("gmail")
    )
  )
    return "Messaging";
  return "Tools";
};

// Get status badge for instance
const getStatusBadge = (status: string, healthStatus?: string) => {
  const effectiveStatus = healthStatus || status;

  switch (effectiveStatus) {
    case "healthy":
    case "running":
      return (
        <Badge variant="success" className="w-fit">
          <CheckCircle className="mr-1 h-3 w-3" />
          Running
        </Badge>
      );
    case "unhealthy":
    case "error":
      return (
        <Badge variant="destructive" className="w-fit">
          <XCircle className="mr-1 h-3 w-3" />
          Error
        </Badge>
      );
    case "starting":
      return (
        <Badge variant="yellow" className="w-fit">
          <Clock className="mr-1 h-3 w-3" />
          Starting
        </Badge>
      );
    default:
      return (
        <Badge variant="yellow" className="w-fit">
          <AlertCircle className="mr-1 h-3 w-3" />
          Setup
        </Badge>
      );
  }
};

export function MCPServerCard({ server, onClick }: MCPServerCardProps) {
  const IconComponent = getCategoryIcon(server.tags || []);
  const category = getCategory(server.tags || []);

  const cardContent = (
    <Card className="h-full px-4 py-5">
      <div className="mb-2 flex gap-2">
        <div className="flex h-6 w-6 flex-shrink-0 items-center justify-center rounded bg-slate-100 dark:bg-slate-800">
          <IconComponent className="h-4 w-4 text-slate-600 dark:text-slate-400" />
        </div>
        <div className="min-w-0 flex-1">
          <h4 className="truncate">{server.name}</h4>
          <p className="truncate text-xs text-gray-500">{server.description}</p>
        </div>
      </div>

      {/* Category Badge */}
      <Badge variant="outline" className="text-xs">
        {category}
      </Badge>
    </Card>
  );

  if (onClick) {
    return (
      <div onClick={onClick} className="cursor-pointer">
        {cardContent}
      </div>
    );
  }

  return cardContent;
}

export function MCPInstanceCard({
  instance,
  healthStatus,
}: MCPInstanceCardProps) {
  return (
    <Link href={`/mcp-servers/${instance.id}`}>
      <Card className="h-full px-4 py-5">
        <div className="mb-2 flex gap-2">
          <div className="flex h-6 w-6 flex-shrink-0 items-center justify-center rounded bg-slate-100 dark:bg-slate-800">
            <Server className="h-4 w-4 text-slate-600 dark:text-slate-400" />
          </div>
          <div className="min-w-0 flex-1">
            <h4 className="truncate">{instance.name}</h4>
            {instance.description && (
              <p className="truncate text-xs text-gray-500">
                {instance.description}
              </p>
            )}
            {instance.endpoint_url && (
              <p className="truncate font-mono text-xs text-gray-400">
                {instance.endpoint_url}
              </p>
            )}
          </div>
        </div>

        {/* Status Badge */}
        {/* {getStatusBadge(instance.status, healthStatus)} */}
      </Card>
    </Link>
  );
}
