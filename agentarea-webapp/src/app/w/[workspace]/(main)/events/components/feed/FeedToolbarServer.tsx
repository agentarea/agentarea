import type { ComponentProps } from "react";
import { showsPlatform } from "@/lib/eventFeed";
import { readFeedPage } from "./feedPage";
import FeedToolbar from "./FeedToolbar";

/** The feed's subheader with the counts of the page the list shows, read once for both. */
export default async function FeedToolbarServer(
  props: Omit<ComponentProps<typeof FeedToolbar>, "facets">
) {
  const page = await readFeedPage(
    props.state,
    showsPlatform(props.state, props.platformStreams)
  );
  return <FeedToolbar {...props} facets={page.facets ?? null} />;
}
