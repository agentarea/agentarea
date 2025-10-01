"use client";

import { TaskWithAgent } from "@/lib/api";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import Link from "next/link";
import { 
  Bot, 
  Calendar, 
  Clock,
  CheckCircle2, 
  XCircle, 
  Loader2,
  AlertCircle,
} from "lucide-react";

interface TaskItemProps {
    task: TaskWithAgent;
}

const statusConfig = {
  running: {
    icon: Loader2,
    badgeVariant: "default" as const,
    label: "Running",
  },
  completed: {
    icon: CheckCircle2,
    badgeVariant: "success" as const,
    label: "Completed",
  },
  success: {
    icon: CheckCircle2,
    badgeVariant: "success" as const,
    label: "Success",
  },
  failed: {
    icon: XCircle,
    badgeVariant: "destructive" as const,
    label: "Failed",
  },
  error: {
    icon: XCircle,
    badgeVariant: "destructive" as const,
    label: "Error",
  },
  paused: {
    icon: AlertCircle,
    badgeVariant: "secondary" as const,
    label: "Paused",
  },
  pending: {
    icon: Clock,
    badgeVariant: "secondary" as const,
    label: "Pending",
  }
};

export default function TaskItem({ task }: TaskItemProps) {
  const status = statusConfig[task.status as keyof typeof statusConfig] || statusConfig.pending;

  return (
    <Link href={`/tasks/${task.id}`}>
        <Card 
            className="group transition-all duration-300 cursor-pointer border-zinc-200 dark:border-zinc-800 overflow-hidden"
        >
            <>
                {/* Header with Status */}
                <div className="flex items-start justify-between gap-4">
                    <div className="flex-1 min-w-0">
                        {/* Title */}
                        <div className="flex-1 min-w-0 space-y-2">
                            <h3>{task.description}</h3>

                            <div className="flex items-center gap-1.5 text-xs text-zinc-500 dark:text-zinc-400">
                                <Bot className="h-3 w-3" />
                                <span>{task.agent_name || "Unknown Agent"}</span>
                            </div>
                            
                            {/* Metadata */}
                            <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-xs text-zinc-500 dark:text-zinc-400">
                                <div className="flex items-center gap-1.5">
                                    <Calendar className="h-3 w-3" />
                                    <span>{new Date(task.created_at).toLocaleDateString('en', {
                                    day: 'numeric',
                                    month: 'short',
                                    year: 'numeric'
                                    })}</span>
                                </div>
                                <div className="flex items-center gap-1.5">
                                    <Clock className="h-3 w-3" />
                                    <span>{new Date(task.created_at).toLocaleTimeString('ru-RU', {
                                    hour: '2-digit',
                                    minute: '2-digit'
                                    })}</span>
                                </div>
                            </div>
                        </div>
                    </div>

                    {/* Status Badge */}
                    <Badge 
                        variant={status.badgeVariant}
                        className="whitespace-nowrap"
                    >
                        {status.label}
                    </Badge>
                </div>
            </>
        </Card>
    </Link>
  );
}