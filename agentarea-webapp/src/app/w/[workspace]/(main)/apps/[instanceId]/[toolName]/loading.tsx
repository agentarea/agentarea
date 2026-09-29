import { getTranslations } from "next-intl/server";
import ContentBlock from "@/components/ContentBlock";

// Opening an app can wait on its MCP server starting from idle, so the viewer
// streams this state instead of holding the previous page.
export default async function Loading() {
  const t = await getTranslations("AppsPage");
  return (
    <ContentBlock
      className="p-0 overflow-hidden"
      header={{ breadcrumb: [{ label: t("title"), href: "/apps" }] }}
    >
      <div
        role="status"
        className="flex flex-1 items-center justify-center p-6 text-sm text-muted-foreground"
      >
        {t("loading")}
      </div>
    </ContentBlock>
  );
}
