import { getLocale, getTranslations } from "next-intl/server";
import { TextPreview } from "@/components/files/text-preview";
import Panel from "@/components/Panel";
import WorkspaceLink from "@/components/WorkspaceLink";
import { listStreams, listStreamSubscriptions } from "@/lib/api";
import { requireApiData } from "@/lib/server-resource";
import { formatDateTime } from "@/utils/dateUtils";

/** The code agents wrote to turn this stream's events into other streams' events; read-only. */
export default async function StreamProcessors({
  streamId,
}: {
  streamId: string;
}) {
  const [t, locale, subscriptionsResult, streamsResult] = await Promise.all([
    getTranslations("EventsPage.processors"),
    getLocale(),
    listStreamSubscriptions(streamId),
    listStreams(),
  ]);
  const processors = requireApiData(
    subscriptionsResult,
    "stream subscriptions"
  ).filter((sub) => sub.kind === "processor");
  if (processors.length === 0) return null;
  const streamNames = new Map(
    requireApiData(streamsResult, "streams").map((s) => [s.id, s.name])
  );

  return (
    <Panel title={t("title")} count={processors.length}>
      <ul className="space-y-2 p-4">
        {processors.map((processor) => {
          const kinds = Array.isArray(processor.filter.kinds)
            ? (processor.filter.kinds as string[])
            : [];
          return (
            <li key={processor.id} className="card-item space-y-2 p-3">
              <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
                <span className="font-medium">{t("writesTo")}</span>
                {processor.output_stream_ids.map((outputId, index) => (
                  <span key={outputId}>
                    {index > 0 && ", "}
                    <WorkspaceLink
                      href={`/events/${outputId}`}
                      className="text-primary hover:underline"
                    >
                      {streamNames.get(outputId) ?? outputId}
                    </WorkspaceLink>
                  </span>
                ))}
                <span className="note">
                  {kinds.length > 0
                    ? t("kinds", { kinds: kinds.join(", ") })
                    : t("everyEvent")}
                </span>
                <span className="note ml-auto">
                  {t("createdAt", {
                    time: formatDateTime(processor.created_at, locale),
                  })}
                </span>
              </div>
              {processor.code && (
                <details className="group rounded-md border border-zinc-200 dark:border-zinc-700">
                  <summary className="cursor-pointer select-none px-3 py-2 text-xs text-muted-foreground">
                    {t("code")}
                  </summary>
                  <div className="border-t border-zinc-200 dark:border-zinc-700">
                    <TextPreview path="processor.py" text={processor.code} />
                  </div>
                </details>
              )}
            </li>
          );
        })}
      </ul>
    </Panel>
  );
}
