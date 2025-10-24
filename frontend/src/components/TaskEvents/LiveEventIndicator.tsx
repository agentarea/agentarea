"use client";

import { Activity, AlertCircle, CheckCircle2, Zap } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { DisplayEvent, EventLevel } from "@/types/events";

interface LiveEventIndicatorProps {
  connected: boolean;
  latestEvent?: DisplayEvent;
  eventCount: number;
  className?: string;
}

export function LiveEventIndicator({
  connected,
  latestEvent,
  eventCount,
  className = "",
}: LiveEventIndicatorProps) {
  const getStatusIcon = () => {
    if (!connected) {
      return <AlertCircle className="h-3 w-3 text-red-500" />;
    }

    if (latestEvent) {
      switch (latestEvent.level) {
        case "success":
          return <CheckCircle2 className="h-3 w-3 text-green-500" />;
        case "error":
          return <AlertCircle className="h-3 w-3 text-red-500" />;
        case "warning":
          return <AlertCircle className="h-3 w-3 text-yellow-500" />;
        default:
          return <Activity className="h-3 w-3 text-blue-500" />;
      }
    }

    return <Zap className="h-3 w-3 text-green-500" />;
  };

  const getStatusText = () => {
    if (!connected) return "Disconnected";
    if (latestEvent) return latestEvent.title;
    return "Connected";
  };

  const getStatusColor = (): string => {
    if (!connected)
      return "bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-300";

    if (latestEvent) {
      switch (latestEvent.level) {
        case "success":
          return "bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-300";
        case "error":
          return "bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-300";
        case "warning":
          return "bg-yellow-100 text-yellow-800 dark:bg-yellow-900/30 dark:text-yellow-300";
        default:
          return "bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-300";
      }
    }

    return "bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-300";
  };

  return (
    <div className={`flex items-center gap-2 ${className}`}>
      <div className="flex items-center gap-1">
        {getStatusIcon()}
        <span className="text-xs text-muted-foreground">{getStatusText()}</span>
      </div>

      {eventCount > 0 && (
        <Badge variant="secondary" className="px-1.5 py-0.5 text-xs">
          {eventCount} events
        </Badge>
      )}

      {latestEvent && (
        <Badge className={`px-1.5 py-0.5 text-xs ${getStatusColor()}`}>
          Latest: {new Date(latestEvent.timestamp).toLocaleTimeString()}
        </Badge>
      )}
    </div>
  );
}

export default LiveEventIndicator;
