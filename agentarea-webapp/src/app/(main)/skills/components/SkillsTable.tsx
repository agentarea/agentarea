"use client";

import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { formatDistanceToNow } from "date-fns";
import { FileCode, Github, Upload } from "lucide-react";
import Table from "@/components/Table/Table";
import { Badge } from "@/components/ui/badge";
import type { Skill } from "@/types/skill";

interface SkillsTableProps {
  skills: Skill[];
}

function getSourceIcon(sourceType: string) {
  switch (sourceType) {
    case "github":
      return <Github className="h-4 w-4" />;
    case "zip":
      return <Upload className="h-4 w-4" />;
    default:
      return <FileCode className="h-4 w-4" />;
  }
}

export default function SkillsTable({ skills }: SkillsTableProps) {
  const router = useRouter();
  const t = useTranslations("SkillsPage.table");
  const tSource = useTranslations("SkillsPage.source");

  function getSourceLabel(sourceType: string) {
    switch (sourceType) {
      case "github":
        return tSource("github");
      case "zip":
        return tSource("zip");
      case "path":
        return tSource("path");
      default:
        return tSource("content");
    }
  }

  const columns = [
    {
      accessor: "name",
      header: t("name"),
      render: (value: string) => (
        <span className="font-medium text-primary hover:underline">
          {value}
        </span>
      ),
    },
    {
      accessor: "description",
      header: t("description"),
      render: (value: string) => (
        <span className="max-w-md truncate text-muted-foreground block">
          {value || "-"}
        </span>
      ),
    },
    {
      accessor: "source_type",
      header: t("source"),
      render: (value: string) => (
        <Badge variant="outline" className="gap-1">
          {getSourceIcon(value)}
          {getSourceLabel(value)}
        </Badge>
      ),
    },
    {
      accessor: "created_at",
      header: t("created"),
      render: (value: string) => (
        <span className="text-muted-foreground">
          {value
            ? formatDistanceToNow(new Date(value), {
                addSuffix: true,
              })
            : "-"}
        </span>
      ),
    },
  ];

  return (
    <Table
      data={skills}
      columns={columns}
      onRowClick={(skill) => router.push(`/skills/${skill.id}`)}
    />
  );
}
