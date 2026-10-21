"use client";

// A bundle opened from a link lands in the personal workspace; a member of
// several picks where it goes before setting it up. Switching moves the same
// link into the other workspace, as the sidebar's workspace switcher does.
import { useTranslations } from "next-intl";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { WorkspaceIcon } from "@/components/WorkspaceIcon";
import { useWorkspaceRouter } from "@/hooks/useWorkspaceNavigation";
import { workspacePath } from "@/lib/workspace-routes";
import type { Workspace } from "@/lib/workspaces";

export function InstallTarget({
  workspaces,
  current,
  src,
}: {
  workspaces: Workspace[];
  current: string;
  src: string;
}) {
  // A `/w/{slug}/...` href passes through unprefixed, so it can leave this one.
  const router = useWorkspaceRouter();
  const t = useTranslations("BundleInstall.target");

  return (
    <div className="flex max-w-[1120px] flex-wrap items-center gap-3">
      <span className="text-sm text-muted-foreground">{t("label")}</span>
      <Select
        value={current}
        onValueChange={(slug) =>
          router.push(
            workspacePath(slug, `/bundles/import?src=${encodeURIComponent(src)}`)
          )
        }
      >
        <SelectTrigger className="w-auto min-w-[240px]">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {workspaces.map((w) => (
            <SelectItem key={w.slug} value={w.slug}>
              <span className="flex items-center gap-2">
                <WorkspaceIcon workspace={w} size={18} />
                <span className="truncate">{w.name}</span>
                {!w.can_administer && (
                  <span className="text-xs text-muted-foreground">
                    · {t("notAdmin")}
                  </span>
                )}
              </span>
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}
