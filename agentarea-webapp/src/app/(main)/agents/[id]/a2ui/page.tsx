import type { Metadata } from "next";
import { A2UICatalog } from "./A2UICatalog";

export const metadata: Metadata = {
  title: "Agent A2UI Components",
};

interface A2UIPageProps {
  params: Promise<{
    id: string;
  }>;
}

export default async function A2UIPage({ params }: A2UIPageProps) {
  const resolvedParams = await params;

  return (
    <div className="h-full space-y-2 overflow-auto px-4 py-5">
      <A2UICatalog agentId={resolvedParams.id} />
    </div>
  );
}
