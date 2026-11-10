"use client";

import { useTranslations } from "next-intl";
import { Radio, Webhook, Zap } from "lucide-react";
import EmptyState from "@/components/EmptyState";
import type { FeedState } from "@/lib/eventFeed";
import { useFeedHref, useFeedPath } from "./FeedPath";

const ICONS = [Webhook, Radio, Zap];

/**
 * The feed with no rows: nothing arrived yet, or nothing under the filters.
 * When the platform's own events are hidden and there are some, showing them
 * is the way out offered first.
 */
export default function FeedEmptyState({
  state,
  hidesPlatform,
}: {
  state: FeedState;
  /** The platform's own events are left out, and there are some. */
  hidesPlatform: boolean;
}) {
  const t = useTranslations("EventsPage.list");
  const tFeed = useTranslations("EventsPage.feed");
  const feedHref = useFeedHref();
  const filtered = Boolean(
    state.stream ||
      state.source_type ||
      state.kind ||
      state.result ||
      state.session ||
      state.sender
  );
  const showPlatform = {
    label: t("showPlatformAction"),
    href: feedHref(state, {
      origin: "all",
      event: undefined,
      before: undefined,
    }),
  };

  // On a stream's own page: nothing has arrived on it, and its sources are
  // one tab away.
  const onStream = useFeedPath().pinned?.includes("stream");
  if (onStream && !filtered && !hidesPlatform) {
    return (
      <EmptyState
        title={t("emptyTitle")}
        description={tFeed("empty")}
        icons={ICONS}
      />
    );
  }

  if (!filtered && !hidesPlatform) {
    return (
      <EmptyState
        title={t("emptyTitle")}
        description={t("empty")}
        icons={ICONS}
        action={{ label: t("emptyAction"), href: "/events/streams" }}
      />
    );
  }

  if (!filtered) {
    return (
      <EmptyState
        title={t("onlyPlatformTitle")}
        description={t("onlyPlatform")}
        icons={ICONS}
        action={showPlatform}
      />
    );
  }

  const clear = {
    label: t("clear"),
    href: feedHref({ origin: state.origin }),
  };
  return (
    <EmptyState
      title={t("noneMatchingTitle")}
      description={
        hidesPlatform
          ? `${t("noneMatching")} ${t("platformHidden")}`
          : t("noneMatching")
      }
      icons={ICONS}
      action={hidesPlatform ? showPlatform : clear}
      additionAction={hidesPlatform ? clear : undefined}
    />
  );
}
