import { FileCode, Github, Sparkles, Upload } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import type { Skill } from "@/types/skill";
import LinkedCard from "@/components/LinkedCard/LinkedCard";

interface SkillsCardProps {
  skill: Skill;
}

function getSourceIcon(sourceType: string) {
  switch (sourceType) {
    case "github":
      return <Github className="h-3 w-3" />;
    case "upload":
      return <Upload className="h-3 w-3" />;
    default:
      return <FileCode className="h-3 w-3" />;
  }
}

function getSourceLabel(sourceType: string) {
  switch (sourceType) {
    case "github":
      return "GitHub";
    case "upload":
      return "Uploaded";
    default:
      return "Content";
  }
}

export default function SkillsCard({ skill }: SkillsCardProps) {
  return (
    <LinkedCard
      href={`/skills/${skill.id}`}
      title={skill.name}
      type="view"
      icon={Sparkles}
      subtitle={
        <Badge
          size="sm"
          variant="outline"
          className="gap-1 font-normal text-muted-foreground border-transparent bg-secondary/50 hover:bg-secondary/70 px-1.5 h-5"
        >
          {getSourceIcon(skill.source_type)}
          {getSourceLabel(skill.source_type)}
        </Badge>
      }
    />
  );
}
