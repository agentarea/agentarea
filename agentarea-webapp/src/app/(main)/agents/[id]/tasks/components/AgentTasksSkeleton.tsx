import { LinkedCardSkeleton } from "@/components/Skeleton";

// Mirrors AgentTasksList: a grid of TaskItem cards (status badge + date row).
export default function AgentTasksSkeleton() {
  return (
    <div
      className="grid grid-cols-1 gap-2 md:grid-cols-2 lg:grid-cols-3"
      aria-hidden="true"
    >
      {Array.from({ length: 9 }).map((_, i) => (
        <LinkedCardSkeleton key={i} topRight lines={1} />
      ))}
    </div>
  );
}
