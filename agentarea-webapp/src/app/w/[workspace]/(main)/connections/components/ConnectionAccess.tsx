import type { ApiResultLike } from "@/lib/api-errors";
import { ConnectionSharingSection } from "./ConnectionSharing";

/** A connection's Access tab: who may call through it. */
export default function ConnectionAccess({
  personal,
  isOwner,
  onShare,
}: {
  personal: boolean;
  isOwner: boolean;
  onShare: (shared: boolean) => Promise<ApiResultLike>;
}) {
  return (
    <div className="h-full overflow-y-auto bg-muted/20 px-4 py-5 font-inter">
      <div className="mx-auto flex w-full max-w-[1120px] flex-col gap-4">
        <ConnectionSharingSection
          personal={personal}
          isOwner={isOwner}
          onShare={onShare}
        />
      </div>
    </div>
  );
}
