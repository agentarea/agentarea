import { LoadingSpinner } from "@/components/LoadingSpinner";

export default function Loading() {
  return (
    <div className="flex h-full items-center justify-center py-8">
      <LoadingSpinner />
    </div>
  );
}
