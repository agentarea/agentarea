import FeedSkeleton from "../components/feed/FeedSkeleton";

// The tab's content while it loads; the header and the tabs stay (layout).
export default function Loading() {
  return (
    <div className="min-w-0 flex-1 px-4 py-5">
      <FeedSkeleton />
    </div>
  );
}
