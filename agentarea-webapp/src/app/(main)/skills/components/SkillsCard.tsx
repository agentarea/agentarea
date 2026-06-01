import { useTranslations } from "next-intl";
import Link from "next/link";
import { FileCode, Github, Sparkles, Upload } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { HoverLink } from "@/components/ui/hover-link";
import { cn } from "@/lib/utils";
import type { Skill } from "@/types/skill";

interface SkillsCardProps {
  skill: Skill;
}

function SourceIcon({ sourceType }: { sourceType: string }) {
  switch (sourceType) {
    case "github":
      return <Github className="h-3 w-3" />;
    case "zip":
      return <Upload className="h-3 w-3" />;
    default:
      return <FileCode className="h-3 w-3" />;
  }
}

export default function SkillsCard({ skill }: SkillsCardProps) {
  const t = useTranslations("SkillsPage.source");

  function getSourceLabel(sourceType: string) {
    switch (sourceType) {
      case "github":
        return t("github");
      case "zip":
        return t("zip");
      case "path":
        return t("path");
      default:
        return t("content");
    }
  }

  return (
    <Link href={`/skills/${skill.id}`}>
      <div className="block h-full">
        <Card
          className={cn(
            "group relative flex h-full cursor-pointer flex-col justify-between overflow-hidden p-0 transition-all duration-300",
            "border border-zinc-200 dark:border-zinc-800",
            "bg-white dark:bg-zinc-900",
            "hover:shadow-lg hover:shadow-zinc-200/50 dark:hover:shadow-zinc-950/50",
            "hover:border-primary/20 dark:hover:border-primary/40",
            "hover:bg-white dark:hover:bg-zinc-800",
            "hover:-translate-y-0.5",
            "active:scale-[0.99]"
          )}
        >
          <div
            className="pointer-events-none absolute inset-0 opacity-[0.015] dark:opacity-[0.03]"
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

          <div className="relative z-10 flex h-full flex-col justify-between">
            <div className="flex flex-col gap-2 px-4 py-4 md:px-5">
              <div className="flex items-start gap-3">
                <div className="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-lg bg-primary/5 text-primary dark:bg-zinc-800 dark:text-zinc-200 group-hover:bg-primary/10 dark:group-hover:bg-zinc-700/80 transition-colors duration-300 border border-transparent dark:border-zinc-700/50">
                  <Sparkles className="h-4 w-4 transition-colors duration-300" />
                </div>
                <div className="min-w-0 flex-1 pt-0.5">
                  <h3 className="truncate text-[15px] font-medium leading-tight tracking-tight text-zinc-900 transition-colors duration-300 group-hover:text-primary dark:text-zinc-100 dark:group-hover:text-zinc-50">
                    {skill.name}
                  </h3>
                  {skill.description && (
                    <p className="mt-1 line-clamp-2 text-xs text-muted-foreground">
                      {skill.description}
                    </p>
                  )}
                </div>
              </div>
            </div>

            <div
              className={cn(
                "relative overflow-hidden border-t",
                "border-zinc-200/60 dark:border-zinc-700/60",
                "pl-4 pr-2 py-2.5 md:pl-5 md:pr-3",
                "transition-colors duration-500"
              )}
            >
              <div className="pointer-events-none absolute inset-0 bg-white opacity-0 transition-opacity duration-300 group-hover:opacity-100 dark:bg-zinc-800" />
              <div className="relative z-10 flex items-center justify-between">
                <Badge
                  size="sm"
                  variant="outline"
                  className="gap-1 font-normal text-muted-foreground border-transparent bg-secondary/50 px-1.5 h-5"
                >
                  <SourceIcon sourceType={skill.source_type} />
                  {getSourceLabel(skill.source_type)}
                </Badge>
                <HoverLink text="View skill" />
              </div>
            </div>
          </div>
        </Card>
      </div>
    </Link>
  );
}
