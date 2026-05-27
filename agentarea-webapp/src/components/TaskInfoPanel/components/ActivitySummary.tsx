import { useTranslations } from "next-intl";
import { Brain, Sparkles, Wrench, XCircle, Zap } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import Section from "./Section";

export interface TaskActivitySummary {
  events: number;
  llmCalls: number;
  toolsCalled: number;
  toolsFailed: number;
  uniqueTools: string[];
  learnedSkills: string[];
}

interface ActivitySummaryProps {
  summary?: TaskActivitySummary;
}

export default function ActivitySummary({ summary }: ActivitySummaryProps) {
  const t = useTranslations("TaskInfoPanel");

  if (!summary) {
    return null;
  }

  const stats = [
    {
      label: t("toolsCalled"),
      value: summary.toolsCalled,
      icon: Wrench,
      className: "text-primary",
    },
    {
      label: t("toolFailures"),
      value: summary.toolsFailed,
      icon: XCircle,
      className:
        summary.toolsFailed > 0 ? "text-destructive" : "text-muted-foreground",
    },
    {
      label: t("modelCalls"),
      value: summary.llmCalls,
      icon: Brain,
      className: "text-violet-600 dark:text-violet-400",
    },
    {
      label: t("events"),
      value: summary.events,
      icon: Zap,
      className: "text-amber-600 dark:text-amber-400",
    },
  ];

  return (
    <Section title={t("activitySummary")} contentClassName="space-y-3 text-xs">
      <div className="grid grid-cols-2 gap-2">
        {stats.map((stat) => {
          const Icon = stat.icon;
          return (
            <div
              key={stat.label}
              className="rounded-md border border-border/70 bg-background px-2.5 py-2"
            >
              <div className="flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                <Icon className={`h-3 w-3 ${stat.className}`} />
                {stat.label}
              </div>
              <div className="mt-1 text-lg font-semibold leading-none text-foreground">
                {stat.value}
              </div>
            </div>
          );
        })}
      </div>

      {summary.uniqueTools.length > 0 && (
        <div className="space-y-1.5">
          <div className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
            {t("calledTools")}
          </div>
          <div className="flex flex-wrap gap-1.5">
            {summary.uniqueTools.slice(0, 6).map((tool) => (
              <Badge
                key={tool}
                variant="outline"
                className="h-auto px-2 py-0.5 text-[10px] font-normal"
              >
                {tool}
              </Badge>
            ))}
            {summary.uniqueTools.length > 6 && (
              <Badge
                variant="secondary"
                className="h-auto px-2 py-0.5 text-[10px] font-normal"
              >
                +{summary.uniqueTools.length - 6}
              </Badge>
            )}
          </div>
        </div>
      )}

      {summary.learnedSkills.length > 0 && (
        <div className="space-y-1.5">
          <div className="flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
            <Sparkles className="h-3 w-3 text-purple-600 dark:text-purple-400" />
            {t("learnedSkills")}
          </div>
          <div className="flex flex-wrap gap-1.5">
            {summary.learnedSkills.slice(0, 6).map((skill) => (
              <Badge
                key={skill}
                variant="secondary"
                className="h-auto bg-purple-50 px-2 py-0.5 text-[10px] font-normal text-purple-700 hover:bg-purple-100 dark:bg-purple-900/30 dark:text-purple-300 dark:hover:bg-purple-900/50"
              >
                {skill}
              </Badge>
            ))}
            {summary.learnedSkills.length > 6 && (
              <Badge
                variant="secondary"
                className="h-auto px-2 py-0.5 text-[10px] font-normal"
              >
                +{summary.learnedSkills.length - 6}
              </Badge>
            )}
          </div>
        </div>
      )}
    </Section>
  );
}
