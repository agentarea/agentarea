import { EntityAvatar, nameInitials } from "@/components/ui/entity-avatar";
import { deterministicHue } from "@/lib/avatar-hue";
import type { Workspace } from "@/lib/workspaces";

/** The workspace's logo, or its initials on its hue when it has none. */
export function WorkspaceIcon({
  workspace,
  size,
}: {
  workspace: Workspace;
  size: number;
}) {
  return (
    <EntityAvatar
      size={size}
      variant="pigment"
      hue={deterministicHue(workspace.id)}
      src={workspace.logo_url ?? undefined}
      alt={workspace.name}
      text={nameInitials(workspace.name)}
    />
  );
}
