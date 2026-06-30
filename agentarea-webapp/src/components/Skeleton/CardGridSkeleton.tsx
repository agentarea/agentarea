import { cn } from "@/lib/utils";

interface CardGridSkeletonProps {
  /** How many placeholder cards to render. */
  count?: number;
  /**
   * The exact grid classes the real list uses, so the placeholder grid has the
   * same columns/gaps/breakpoints as the loaded content.
   */
  className?: string;
  /** Per-domain card skeleton, rendered directly as a grid child. */
  Card: React.ComponentType;
}

/**
 * Loading placeholder for a card grid. Reuses the real grid classes and renders
 * `count` copies of the supplied per-domain card skeleton.
 */
export default function CardGridSkeleton({
  count = 10,
  className,
  Card,
}: CardGridSkeletonProps) {
  return (
    <div className={cn(className)} aria-hidden="true">
      {Array.from({ length: count }).map((_, index) => (
        <Card key={index} />
      ))}
    </div>
  );
}
