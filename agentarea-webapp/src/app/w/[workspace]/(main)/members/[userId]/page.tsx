import { Suspense } from "react";
import { MemberOverview } from "./components/MemberOverview";
import MemberOverviewSkeleton from "./components/MemberOverviewSkeleton";

interface Props {
  params: Promise<{ userId: string }>;
}

/** Who a member is, what they started, and what depends on them staying. */
export default async function MemberPage({ params }: Props) {
  const { userId } = await params;

  return (
    <div className="h-full overflow-auto md:overflow-hidden">
      <Suspense fallback={<MemberOverviewSkeleton />}>
        <MemberOverview userId={userId} />
      </Suspense>
    </div>
  );
}
