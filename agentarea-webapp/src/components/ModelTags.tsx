import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

/** A model's tags (default, fast, cheap, ...) as small neutral badges. */
export function ModelTags({
  tags,
  className,
}: {
  tags: string[] | undefined;
  className?: string;
}) {
  if (!tags?.length) return null;
  return (
    <span className={cn("flex shrink-0 gap-1", className)}>
      {tags.map((tag) => (
        <Badge key={tag} variant="outline" size="sm">
          {tag}
        </Badge>
      ))}
    </span>
  );
}
