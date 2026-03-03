"use client";

import { useTranslations } from "next-intl";
import Link from "next/link";
import { formatDistanceToNow } from "date-fns";
import { FileCode, Github, Upload } from "lucide-react";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import type { Skill } from "@/types/skill";

interface SkillsTableProps {
  skills: Skill[];
}

function getSourceIcon(sourceType: string) {
  switch (sourceType) {
    case "github":
      return <Github className="h-4 w-4" />;
    case "upload":
      return <Upload className="h-4 w-4" />;
    default:
      return <FileCode className="h-4 w-4" />;
  }
}

export default function SkillsTable({ skills }: SkillsTableProps) {
  const t = useTranslations("SkillsPage.table");
  const tSource = useTranslations("SkillsPage.source");

  function getSourceLabel(sourceType: string) {
    switch (sourceType) {
      case "github":
        return tSource("github");
      case "upload":
        return tSource("uploaded");
      default:
        return tSource("content");
    }
  }

  return (
    <div className="rounded-md border">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>{t("name")}</TableHead>
            <TableHead>{t("description")}</TableHead>
            <TableHead>{t("source")}</TableHead>
            <TableHead>{t("created")}</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {skills.map((skill) => (
            <TableRow key={skill.id} className="cursor-pointer hover:bg-muted/50">
              <TableCell>
                <Link
                  href={`/skills/${skill.id}`}
                  className="font-medium text-primary hover:underline"
                >
                  {skill.name}
                </Link>
              </TableCell>
              <TableCell className="max-w-md truncate text-muted-foreground">
                {skill.description || "-"}
              </TableCell>
              <TableCell>
                <Badge variant="outline" className="gap-1">
                  {getSourceIcon(skill.source_type)}
                  {getSourceLabel(skill.source_type)}
                </Badge>
              </TableCell>
              <TableCell className="text-muted-foreground">
                {skill.created_at
                  ? formatDistanceToNow(new Date(skill.created_at), {
                      addSuffix: true,
                    })
                  : "-"}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
