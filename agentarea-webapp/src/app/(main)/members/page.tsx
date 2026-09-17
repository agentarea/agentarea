import { Suspense } from "react";
import type { Metadata } from "next";
import MembersData from "./MembersData";
import MembersSkeleton from "./MembersSkeleton";

export const metadata: Metadata = {
  title: "Members",
};

// MembersClient owns the page chrome (breadcrumb, invite button, tab toolbar)
// because the toolbar counts come from the same fetch as the tables.
export default function MembersPage() {
  return (
    <Suspense fallback={<MembersSkeleton />}>
      <MembersData />
    </Suspense>
  );
}
