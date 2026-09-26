import type { Metadata } from "next";
import { Suspense } from "react";
import type { TriggerResponse } from "@/api/client/types.gen";
import { getTrigger } from "@/lib/api";
import { requireApiData } from "@/lib/server-resource";
import { TriggerOverview } from "./components/TriggerOverview";
import TriggerOverviewSkeleton from "./components/TriggerOverviewSkeleton";

interface Props {
  params: Promise<{ id: string }>;
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { id } = await params;
  const trigger = requireApiData<TriggerResponse>(
    await getTrigger(id),
    "trigger"
  );
  return { title: trigger.name ?? "Trigger" };
}

/** A saved automation opens on what it is doing: schedule, health, last runs.
 *
 * It used to open in the form that created it, which answered "how is this
 * configured" and left "is it working" to the other tabs. Changing it is one
 * click away, on /edit.
 */
export default async function TriggerPage({ params }: Props) {
  const { id } = await params;

  return (
    <div className="h-full overflow-auto md:overflow-hidden">
      <Suspense fallback={<TriggerOverviewSkeleton />}>
        <TriggerOverview triggerId={id} />
      </Suspense>
    </div>
  );
}
