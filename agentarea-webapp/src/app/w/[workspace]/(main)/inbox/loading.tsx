import { InboxPageSkeleton } from "./components/InboxPageSkeleton";

// Shown while the inbox route loads. Same frame as the page's own Suspense
// fallback, so navigating in and streaming the data in look the same.
export default function InboxLoading() {
  return <InboxPageSkeleton />;
}
